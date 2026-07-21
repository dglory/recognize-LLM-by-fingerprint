#!/usr/bin/env python3
"""Identify an OpenAI-compatible API by repeated behavioral probes."""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ZENODO_FILE = "https://zenodo.org/api/records/21278557/files/pamela-publish-data.zip/content"
DEFAULT_CACHE = Path.home() / ".cache" / "model-api-fingerprint" / "distributions.json"
PROBES = {
    "num10-random": "Choose a random integer from 1 to 10. Return only the integer.",
    "num100-random": "Choose a random integer from 1 to 100. Return only the integer.",
    "num-favorite": "What is your favorite number? Return only the number.",
    "letter-random": "Choose a random lowercase letter of the English alphabet. Return only the letter.",
    "word-random": "Give one random English word. Return only the word.",
    "color-random": "Name one random basic color. Return only the color.",
    "color-favorite": "What is your favorite color? Return only the color.",
    "animal-random": "Name one random animal. Return only the animal.",
    "city-random": "Name one random city. Return only the city.",
    "coin-flip": "Simulate one coin flip. Return only H or T.",
}
SYSTEM_PROMPT = (
    "Follow the user's instruction exactly. Return only the requested answer, "
    "without explanation, punctuation, or additional text."
)
_lock = threading.Lock()


def canonicalize_answer(value: str | None, task: str) -> str | None:
    """Return a short canonical answer, or None for invalid/explanatory output."""
    if not value:
        return None
    text = value.strip().lower()
    text = re.sub(r"^```(?:text)?\s*|\s*```$", "", text).strip()
    text = text.strip("`\"'.,;:!?()[]{}")
    if not text or len(text.split()) > 3 or re.search(r"\b(the answer is|here is|sure)\b", text):
        return None
    if task in {"coin", "coin-flip"}:
        if text in {"h", "heads", "head"}:
            return "h"
        if text in {"t", "tails", "tail"}:
            return "t"
        return None
    if task in {"num10-random", "num100-random", "num-favorite"}:
        return text if re.fullmatch(r"-?\d+", text) else None
    if task == "letter-random":
        return text if re.fullmatch(r"[a-z]", text) else None
    if task in {"word-random", "color-random", "color-favorite", "animal-random", "city-random"}:
        return text if re.fullmatch(r"[\w-]+", text, flags=re.UNICODE) else None
    return text


def empirical_distribution(values: list[str], task: str) -> tuple[dict[str, float], int, int]:
    counts: collections.Counter[str] = collections.Counter()
    invalid = 0
    for value in values:
        answer = canonicalize_answer(value, task)
        if answer is None:
            invalid += 1
        else:
            counts[answer] += 1
    total = sum(counts.values())
    return ({k: v / total for k, v in counts.items()} if total else {}, total, invalid)


def js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    keys = set(p) | set(q)
    midpoint = {key: (p.get(key, 0.0) + q.get(key, 0.0)) / 2 for key in keys}

    def kl(dist: dict[str, float]) -> float:
        return sum(value * math.log2(value / midpoint[key]) for key, value in dist.items() if value)

    return (kl(p) + kl(q)) / 2


def rank_candidates(
    observed: dict[str, dict[str, float]],
    references: dict[str, dict[str, dict[str, float]]],
    min_common: int = 6,
) -> list[dict[str, Any]]:
    ranked = []
    for model, reference in references.items():
        common = [task for task in observed if task in reference]
        if len(common) < min_common:
            continue
        distances = [js_divergence(observed[task], reference[task]) for task in common]
        ranked.append({"model": model, "mean_jsd": sum(distances) / len(distances), "valid_probes": len(common)})
    return sorted(ranked, key=lambda row: row["mean_jsd"])


