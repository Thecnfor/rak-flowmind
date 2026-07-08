# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

`rak-flowmind` 是一个**对龙虾(OpenClaw)及任意 Agent 友好**的 Python Skill SDK，通过 MCP 暴露。它是竞赛作品「龙虾×FlowMind」的**技能底座** —— 不实现 OpenClaw 引擎本身，只提供「能被 OpenClaw 优雅调度的技能」的框架契约。

**核心不变量**：**新增一个技能 = 写一个 `@skill` 函数**。注册 / JSON schema / MCP tool / manifest / discover() 自动暴露全自动。加技能**不改动** `server.py` / `contracts.py` / `skill.py` / `rules.py` / `__init__.py` 之外的契约 / 框架层 —— 这条约束改前务必确认。

`README.md` 顶部的 `🤖 FRESH AGENT DEPLOYMENT PROTOCOL` 段是新 Agent 第一次拿到这个 repo 该走的 5 步 startup（自我对话 + 自动部署 + MCP 配置）。**Agent 进来先读那段**，不是读 CLAUDE.md。

## 常用命令

```bash
uv sync --extra dev                                    # 装运行时 + 开发依赖（httpx / requests / pytest / ruff）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -p pytest_asyncio                       # 全量测试（229 个，2026-07 当前）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests/test_inventory_risk.py -v          # 单文件
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests/test_skill.py::test_xxx -v        # 单个测试
uv run ruff check src tests                            # lint（必须通过）
uv run flowmind-mcp                                    # 启动 MCP 服务器（stdio 传输）
uv run flowmind-init                                   # 9 步对话式初始化向导（用户跑）
```

**Python 3.11**（`.python-version`）。**不用 Makefile / Docker / n8n**。ROS 环境下跑 pytest 必须 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`（ROS 插件 `launch_testing_ros_pytest_entrypoint` 与新版 pytest hookspec 不兼容）。

## 架构（大图）

数据流：`Agent/龙虾 → (MCP tool call) server.py → invoke() → skill 函数 → SkillResult → 业务结果 / 错误信封`。

分层（`src/flowmind/`，传输无关核心 + 薄 MCP 层）：

- **`contracts.py`** —— 对外契约层：`SkillResult[T]` 信封 / `ReasoningChain` 四段式链 / `ReliabilityMetrics` / `TraceContext` / `SkillError` / `SkillOutput[T]`。**改这里 = 改对外 API**，必须 bump version 并走 PR。
- **`skill.py`** —— 融合点：`@skill` 装饰器 + `_REGISTRY` + `invoke()`。技能函数只返回轻量 `SkillOutput`；`invoke()` 统一套 `SkillResult` 信封（注入/透传 `trace_id`、填 `latency_ms`、把三类失败兜底成结构化错误）。`SkillSpec` 在注册时**自动捕获** `output_model`（从 `SkillOutput[T]` 返回注解）和 `description`（从函数 docstring 第一段）。
- **`discover.py` + `manifest.py`** —— Agent 自助发现：`discover()` / `field_names()` 把 input + output 完整 JSON Schema 一次暴露，Agent **不再需要读源码**就能拿到 `r.data.foo` 该叫什么。
- **`errors.py`** —— 错误分类（不放在 `contracts.py` 守不变量）：`ErrorCode` enum + `_classify_exception()` + `is_retriable()`。把异常归到 `environment` / `video` / `transient` / `unknown` 四类。
- **`interactive.py`** —— 对话式可交互初始化：`run_interactive_init(ask_fn)` 逐项问用户 9 个偏好；CLI 入口 `flowmind-init`。
- **`config.py`** —— 配置层：`FlowmindConfig` / `InventoryConfig` / `FeishuKbConfig` / `MarketingImageConfig` / `LocalizerConfig`；`load_config` / `save_config` / `get_config` / `reload_config` / `init_for_user`。可调项只经 config 暴露，**带通用默认**；个性化由终端用户对话写 `flowmind.config.toml`（gitignored）。
- **`vl_client.py`** —— 视频本地化后端 HTTP 封装（含请求分类）。
- **`server.py`** —— FastMCP（**v1**，`mcp>=1.27,<2`）遍历注册表动态登记 MCP tool。`_make_tool` 靠设置 `__annotations__` 驱动 schema 推断 —— v1 特定技巧。
- **`skills/`** —— 8 个 `@skill` 注册在 `__init__.py`：3 个纯计算（`inventory_risk` / `feishu_kb_search` / `marketing_image_gen`）+ 5 个 HTTP 依赖的 `localize_*`。每个技能文件第一段 docstring 会被 `SkillSpec.description` 自动捕获。

## 关键约定

- **语言**：注释 / 文档字符串 / 日志 / 提交信息用**中文**；标识符（变量/函数/类）用**英文**。
- **提交格式**：`<type>: <中文描述>`，type ∈ `feat/fix/docs/refactor/test/chore`。
- **错误永不静默**：所有失败经 `SkillResult(ok=False, error=...)` 或 `degraded=True` 返回结构化结果，绝不吞异常、不返回半成品。`invoke()` 是这条铁律的统一执行点。
- **不留代码 TODO 给下游开发者**：可调项全部实现并带通用默认，走 config；定制只发生在终端用户对话初始化。
- **`trace_id` 贯穿**每次调用（透传优先，缺失则 `new_trace()` 生成）。
- **DSI（周转天数）无动销（`sales_30d==0`）时取 `None`**，避免 `Infinity` 破坏 JSON 序列化。
- **TDD**：先写失败测试，再实现；测试优先通过 `invoke("<id>", args)` 做端到端断言。
- **API key 永不进 toml / commit**：视频本地化 `ALLIN_API_KEY`、营销生图 `ALLIN_API_KEY` 都只从环境变量读。代码里只有 `*_key_env: str = "ALLIN_API_KEY"` 这种 env var 名字。
- **错误消息脱敏**：失败路径（`api_message` / `causal_analysis` / `warning`）不放完整异常详情或 `api_base` URL —— Agent 拿到 result 后能据此决策，但不泄漏内部 host / 凭证。

## 失败返回的两种契约（测试必懂）

5 个 `localize_*` 的错误走 **degraded SkillOutput** 模式（**不是** raise）：
```python
r = invoke("localize_batch", {...})
r.ok is True              # ← 不论成功失败
r.metrics.degraded is True
r.data.failure_category   # "environment" / "video" / "transient" / "unknown"
r.data.retriable          # True iff transient
r.error is None
```

`inventory_risk` / `feishu_kb_search` / `marketing_image_gen` 走**普通 raise 模式**：
```python
r.ok is False
r.error.code             # "VALIDATION" / "NOT_FOUND" / "INTERNAL"
r.metrics.degraded is False
r.data.failure_category is None
```

测试断言时**先看 skill 是哪一类**，再选对 expect_ok / expect_degraded / expect_category。

## 测试（两层）

### Layer 1 — 单元（pytest）

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -p pytest_asyncio
```

