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

## 贡献新技能

见 `CONTRIBUTING.md`。要点：`src/flowmind/skills/<name>.py` 写一个 `@skill` 函数返回 `SkillOutput` → 在 `skills/__init__.py` 加一行 `from flowmind.skills import <name>` → `server`/`manifest` 自动发现。可调参数进 `config.py` 的配置模型。

设计文档 `docs/superpowers/specs/`，实现计划 `docs/superpowers/plans/`。
