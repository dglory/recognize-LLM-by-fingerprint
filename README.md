# Model API Fingerprint

**Language / 语言:** English · [简体中文](README.zh-CN.md)

Identify the model behind a black-box OpenAI-compatible API using repeated behavioral probes. The method does not require model weights, hidden states, or logprobs: it compares empirical answer distributions with reference fingerprints.

> This is probabilistic attribution, not cryptographic proof. Never identify a model from one answer such as `7`, `42`, or `blue`.

## What it does

- probes `/models`, Responses API, and Chat Completions API;
- records self-reported model metadata, response format, route/provider hints, and errors;
- repeats short, low-cost prompts against an unknown endpoint;
- normalizes answers into categorical distributions;
- ranks reference models with Jensen–Shannon divergence (JSD);
- reports candidates, distance, valid-sample count, confidence, and caveats;
- separates “what the API claims” from “what its behavior resembles.”

## Research basis

This workflow is based on the Zenodo artifact [Single-token output distributions as behavioral fingerprints of large language models](https://zenodo.org/records/21278557).

The main run planned 179 endpoints; 165 models had enough usable data for fingerprint/clustering analysis and 163 entered family classification. It covered GPT, Claude, Gemini/Gemma, Qwen, Mistral, Llama derivatives, DeepSeek, GLM, Nova, Kimi, Command, and many smaller families.

The full 40-cell verification battery reached approximately AUC `0.971` and EER `7.3%`. Family classification was much weaker (about `59.5%` accuracy), so same-model verification is more reliable than exact version attribution.

## Method

```text
API URL + credential
        │
        ├─ Protocol metadata: models, response model, provider, errors
        ├─ Repeated probes: 10 tasks × 12/30 repetitions
        ├─ Normalization: case, punctuation, aliases, invalid/refusal outputs
        ├─ Empirical answer distribution per task
        ├─ JSD against reference distributions
        └─ Ranked candidates + confidence + limitations
```

### Probe prompts

Use this system instruction when supported:

```text
Follow the user's instruction exactly. Return only the requested answer,
without explanation, punctuation, or additional text.
```

Use the same wording and parameters for every reference and unknown API:

```text
Choose a random integer from 1 to 10. Return only the integer.
Choose a random integer from 1 to 100. Return only the integer.
What is your favorite number? Return only the number.
Choose a random lowercase letter of the English alphabet. Return only the letter.
Give one random English word. Return only the word.
Name one random basic color. Return only the color.
What is your favorite color? Return only the color.
Name one random animal. Return only the animal.
Name one random city. Return only the city.
Simulate one coin flip. Return only H or T.
```

Use `temperature=1`, `max_tokens`/`max_output_tokens=16`, and disable reasoning where supported. Repeat each task 12 times for a quick screen or 30 times for a high-confidence run. Repeat the battery in Chinese, Russian, and Arabic for stronger evidence.

### Distribution and scoring

Thirty answers become an empirical distribution, for example:

```json
{"7": 0.60, "5": 0.20, "3": 0.10}
```

For distributions `P` and `Q`:

```text
JSD(P,Q) = 0.5 * KL(P || M) + 0.5 * KL(Q || M)
M = (P + Q) / 2
```

Average JSD across common valid tasks. Lower means behaviorally closer. Require at least six valid tasks; otherwise return `insufficient evidence`.

## Use the Skill

Install [SKILL.md](SKILL.md) in a Hermes or Agent Skills directory:

```bash
mkdir -p "$HOME/.agents/skills/model-api-fingerprint"
cp SKILL.md "$HOME/.agents/skills/model-api-fingerprint/SKILL.md"
```

Provide credentials through the environment, never by committing them:

```bash
export OPENAI_BASE_URL="https://example.com/v1"
export OPENAI_API_KEY="<your-key>"
```

Example request:

```text
Use the model-api-fingerprint skill to identify this OpenAI-compatible API.
```

The skill first checks protocol metadata, then samples behavior, parses JSON or SSE, computes JSD, and returns ranked candidates. It must not guess model names indefinitely after permanent 4xx errors.

## Use the CLI

The repository also includes a dependency-free Python CLI. It supports Responses and Chat Completions endpoints, parses JSON/SSE, retries transient failures, and caches the public reference catalog at `~/.cache/model-api-fingerprint/distributions.json`.

```bash
export OPENAI_BASE_URL="https://example.com/v1"
export OPENAI_API_KEY="<your-key>"
python3 identify.py --model "provider/model-id" --repetitions 12
```

Use `--repetitions 30` for a stronger screen, `--workers 2` for a conservative rate, `--reference path/to/distributions.json` for a local catalog, or `--no-reference-download` to forbid the first-run Zenodo download. The `--model` value is required by many APIs and is not treated as truth.

For OpenClaw, expose the same command through its shell/exec tool and pass `OPENAI_BASE_URL` and `OPENAI_API_KEY` as runtime secrets. No OpenClaw-specific plugin is required for the CLI; the agent only needs permission to run Python and make outbound HTTPS requests.

Run tests with:

```bash
python3 -m unittest discover -s tests -v
```

## Reference data

Prefer a local catalog collected with exactly the same prompts, parameters, and provider. Otherwise cache the Zenodo artifact:

```text
https://zenodo.org/records/21278557
```

The ZIP contains `results/distributions.json`. The public distributions use the paper's exact prompt wording; the prompts in this repository are equivalent reconstructions because the original prompt text was not included in the data package. Mark matches against the public file as approximate unless exact prompts are available.

## Recommended output

```json
{
  "metadata_model": "gpt-5.4",
  "behavioral_candidates": [
    {"model": "openai/gpt-5.4", "mean_jsd": 0.12, "valid_probes": 10},
    {"model": "openai/gpt-5.2", "mean_jsd": 0.30, "valid_probes": 10}
  ],
  "confidence": "high",
  "conclusion": "Highly consistent with openai/gpt-5.4; metadata is corroborating evidence."
}
```

Always separate:

1. **Protocol claim** — what the endpoint reports and accepts;
2. **Behavioral nearest neighbors** — what the responses resemble;
3. **Confidence** — high, medium, low, or unknown;
4. **Caveats** — proxy, routing, prompts, sampler, tokenizer, and version effects.

Say “highly consistent with `openai/gpt-5.4`,” not “proved to be GPT-5.4.”

## Example observation

One Codex/Responses-style proxy was sampled 120 times. It accepted `gpt-5.4`, rejected several guessed model names, and reported `gpt-5.4` in every successful response. Its behavior was concentrated around `7`, `q`, `blue`, `otter`, `valencia/oslo`, and near-balanced H/T coin flips.

Against 165 Zenodo reference models, the nearest candidates were:

```text
1. openai/gpt-5.4  mean JSD ≈ 0.122
2. openai/gpt-5.2  mean JSD ≈ 0.303
```

The defensible conclusion is “highly consistent with GPT-5.4,” not a claim of provenance.

## Security and privacy

- never commit or print API keys;
- redact bearer tokens and full authorization headers;
- avoid storing raw responses unless they contain no sensitive data;
- cap concurrency, retries, cost, and output tokens;
- do not send personal or production-confidential data;
- rotate keys that appeared in chat, terminals, logs, or issues.

## Limitations

The method identifies an API behavior profile, not necessarily bare model weights. Behavior can change with system/developer prompts, safety wrappers, temperature, random seeds, tokenizer, quantization, inference framework, provider routing, caching, and model drift.

It is strongest for same-model/same-provider verification and weaker for exact family/version classification. If the top candidates are close, return an ambiguity set and collect more repetitions or calibrate against the same provider.

## Future work

- publish exact prompts and versioned reference catalogs;
- calibrate thresholds per provider;
- add time-series drift detection;
- report bootstrap confidence intervals;
- expand the quick battery to 40 task-language cells;
- add cost limits, redaction, and rate-limit protection;
- validate with leave-one-out and split-half experiments.

## Citation

> Bruckner, Tomáš. *Single-token output distributions as behavioral fingerprints of large language models*. Zenodo, 2026. DOI: [10.5281/zenodo.21278557](https://doi.org/10.5281/zenodo.21278557).

This repository's [SKILL.md](SKILL.md) is an operational guide for Hermes/Codex-style agents, not the original paper implementation. Add a license, runnable scripts, tests, and a pinned data version before publishing a production-ready fork.