### Layer 2 — 端到端 Agent 视角（`flowmind-test-skill`）

`.claude/skills/flowmind-test-skill/SKILL.md` 描述完整流程。本质：像真 Agent 一样用 `invoke()` 调 skill，覆盖 happy / boundary / 两种错误契约，输出 JSON + md 报告。**改完代码必跑**。

每个 demo 脚本（`examples/<skill>_demo.py`）第一行都跑 `discover()` —— 这是真实字段名的来源。

## 贡献新技能

1. `src/flowmind/skills/<name>.py` 写一个 `@skill` 函数返回 `SkillOutput`。
2. `src/flowmind/skills/__init__.py` 加一行 `from flowmind.skills import <name>  # noqa: F401`。
3. 可调参数加到 `config.py` 的 `XxxConfig` 类 + 纳入 `FlowmindConfig`。
4. `tests/test_<name>.py` 用 `invoke("<id>", args)` 做端到端断言（不要直接调函数 —— 跳过 envelope 层 = 跳过 trace/latency/error 处理）。
5. `examples/<name>_demo.py` 加 demo（happy / 默认 / 错误三段式）。
6. 跑 Layer 1 + Layer 2 + `ruff check src tests`，全绿才 commit。
7. 提交格式 `<type>: <中文描述>`，type ∈ `feat/fix/docs/refactor/test/chore`。

具体配方 + 反例见 `.claude/skills/flowmind-test-skill/SKILL.md`（必读）和 `flowmind-onboard` skill。

## Agent / 用户工具

- **CLI 向导**：`uv run flowmind-init`（用户跑 9 步问 9 个偏好）
- **Agent 对话式**：`from flowmind.interactive import run_interactive_init; run_interactive_init(ask_fn=my_llm_ask_fn)`
- **Schema 发现**：`from flowmind import discover, field_names`
- **MCP 起服务**：`nohup uv run flowmind-mcp > /tmp/flowmind-mcp.log 2>&1 &`
- **真打 allin-api**（视频本地化 / 营销生图）：`export ALLIN_API_KEY="sk-..."` 后 backend 自动选真；无 key 自动 fallback mock。`examples/marketing_image_gen_real.py` 是真打集成 demo。

## 仓库特有目录

- `.claude/skills/flowmind-onboard/` —— Agent 第一次进 repo 必读
- `.claude/skills/flowmind-test-skill/` —— 端到端测试 skill
- `examples/` —— 8 个 demo 脚本 + 1 个真打集成示例
- `.test-runs/` —— gitignored，端到端测试报告输出位置