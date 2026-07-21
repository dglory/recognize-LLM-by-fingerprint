# 通过行为识别 LLM API 背后的模型

**Language / 语言：** [English](README.md) · 简体中文

[![CI](https://github.com/dglory/recognize-LLM-by-fingerprint/actions/workflows/ci.yml/badge.svg)](https://github.com/dglory/recognize-LLM-by-fingerprint/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

手里只有一个 API 地址和 Key，不知道背后到底是什么模型？这个项目会反复询问 API 一组简单问题，再把回答规律与参考模型库进行比较，给出一个**尽可能可靠的推测**。

它适用于许多兼容 OpenAI 接口的代理和网关，不需要模型权重、隐藏状态或 logprobs。

> 重要提醒：这是行为归因，不是模型身份证明。仅凭一次回答是 `42` 或 `blue`，无法可靠识别模型。

## 快速开始

```bash
git clone https://github.com/dglory/recognize-LLM-by-fingerprint.git
cd recognize-LLM-by-fingerprint

export OPENAI_BASE_URL="https://your-api.example/v1"
export OPENAI_API_KEY="your-key"

python3 identify.py --model "provider/model-id" --repetitions 12
```

部分 API 要求请求中必须提供 `--model`。这个值只是发送给接口的模型名，工具**不会**把它当成识别证据。

首次运行可能会从 [Zenodo](https://zenodo.org/records/21278557) 下载约 52 MB 的公开参考库，并缓存到 `~/.cache/model-api-fingerprint/`。如果已有本地参考库，可使用 `--reference path/to/distributions.json --no-reference-download`。

## 工具是怎么识别的

1. 先查看接口如何描述自己，包括 `/models`、响应中的模型名、服务商信息和错误行为。
2. 重复发送一组简短且固定的问题：快速检查每题 12 次，更强检查每题 30 次。
3. 统计回答分布。例如某题返回 `7` 18 次、`5` 6 次、`3` 6 次。
4. 使用 Jensen–Shannon divergence（JSD）将回答分布与参考模型指纹比较。
5. 输出最接近的候选模型、证据数量、置信度和限制条件。

结果应该理解为：

> “这个 API 的行为与模型 **X** 高度一致。”

而不是：

> “已经证明这个 API 就是模型 **X**。”

## 如何理解结果

请始终区分下面两件事：

- **接口自报信息：** API 声称自己是什么模型、支持什么能力。
- **行为匹配结果：** 它的回答规律最像哪些参考模型。

如果前几名非常接近，正确做法是报告多个候选或 `insufficient evidence`，而不是强行猜一个模型。此时可以增加重复次数，或使用同一服务商采集自己的参考库。

## 作为 Agent Skill 使用

仓库中的 [SKILL.md](SKILL.md) 可以让 Hermes、Codex 类 Agent 和其他支持 Skills 的工具自动执行识别流程。

```bash
mkdir -p "$HOME/.agents/skills/model-api-fingerprint"
cp SKILL.md "$HOME/.agents/skills/model-api-fingerprint/SKILL.md"
```

通过运行时环境变量提供 API 地址和 Key，然后对 Agent 说：

```text
请使用 model-api-fingerprint skill 识别这个 OpenAI-compatible API 背后的模型。
```

不要把 Key 写入代码、提示词、Git 提交或 GitHub Issue。

## 命令行选项

```bash
python3 identify.py --help
```

常用选项：

- `--repetitions 30`：收集更多样本，增强证据；
- `--workers 2`：降低并发，减少触发限流的风险；
- `--reference FILE`：使用本地参考库；
- `--no-reference-download`：禁止自动下载参考库。

CLI 支持 Chat Completions 和 Responses 风格接口，能解析 JSON/SSE、重试临时错误并缓存参考库。OpenClaw 可以直接通过 shell/exec 工具运行相同命令，不需要专用插件。

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

## 指纹探针

接口支持 system prompt 时，使用：

```text
Follow the user's instruction exactly. Return only the requested answer,
without explanation, punctuation, or additional text.
```

快速探针会要求模型随机选择数字、字母、单词、颜色、动物、城市和硬币正反面。参考模型与未知 API 必须使用完全相同的提示词、temperature、输出长度和 reasoning 设置，否则比较结果可能失真。

需要更强证据时，可以用多种语言重复测试。测试中不要发送个人数据、生产数据或公司机密。

## 研究依据

本项目基于论文及数据集 [Single-token output distributions as behavioral fingerprints of large language models](https://zenodo.org/records/21278557)。论文使用完整的 40 组测试时，同模型验证约达到 **AUC 0.971**、**EER 7.3%**；但精确识别模型家族或版本的准确率只有约 **59.5%**。因此，“判断两个端点是否像同一个模型”通常比“精确说出模型版本”更可靠。

公开参考库覆盖 GPT、Claude、Gemini/Gemma、Qwen、Mistral、Llama 衍生模型、DeepSeek、GLM、Nova、Kimi、Command 等系列。数据包没有公开论文使用的逐字提示词，因此用本仓库重构提示词得到的匹配应标记为近似结果。

## 局限与安全

工具识别的是一个 **API 行为特征**，不一定是裸模型权重。系统提示词、安全策略、temperature、tokenizer、量化方式、服务商路由、缓存和模型升级都会影响结果。

- 使用临时环境变量或 secret manager 保存 API Key；
- 日志中隐藏 bearer token；
- 限制重复次数、并发、重试、费用和输出长度；
- 曾出现在聊天、终端、日志或 Issue 中的 Key 应及时轮换。

## 引用

> Bruckner, Tomáš. *Single-token output distributions as behavioral fingerprints of large language models*. Zenodo, 2026. [DOI: 10.5281/zenodo.21278557](https://doi.org/10.5281/zenodo.21278557)。

本仓库是面向 Agent 和 API 审计场景的操作实现，不是论文作者发布的原始实现。
