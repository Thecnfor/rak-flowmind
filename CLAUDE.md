# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

`rak-flowmind` 是一个**对龙虾(OpenClaw)及任意 Agent 友好**的 Python Skill SDK，通过 MCP 暴露。它是竞赛作品「龙虾×FlowMind」的技能底座部分 —— **不实现 OpenClaw 引擎本身**（调度中枢/哨兵/熔断/进化都不在此），只提供「能被 OpenClaw 优雅调度的技能」的框架契约。

核心不变量 —— **新增一个技能 = 写一个 `@skill` 函数**：注册、JSON schema 生成、被 MCP server 暴露、被 manifest 发现全自动，加技能**不改动** `server.py` / `contracts.py` / 初始化骨架。改这条约束前务必确认。

## 常用命令

```bash
uv sync --extra dev                                    # 安装运行时 + 开发依赖
uv run pytest                                          # 全量测试（当前 34 个）
uv run pytest tests/test_inventory_risk.py -v          # 单文件
uv run pytest tests/test_skill.py::test_invoke_wraps_envelope -v  # 单个测试
uv run ruff check src tests                            # lint（必须通过）
uv run flowmind-mcp                                    # 启动 MCP 服务器（stdio 传输）
```

Python 3.11（`.python-version`）。只有 uv 环境，无 Docker/n8n（文档里的这些属「理想部署态」，不在本仓库范围）。

## 架构（大图，需跨文件理解）

数据流：`Agent/龙虾 → (MCP tool call) server.py → invoke() → skill 函数 → SkillResult`。

分层（`src/flowmind/`，传输无关核心 + 薄 MCP 层）：

- **`contracts.py`（契约层，最关键）**：定义「对 Agent 友好」的全部数据类型 —— `SkillResult[T]`（对外统一信封）、`ReasoningChain`（四段式因果推理链）、`ReliabilityMetrics`、`TraceContext`、`SkillError`、以及技能内部产出 `SkillOutput[T]`。改这里等于改对外契约，谨慎。
- **`rules.py`**：声明式 `Rule` + `evaluate_rules()`。四段式链的「触发规则 / 数据证据」两段**由规则求值自动生成，不手写**。
- **`config.py`**：`FlowmindConfig`/`InventoryConfig` + `load_config`/`save_config`/`is_initialized`。阈值等可调项**只经 config 暴露**，带通用默认；个性化由终端用户对话初始化写 `flowmind.config.toml`（gitignored）覆盖。
- **`skill.py`（融合点）**：`@skill` 装饰器 + `_REGISTRY` + `invoke()`。技能函数只返回轻量 `SkillOutput`（业务数据 + 推理链）；`invoke()` 统一套上 `SkillResult` 信封 —— 注入/透传 `trace_id`、计时填 `latency_ms`、并把三类失败兜底为结构化错误（`NOT_FOUND`/`VALIDATION`/`INTERNAL`）。重复 id 严格抛错。用 `typing.get_type_hints()` 推断入参模型，兼容 `from __future__ import annotations`。
- **`skills/inventory_risk.py`**：参考技能（库销比/库存风险），纯确定性、无外部依赖。示范完整套路：算指标 → `evaluate_rules` → 分级 → 组装四段式链 → `SkillOutput`。
- **`manifest.py`**：`build_manifest()` 由注册表生成能力清单（含输入 schema + 可靠性画像），供 Agent 发现。
- **`server.py`**：FastMCP（**v1**，`mcp>=1.27,<2`）遍历注册表，把每个技能动态登记为 MCP tool。`_make_tool` 靠设置 `__annotations__` 驱动 FastMCP 的 schema 推断 —— 这是 v1 特定技巧，由 `<2` pin 兜底。

## 关键约定

