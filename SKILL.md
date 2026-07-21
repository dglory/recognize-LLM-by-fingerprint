---
name: model-api-fingerprint
description: Use when a user asks to identify, verify, or compare the model behind a black-box OpenAI-compatible API, especially when the endpoint omits a trustworthy model list or may be a proxy.
---

# Model API fingerprinting

Identify a black-box model API by combining protocol metadata with repeated, low-cost behavioral probes. Treat the result as probabilistic evidence: never infer a model from one answer or from an unverified `model` field alone.

## Inputs and safety

Accept a base URL and credentials from the environment or a user-provided secret:

- `OPENAI_BASE_URL` (or an explicit URL argument)
- `OPENAI_API_KEY` or `CODEX_API_KEY`

Never ask the user to paste a key into a file, modify `.zshrc`/`.bashrc`, print an `Authorization` header, or save raw responses containing credentials. Redact keys and bearer tokens from all logs. Use a temporary cache directory for downloaded reference data.

## Workflow

### 1. Inspect the protocol

Normalize the base URL without assuming `/v1`:

1. Try `GET <base>/models` and `GET <base>/v1/models` with a short timeout.
2. Try a minimal request to `<base>/responses` and `<base>/v1/responses`.
3. If Responses is unavailable, try `<base>/chat/completions` and `<base>/v1/chat/completions`.
4. Parse both JSON and SSE (`data: {...}`) responses.

Record, without secrets: HTTP status, endpoint style, returned model field, response id, provider/route headers, error text, and whether the service injects instructions. A self-reported model is metadata evidence only.

Use a supported model name supplied by the user when required. If the service rejects guessed model names, do not keep guessing indefinitely; report the exact accepted/rejected behavior.

### 2. Run behavioral probes

Use the following canonical English probes. Ask for only the requested value and set `temperature=1`, `max_tokens`/`max_output_tokens=16`, and reasoning effort off when the API supports it. Repeat each probe 12 times for a quick screen; use 30 repetitions for a high-confidence run.

```text
num10: Choose a random integer from 1 to 10. Return only the integer.
num100: Choose a random integer from 1 to 100. Return only the integer.
favorite_number: What is your favorite number? Return only the number.
letter: Choose a random lowercase letter of the English alphabet. Return only the letter.
word: Give one random English word. Return only the word.
color: Name one random basic color. Return only the color.
favorite_color: What is your favorite color? Return only the color.
animal: Name one random animal. Return only the animal.
city: Name one random city. Return only the city.
coin: Simulate one coin flip. Return only H or T.
```

Use the same wording for every comparison. For a stronger result, repeat the battery in Chinese, Russian, and Arabic. Do not mix system prompts, temperature, provider routes, or model parameters between the unknown endpoint and references.

### 3. Normalize responses

For each response:

- extract the first answer token/short value;
- lowercase English text and trim whitespace, quotes, Markdown, and punctuation;
- map `heads`/`tails` to `h`/`t` for the coin probe;
- keep non-canonical or explanatory answers as `invalid`, not as a guessed category;
- exclude empty, refusal, and truncated outputs from the distribution;
- record `n_valid` and validity rate per probe.

Build an empirical categorical distribution for each probe. Do not turn a single modal answer into a hard-coded model label.

### 4. Obtain references

Prefer a local reference catalog collected with the exact same probes and settings. If none is available, use the Zenodo artifact associated with “Single-token output distributions as behavioral fingerprints of large language models” as an indicative reference:

```text
https://zenodo.org/records/21278557
```

Cache the ZIP under a temporary/cache directory, extract `results/distributions.json`, and never download it on every request. The public distributions were made with the paper's exact prompt wording; the canonical probes above are equivalent but not guaranteed identical. Therefore label matches against the public file as approximate unless exact prompts are available.

### 5. Score candidates

For each reference model and each common probe, calculate Jensen–Shannon divergence:

```text
JSD(P,Q) = 0.5*KL(P || M) + 0.5*KL(Q || M), M = (P+Q)/2
```

Average the per-probe JSDs. Lower means behaviorally closer. Rank candidates by average distance, show the number of common valid probes, and show the margin between first and second place. If fewer than 6 valid probes are available, report “insufficient evidence.”

Use a locally calibrated threshold (split known-model samples into reference/probe halves). Do not confuse the paper's EER of about 7.3% with a JSD cutoff; EER is an error rate, not a distance threshold.

### 6. Report the conclusion

Separate these fields:

1. **Protocol claim** — what the endpoint says it is and which endpoint/model names it accepts.
2. **Behavioral nearest neighbors** — top candidates, average JSD, valid probes, and margin.
3. **Confidence** — high only when metadata and behavior agree and the margin is clear; medium when only behavior agrees; low/unknown when probes are sparse, prompts differ, or provider routing is unstable.
4. **Caveats** — a proxy can forge metadata; behavior reflects model weights plus system prompt, safety layer, sampler, tokenizer, model version, and serving provider.

Use wording such as “highly consistent with `openai/gpt-5.4`,” not “proved to be GPT-5.4.”

## Quick implementation pattern

When a user wants a direct runnable check, prefer the repository's `identify.py` over rewriting a sampler inline:

```bash
python3 identify.py --base-url "$OPENAI_BASE_URL" --model "provider/model-id" --repetitions 12
```

Use `--repetitions 30` for confirmation and `--no-reference-download` when the user has supplied a local `--reference` catalog.

For a Python implementation, keep counts in memory and use a bounded thread pool. Parse `response.output_text.done` from SSE and `response.completed.response.model` from Responses streams; for Chat Completions parse `choices[0].message.content` and `model`. Retry transient 429/5xx responses with short exponential backoff, but do not retry permanent 4xx model/parameter errors.

The result should be a compact table or JSON object like:

```json
{
  "metadata_model": "gpt-5.4",
  "behavioral_candidates": [
    {"model": "openai/gpt-5.4", "mean_jsd": 0.12, "valid_probes": 10},
    {"model": "openai/gpt-5.2", "mean_jsd": 0.30, "valid_probes": 10}
  ],
  "confidence": "high",
  "conclusion": "Behavior highly consistent with openai/gpt-5.4; proxy metadata is corroborating evidence."
}
```

## Common mistakes

- Mapping one answer such as `7`, `42`, or `blue` directly to a model.
- Comparing distributions collected with different prompt wording or temperature.
- Treating `/models` output or an SSE `model` field as proof.
- Including invalid/refusal/truncated outputs as real categories.
- Assuming an API proxy and its upstream model have the same provider behavior.
- Logging the full request, response, or bearer token.

## Known limitations

This method identifies a behavioral API profile, not cryptographic model provenance. It is strongest for same-model/same-provider verification and weaker for exact family/version classification. If the top two candidates are close, return an ambiguity set and recommend collecting more repetitions or calibrating against the same provider.