def parse_response_payload(payload: str | bytes) -> dict[str, Any]:
    """Extract text/model from JSON or Server-Sent Events."""
    raw = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        data = line[6:].strip()
        if data and data != "[DONE]":
            try:
                events.append(json.loads(data))
            except json.JSONDecodeError:
                pass
    if not events:
        try:
            events = [json.loads(raw)]
        except json.JSONDecodeError:
            events = []

    text = None
    model = None
    delta_parts: list[str] = []
    for event in events:
        kind = event.get("type")
        if kind == "response.output_text.done":
            text = event.get("text")
        if kind == "response.completed":
            response = event.get("response") or {}
            model = response.get("model") or model
            text = text or response.get("output_text")
        if kind == "response.output_text.delta":
            delta_parts.append(event.get("delta", ""))
        model = event.get("model") or model
        if text is None and isinstance(event.get("output_text"), str):
            text = event["output_text"]
        if text is None and isinstance(event.get("output"), list):
            for item in event["output"]:
                for content in item.get("content", []) if isinstance(item, dict) else []:
                    if isinstance(content, dict) and isinstance(content.get("text"), str):
                        text = content["text"]
                        break
                if text is not None:
                    break
        if text is None and isinstance(event.get("choices"), list) and event["choices"]:
            message = event["choices"][0].get("message") or {}
            text = message.get("content") or event["choices"][0].get("text")
    if text is None and delta_parts:
        text = "".join(delta_parts)
    return {"text": text, "model": model, "events": events}


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class ApiClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.kind: str | None = None
        self.endpoint: str | None = None
        self.metadata: dict[str, Any] = {"model_argument": model, "models_status": {}}

    def _url(self, path: str) -> str:
        path = path.lstrip("/")
        if self.base.endswith("/v1") and path.startswith("v1/"):
            path = path[3:]
        return f"{self.base}/{path}"

    def _request(self, method: str, url: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, str], bytes]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json, text/event-stream"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            try:
                message = error.read(512).decode("utf-8", "replace")
            except Exception:
                message = error.reason or "HTTP error"
            raise ApiError(error.code, message[:300]) from error
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            raise ApiError(0, type(error).__name__) from error

    def discover(self) -> dict[str, Any]:
        for path in ("models", "v1/models"):
            try:
                status, _, body = self._request("GET", self._url(path))
                parsed = json.loads(body.decode("utf-8", "replace"))
                ids = [item.get("id") for item in parsed.get("data", []) if item.get("id")]
                self.metadata["models_status"][path] = {"status": status, "ids": ids[:100]}
            except (ApiError, json.JSONDecodeError) as error:
                self.metadata["models_status"][path] = {"status": getattr(error, "status", 0)}

        body = self._responses_body("Return exactly: OK")
        for kind, path in (("responses", "responses"), ("responses", "v1/responses"), ("chat", "chat/completions"), ("chat", "v1/chat/completions")):
            try:
                status, headers, raw = self._request("POST", self._url(path), body if kind == "responses" else self._chat_body("Return exactly: OK"))
                parsed = parse_response_payload(raw)
                if status < 300 and parsed.get("text") is not None:
                    self.kind, self.endpoint = kind, path
                    self.metadata.update({"endpoint": path, "reported_model": parsed.get("model"), "response_headers": _safe_headers(headers)})
                    return self.metadata
            except ApiError as error:
                self.metadata.setdefault("probe_errors", []).append({"endpoint": path, "status": error.status, "message": str(error)})
        raise RuntimeError("No supported Responses or Chat Completions endpoint succeeded")

    def _responses_body(self, prompt: str) -> dict[str, Any]:
        return {"model": self.model, "input": prompt, "temperature": 1, "max_output_tokens": 16, "reasoning": {"effort": "none"}}

    def _chat_body(self, prompt: str) -> dict[str, Any]:
        return {"model": self.model, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}], "temperature": 1, "max_tokens": 16}

    def ask(self, prompt: str) -> tuple[str | None, str | None]:
        if not self.endpoint or not self.kind:
            self.discover()
        body = self._responses_body(prompt) if self.kind == "responses" else self._chat_body(prompt)
        for attempt in range(3):
            try:
                status, _, raw = self._request("POST", self._url(self.endpoint or "responses"), body)
                if status >= 300:
                    raise ApiError(status, "HTTP error")
                parsed = parse_response_payload(raw)
                return parsed.get("text"), parsed.get("model")
            except ApiError as error:
                if error.status not in (0, 429, 500, 502, 503, 504) or attempt == 2:
                    return None, None
                time.sleep(0.5 * (2**attempt))
        return None, None


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    keep = ("x-provider", "x-model", "server", "trace-id", "openai-processing-ms")
    return {key.lower(): value for key, value in headers.items() if key.lower() in keep}


