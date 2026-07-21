# Recognize an LLM API by its behavior

**Language / 语言:** English · [简体中文](README.zh-CN.md)

[![CI](https://github.com/dglory/recognize-LLM-by-fingerprint/actions/workflows/ci.yml/badge.svg)](https://github.com/dglory/recognize-LLM-by-fingerprint/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

You have an API URL and a key, but you do not know what model is really behind it? This project makes a **best-effort identification** by asking the API the same small set of questions many times and comparing the answer patterns with a reference collection.

It works with many OpenAI-compatible proxies and gateways. It does not need model weights, hidden states, or logprobs.

> Important: this is behavioral attribution, not proof of model identity. Although the method is supported by research, the result should only be used as a reference.

## Research basis

This workflow is based on [Single-token output distributions as behavioral fingerprints of large language models](https://zenodo.org/records/21278557). In the paper's verification experiment, the full 40-cell battery reached approximately **AUC 0.971** and **EER 7.3%**. Exact family/version classification was weaker (about **59.5% accuracy**), so same-model verification is more reliable than naming an exact version.

The public catalog covers GPT, Claude, Gemini/Gemma, Qwen, Mistral, Llama derivatives, DeepSeek, GLM, Nova, Kimi, Command, and smaller families. The catalog's original prompt text was not included, so matches made with this repository's reconstructed prompts should be treated as approximate.

## Quick start

```bash
git clone https://github.com/dglory/recognize-LLM-by-fingerprint.git
cd recognize-LLM-by-fingerprint

export OPENAI_BASE_URL="https://your-api.example/v1"
export OPENAI_API_KEY="your-key"

python3 identify.py --model "provider/model-id" --repetitions 12
```

The `--model` value is required by some APIs. It is only the name sent in the request; the tool does **not** treat it as evidence.

The first run may download the public reference catalog from [Zenodo](https://zenodo.org/records/21278557) (about 52 MB) and cache it in `~/.cache/model-api-fingerprint/`. To use a local file instead, pass `--reference path/to/distributions.json --no-reference-download`.

## What the tool does

1. Checks what the endpoint says about itself (`/models`, response metadata, provider hints, and errors).
2. Sends short, controlled prompts repeatedly (12 times for a quick check, 30 for a stronger check).
3. Counts the answers. For example, an API might return `7` 18 times, `5` 6 times, and `3` 6 times.
4. Compares those answer distributions with reference fingerprints using Jensen–Shannon divergence (JSD).
5. Reports the closest candidates, the amount of evidence, and caveats.

The result should be read as:

> “This API is highly consistent with **X**,”

not:

> “This proves the API is **X**.”

## Understanding the output

Keep these two facts separate:

- **Protocol claim:** the model name and capabilities reported by the API.
- **Behavioral match:** the models whose response patterns look most similar.

If the top candidates are close, the correct answer is an ambiguity set or `insufficient evidence`. Run more repetitions or build a reference catalog from the same provider.

## Use it as an Agent Skill

The included [SKILL.md](SKILL.md) lets Hermes, Codex-style agents, and similar tools run the workflow for you.

```bash
mkdir -p "$HOME/.agents/skills/model-api-fingerprint"
cp SKILL.md "$HOME/.agents/skills/model-api-fingerprint/SKILL.md"
```

Then provide the endpoint and key through runtime environment variables and ask:

```text
Use the model-api-fingerprint skill to identify this OpenAI-compatible API.
```

Never paste keys into source files, prompts, Git commits, or issue reports.

## CLI options

```bash
python3 identify.py --help
```

Useful options:

- `--repetitions 30` — collect stronger evidence;
- `--workers 2` — limit concurrency and reduce rate-limit risk;
- `--reference FILE` — use a local reference catalog;
- `--no-reference-download` — forbid automatic downloads.

The CLI supports Chat Completions and Responses-style endpoints, JSON and SSE responses, transient-error retries, and local reference caching. OpenClaw can run the same command through its shell/exec tool; no OpenClaw-specific plugin is required.

Run the tests with:

```bash
python3 -m unittest discover -s tests -v
```

## Prompts used for fingerprinting

When supported, use this system instruction:

```text
Follow the user's instruction exactly. Return only the requested answer,
without explanation, punctuation, or additional text.
```

The quick battery asks for random numbers, a letter, a word, colors, an animal, a city, and a coin flip. The exact wording and sampling settings matter; use the same prompts, temperature, token limit, and reasoning settings for reference and unknown APIs.

For a stronger screen, repeat the battery in several languages. Do not send personal, confidential, or production data.

## Limitations and safety

Results describe an **API behavior profile**, not necessarily bare model weights. Behavior can change because of system prompts, safety wrappers, temperature, tokenizer, quantization, routing, caching, model updates, or provider changes.

- Keep API keys in environment variables or a secret manager.
- Redact bearer tokens from logs.
- Limit repetitions, concurrency, retries, cost, and output tokens.
- Rotate any key that was exposed in chat, terminals, logs, or issues.

## Citation

> Bruckner, Tomáš. *Single-token output distributions as behavioral fingerprints of large language models*. Zenodo, 2026. [DOI: 10.5281/zenodo.21278557](https://doi.org/10.5281/zenodo.21278557).

This repository is an operational implementation for Agents and API audits, not the original paper's implementation.