- **语言**：注释/文档字符串/日志/提交信息用**中文**；标识符（变量/函数/类）用**英文**。
- **提交格式**：`<type>: <中文描述>`，type ∈ `feat`/`fix`/`docs`/`refactor`/`test`/`chore`。
- **错误永不静默**：所有失败经 `SkillResult(ok=False, error=...)` 或 `degraded=True` 返回结构化结果，绝不吞异常、不返回半成品。`invoke()` 是这条铁律的统一执行点。
- **不留代码 TODO 给下游开发者**：可调项全部实现并带通用默认，走 config；定制只发生在终端用户对话初始化（见 `README.md` 的「Agent 初始化剧本」）。
- **`trace_id` 贯穿**每次调用（透传优先，缺失则 `new_trace()` 生成）。
- **DSI（周转天数）无动销（`sales_30d==0`）时取 `None`**，避免 `Infinity` 破坏 JSON 序列化。
- **TDD**：先写失败测试，再实现；测试优先通过 `invoke("<id>", args)` 做端到端断言（丰富断言在 `invoke` 层，MCP 层测试只验连通）。

## 测试与验证（贡献者必读）

**两层测试，缺一不可。** 改任何技能前，请按以下顺序跑通：

### Layer 1 — 单元测试（pytest）

```bash
uv run pytest tests/test_<skill_id>.py -v
uv run pytest tests/                       # 全量
uv run ruff check src tests                # lint
```

单元测试是契约级保护，必须全绿。

### Layer 2 — 端到端 Agent 视角测试（`flowmind-test-skill`）

**改完代码必须跑这个** —— 它像真 Agent 一样用 `invoke()` 调你的 skill，覆盖：
- happy path（典型真实输入）
- boundary（空 / 极小 / 极大 / None）
- error 路径（**两种契约，按 skill 类型选对**）：
  - **纯计算类**（`inventory_risk` / `feishu_kb_search` / `marketing_image_gen`）—— 失败走 `r.ok=False + r.error.code="VALIDATION"` / `"NOT_FOUND"`
  - **HTTP 依赖类**（5 个 `localize_*`）—— 失败走 `r.ok=True + r.metrics.degraded=True + r.data.failure_category ∈ {environment / video / transient / unknown}`，**不是 `r.ok=False`**

跑法：
```bash
# 自动跑（Claude 通过 flowmind-test-skill 完成）：
#   "测试 inventory_risk"
#   "跑一下 localize_batch"
#   "测全部 8 个 skill"
#
# 或手动参考 examples/<skill>_demo.py + flowmind-test-skill/SKILL.md 写 driver
```

输出 `.test-runs/<skill>-<timestamp>/report.{json,md}` —— **PR 描述里贴通过率数字**。

### 为什么不能只跑 Layer 1

pytest 跑得过不代表 Agent 能用：
- 单元测试可能 mock 了 `requests.post`，但实际集成时 VL 后端返回 5xx 时 skill 没正确分类
- 单元测试断言的是你想到的场景，但 Agent 用法是「看到 `data.failure_category` 就决定下一步」—— 没测过的字段会沉默失败

`flowmind-test-skill` 让 Agent 视角跑你的 skill，强制覆盖「调用 → 拿到 SkillResult → 根据字段决策」全链路。

### 关键工具（不要凭印象写代码）

```python
from flowmind import discover, field_names, invoke

# 拿完整 schema（input + output JSON Schema + description）
info = discover("your_skill_id")

# 拿嵌套字段路径字典（避免 r.data.foo vs r.data.bar 猜错）
for path, names in field_names("your_skill_id").items():
    print(f"{path}: {names}")
```

**写测试 / 写调用代码前先 discover()**——这是「开箱即用」的核心契约。

## 贡献新技能

见 `CONTRIBUTING.md`。要点：`src/flowmind/skills/<name>.py` 写一个 `@skill` 函数返回 `SkillOutput` → 在 `skills/__init__.py` 加一行 `from flowmind.skills import <name>` → `server`/`manifest` 自动发现。可调参数进 `config.py` 的配置模型。

设计文档 `docs/superpowers/specs/`，实现计划 `docs/superpowers/plans/`。

**提交前必跑** `flowmind-test-skill`（见上节）—— 端到端通过率 100% 才合并。
