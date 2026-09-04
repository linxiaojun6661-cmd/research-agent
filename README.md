# 研报 Agent（ResearchPilot）

多智能体调研报告流水线：输入一个主题，自动完成 **搜索 → 资料汇编 → 撰写 → 审查 → 修订**，输出带引用溯源的中文 Markdown 报告。

## 特性

- **多智能体流水线**：researcher / writer / reviewer / reviser 四角色协作，有界修订循环（不依赖现成 Agent 框架）
- **引用可溯源**：每个关键论断带 `[n]` 标注，文末列出对应 URL
- **三层安全**：搜索词检查 + URL 白名单 + 计划人工确认（human-in-the-loop）
- **成本控制**：token 预算上限、超限自动降级交付草稿、重试分级（暂时性错误才重试，指数退避）
- **全链路可观测**：JSONL trace 记录每次 API/工具调用的耗时与 token
- **三层评估体系**：规则断言（零成本）+ LLM-as-judge 报告评分 + Golden 主题集回归

## 架构

```
main.py          CLI 入口（参数解析、报告落盘）
pipeline.py      四角色流水线（research → write → review → revise）
├── tools.py          工具层（Tavily 搜索 / 计算器 / 知识库）
├── safety.py         安全层（查询检查 / URL 白名单 / 人工确认）
├── cost_control.py   可靠性层（token 预算 / 重试分级 / 指数退避）
└── trace_log.py      可观测层（JSONL 全链路日志）
eval_safety.py   安全评测（断言，零 API 成本）
eval_report.py   报告质量评测（LLM-as-judge）
eval_runner.py   Golden 回归（管线 + judge + 成本断言三合一）
```

## 快速开始

### 1. 环境

```bash
pip install openai httpx python-dotenv
```

### 2. 配置 Key

```bash
cp .env.example .env
```

编辑 `.env`，填入：

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key（必填） |
| `TAVILY_API_KEY` | Tavily 搜索 Key（必填，https://tavily.com 免费注册） |

### 3. 跑第一份报告

```bash
python main.py "2026 年国产大模型现状"
```

流程：生成搜索计划 → **人工确认（y/N）** → 调研 → 撰写 → 审查修订 → 报告保存到 `outputs/`，trace 保存到 `traces/`。

## CLI 用法

```bash
python main.py "主题"              # 完整流程（计划需人工确认）
python main.py "主题" --yes        # 跳过人工确认
python main.py "主题" --budget 50000   # 覆盖 token 预算（默认 200,000）
python main.py --list-traces       # 查看最近的运行日志
```

## 评测

```bash
python eval_safety.py              # 安全断言测试（12 项，零 API 成本）
python eval_report.py              # judge 评测 outputs/ 最新报告
python eval_runner.py              # Golden 回归（跑 1 个主题，省钱模式）
python eval_runner.py --full       # 回归全部 3 个主题
```

评测通过退出码 0、失败退出码 1，可直接接入 CI。

## 扩展指南

### 加一个新工具

1. 在 `tools.py` 写工具函数（入参 dict、出参 str）
2. 注册进 `TOOL_HANDLERS` 和 `TOOLS`（后者是给 LLM 的参数说明）
3. 在 `pipeline.py` 的 `ROLE_MODULES["researcher"]["tools"]` 里加上工具名

### 加一个新角色

在 `pipeline.py` 的 `ROLE_MODULES` 加一个条目（职责提示词 + 工具清单），再在主流程中调用——核心循环不用改。

### 换模型

改 `config.py` 里的 `MODEL` 和 `BASE_URL`（OpenAI 兼容端点均可，如豆包 `ark.cn-beijing.volces.com/api/v3`）。

## 已知限制

- **搜索依赖 Tavily**：返回质量决定资料上限；没有做网页全文抓取（白名单内 URL 可直接浏览器抓取，尚未接入 pipeline）
- **审查与撰写不共享资料原文**：reviewer 检查事实一致性时凭模型自身知识，理想做法是把资料汇编也传给 reviewer
- **无长期记忆**：每次调研从零开始，调研成果不跨次复用（路线图上的增强项）
- **judge 非绝对可靠**：LLM-as-judge 有漏判率，正式使用建议抽样人工复核
- **DeepSeek 单一模型**：四角色共用同一模型，未做角色级模型路由

## 项目结构

```
research-agent/
├── config.py          # 全局配置（模型/预算/白名单，所有阈值集中于此）
├── tools.py           # 工具层
├── safety.py          # 安全层
├── cost_control.py    # 可靠性层
├── trace_log.py       # 可观测层
├── pipeline.py        # 四角色流水线
├── main.py            # CLI 入口
├── eval_safety.py     # 安全评测
├── eval_report.py     # 报告质量评测
├── eval_runner.py     # Golden 回归
├── outputs/           # 生成的报告（gitignore）
├── traces/            # JSONL 运行日志（gitignore）
└── .env.example       # 配置模板
```