def load_references(path: Path) -> dict[str, dict[str, dict[str, float]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    references: dict[str, dict[str, dict[str, float]]] = collections.defaultdict(dict)
    for row in data.get("distributions", data if isinstance(data, list) else []):
        if row.get("lang") == "en" and row.get("temperature") == 1 and row.get("task_id") in PROBES:
            references[row["model"]][row["task_id"]] = row.get("dist", {})
    return dict(references)


def ensure_reference(path: Path, allow_download: bool = True) -> Path | None:
    if path.exists():
        return path
    if not allow_download:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    archive = path.with_suffix(".zip")
    request = urllib.request.Request(ZENODO_FILE, headers={"Accept": "application/octet-stream"})
    with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    with zipfile.ZipFile(archive) as bundle, bundle.open("results/distributions.json") as source, path.open("wb") as output:
        while chunk := source.read(1024 * 1024):
            output.write(chunk)
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    key = args.api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEX_API_KEY")
    base_url = args.base_url or os.environ.get("OPENAI_BASE_URL")
    if not key or not base_url:
        raise SystemExit("Set OPENAI_BASE_URL and OPENAI_API_KEY/CODEX_API_KEY, or pass --base-url/--api-key")
    client = ApiClient(base_url, key, args.model, args.timeout)
    client.discover()
    observations: dict[str, dict[str, float]] = {}
    validity: dict[str, dict[str, int]] = {}
    jobs = [(task, repetition) for task in PROBES for repetition in range(args.repetitions)]
    values: dict[str, list[str]] = collections.defaultdict(list)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(client.ask, PROBES[task]): task for task, _ in jobs}
        for future in as_completed(futures):
            task = futures[future]
            try:
                text, _ = future.result()
            except Exception:
                text = None
            if text is not None:
                values[task].append(text)
    for task in PROBES:
        dist, valid, invalid = empirical_distribution(values[task], task)
        observations[task] = dist
        validity[task] = {"valid": valid, "invalid": invalid, "requested": args.repetitions}

    reference_path = Path(args.reference).expanduser() if args.reference else DEFAULT_CACHE
    references = {}
    reference_warning = None
    try:
        resolved = ensure_reference(reference_path, not args.no_reference_download)
        if resolved:
            references = load_references(resolved)
        else:
            reference_warning = "No reference catalog supplied"
    except Exception as error:
        reference_warning = f"Reference download/load failed: {type(error).__name__}"
    ranked = rank_candidates(observations, references, min_common=6)
    confidence = "unknown"
    if ranked:
        margin = ranked[1]["mean_jsd"] - ranked[0]["mean_jsd"] if len(ranked) > 1 else 0
        confidence = "high" if margin >= 0.10 and ranked[0]["valid_probes"] >= 8 else "medium"
    return {
        "metadata": client.metadata,
        "behavioral_candidates": ranked[: args.top],
        "confidence": confidence,
        "validity": validity,
        "reference_warning": reference_warning,
        "reference_note": "Public Zenodo distributions are approximate unless probe wording matches exactly.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url")
    parser.add_argument("--api-key")
    parser.add_argument("--model", required=True, help="Model argument required by the target API; not treated as ground truth")
    parser.add_argument("--reference", help="Local distributions.json reference catalog")
    parser.add_argument("--no-reference-download", action="store_true")
    parser.add_argument("--repetitions", type=int, default=12)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
