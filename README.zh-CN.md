# Model API Fingerprint

**Language / 语言:** [English](README.md) · 简体中文 (`README.zh-CN.md`)

用黑盒行为指纹判断一个 OpenAI-compatible API 背后的模型、模型家族或代理端点。

这个项目来自对 Zenodo 数据集 [Single-token output distributions as behavioral fingerprints of large language models](https://zenodo.org/records/21278557) 的复现性整理。核心方法是不依赖权重、logprobs 或隐藏状态，而是重复发送一组低成本 prompt，比较回答分布。

> 结论是概率性鉴别，不是模型来源的密码学证明。不要把一次回答 `7`、`42` 或 `blue` 直接映射成某个模型。

## 能做什么

- 检查 API 的 `/models`、Responses API 和 Chat Completions API；
- 记录接口自报的模型名、响应格式、路由/provider 信息和错误行为；
- 对未知 API 重复运行短回答探针；
- 将回答规范化为离散概率分布；
- 用 Jensen–Shannon divergence（JSD）与参考模型指纹比较；
- 输出 Top-N 候选、距离、有效样本数、置信等级和限制条件；
- 识别“两个 API 是否可能是同一个模型”，或为未知 API 找出最接近的参考模型。

## 研究结果摘要

Zenodo 配套数据的主实验计划调用了 179 个端点，最终 165 个模型进入聚类/指纹分析，163 个进入家族分类。覆盖的主要系列包括：

| 系列 | 分析数量 |
|---|---:|
| Qwen | 30 |
| OpenAI GPT | 21 |
| Mistral | 16 |
| Claude | 12 |
| GLM | 12 |
| Llama 及其衍生模型 | 12 |
| Gemini/Gemma | 11 |
| DeepSeek | 8 |
| Amazon Nova | 5 |
| Command、Kimi、Seed | 各 4 |

完整指纹验证结果：AUC 约 0.971，EER 约 7.3%。但具体模型家族分类准确率约 59.5%，所以“同模型验证”明显强于“精确猜版本”。

## 方法概览

```text
API URL + credential
        │
        ├─ 协议元数据：/models、model 字段、响应格式、provider
        │
        ├─ 重复 probe：10 个任务 × 12/30 次
        │
        ├─ 清洗：大小写、标点、同义词、空回答、拒答、截断
        │
        ├─ 每个任务形成经验分布 P(answer | model, task)
        │
        ├─ 与参考分布计算 JSD
        │
        └─ 排序候选 + 置信度 + 局限性
```

### 探针 prompt

固定 system prompt（如果 API 支持）：

```text
Follow the user's instruction exactly. Return only the requested answer,
without explanation, punctuation, or additional text.
```

使用以下 10 个英文任务；每个任务快速筛查重复 12 次，高置信度重复 30 次：

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

推荐参数：`temperature=1`、`max_tokens`/`max_output_tokens=16`，关闭 reasoning（如果接口支持）。高质量实验还应使用中文、俄语、阿拉伯语重复同一电池。

### 分布与距离

对一个任务的 30 次回答得到经验分布，例如：

```json
{"7": 0.60, "5": 0.20, "3": 0.10}
```

两个分布 `P`、`Q` 的 JSD 为：

```text
JSD(P,Q) = 0.5 * KL(P || M) + 0.5 * KL(Q || M)
M = (P + Q) / 2
```

对所有共同有效任务的 JSD 取平均。距离越小，行为越接近。至少需要 6 个有效任务；任务不足时必须报告 `insufficient evidence`。

## 使用 Skill

将 [SKILL.md](SKILL.md) 复制到 Hermes 或其他 Agent Skills 目录：

```bash
mkdir -p "$HOME/.agents/skills/model-api-fingerprint"
cp SKILL.md "$HOME/.agents/skills/model-api-fingerprint/SKILL.md"
```

然后提供 API 地址和环境变量：

```bash
export OPENAI_BASE_URL="https://example.com/v1"
export OPENAI_API_KEY="<your-key>"
```

不要把真实 key 写入仓库、`.zshrc`、`.bashrc`、日志或 issue。建议通过 secret manager、临时环境变量或 CI secret 注入。

触发示例：

```text
请测一下这个 OpenAI-compatible API 是什么模型，使用 model-api-fingerprint skill。
```

Skill 会优先做协议探测，再执行行为采样。如果服务拒绝猜测的模型名，不要无限尝试；记录其 4xx 错误并要求用户提供支持的模型名。

## 使用命令行工具

仓库还包含一个零第三方依赖的 Python CLI，支持 Responses 和 Chat Completions，解析 JSON/SSE，重试临时错误，并把公共参考库缓存到 `~/.cache/model-api-fingerprint/distributions.json`。

```bash
export OPENAI_BASE_URL="https://example.com/v1"
export OPENAI_API_KEY="<your-key>"
python3 identify.py --model "provider/model-id" --repetitions 12
```

高可信筛查可使用 `--repetitions 30`；使用 `--workers 2` 降低并发；使用 `--reference path/to/distributions.json` 指定本地参考库；使用 `--no-reference-download` 禁止首次自动下载 Zenodo 数据。很多 API 要求 `--model`，但该值不应被当作识别真值。

对于 OpenClaw，可将同一命令暴露为 shell/exec 工具，并把 `OPENAI_BASE_URL`、`OPENAI_API_KEY` 作为运行时 secret 注入。CLI 不要求 OpenClaw 专用插件，但 Agent 必须有 Python 执行权限和出站 HTTPS 权限。

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

## 参考数据

优先使用“用完全相同 prompt、参数和 provider 采集”的本地参考库。没有本地库时，可以缓存 Zenodo 数据：

```text
https://zenodo.org/records/21278557
```

公开 ZIP 中的 `results/distributions.json` 包含每个模型、任务、语言和 temperature 的分布。它使用了论文原始 prompt；本文档的 prompt 是等价重构版本，逐字文本并未在 Zenodo 数据包中公开。因此：

- 用公开分布做候选排序时，应标记为 approximate；
- 要做高可信阈值判断，必须用同一 prompt 重新采集参考模型；
- 参考库应按 provider、系统 prompt、模型版本和采样参数分层保存。

## 输出格式

推荐返回结构化结果：

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

务必分开报告：

1. **Protocol claim**：API 自报什么、接受哪些模型名；
2. **Behavioral nearest neighbors**：行为上最接近哪些参考模型；
3. **Confidence**：高、中、低或 unknown；
4. **Caveats**：代理、路由、system prompt、采样器和模型版本的影响。

推荐使用“高度符合 `openai/gpt-5.4`”这样的措辞，不要写“证明就是 GPT-5.4”。

## 实测案例

对一个 Codex/Responses 风格的 OpenAI-compatible 代理进行 120 次采样：

- 服务只接受 `gpt-5.4`，拒绝若干其他猜测模型名；
- 120 次响应均报告 `model: gpt-5.4`；
- `num10` 和 `favorite_number` 均返回 `7`；
- 字母主要是 `q`；
- 颜色均为 `blue`；
- 动物 12 次中 11 次为 `otter`；
- 城市集中在 `valencia` 和 `oslo`；
- 硬币结果接近 H/T 各半。

将这 10 个分布与 Zenodo 中 165 个参考模型比较后：

```text
1. openai/gpt-5.4  mean JSD ≈ 0.122
2. openai/gpt-5.2  mean JSD ≈ 0.303
```

因此结论是“高度符合 GPT-5.4”，而不是仅凭响应字段下定论。

## 安全与隐私

- 不要提交或记录 API key；
- 日志中只保留脱敏后的状态码、模型名、响应 id 和统计摘要；
- 不要保存完整 prompt/response，除非已确认没有敏感数据；
- 控制并发和重试，避免触发供应商限流或产生意外费用；
- 默认使用低 `max_tokens` 和短 prompt；
- 测试完成后轮换曾经出现在聊天、终端或 issue 中的 key；
- 将目标 API 视为外部系统，不发送个人数据或生产机密。

## 局限性

该方法识别的是“API 行为系统”，不一定是裸模型权重。行为可能受以下因素影响：

- system/developer prompt；
- safety wrapper 和拒答策略；
- temperature、top-p、随机种子；
- tokenizer、量化和推理框架；
- provider 路由、批处理和缓存；
- 模型版本漂移或灰度升级。

因此方法最适合：

- 同模型/不同 API 端点验证；
- 发现代理声称模型与实际行为不一致；
- 为未知 API 提供候选集合。

不适合：

- 仅凭一次回答精确识别模型；
- 在不同 prompt、temperature 或 provider 下直接比较；
- 将行为相似误认为权重完全相同。

## 后续改进

- 发布原始 prompt 和固定版本的 reference catalog；
- 为每个 provider 单独校准阈值；
- 增加时间序列测试，检测模型漂移；
- 使用 bootstrap 置信区间，而不是只有点估计；
- 将 10 个快速 probe 扩展为 40 个任务×语言单元；
- 加入自动化脱敏、成本上限和限流保护；
- 对候选模型做 leave-one-out 和 split-half 验证。

## 引用

数据集：

> Bruckner, Tomáš. *Single-token output distributions as behavioral fingerprints of large language models*. Zenodo, 2026. DOI: [10.5281/zenodo.21278557](https://doi.org/10.5281/zenodo.21278557).

本仓库中的 [SKILL.md](SKILL.md) 是面向 Hermes/Codex 类 Agent 的操作指南，不是论文原文的复刻实现。发布到 GitHub 时，请根据实际代码和数据许可证补充 LICENSE、运行脚本和测试。
