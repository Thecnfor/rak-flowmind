# FlowMind Skill SDK

对龙虾(OpenClaw)及任意 Agent 友好的技能底座。技能一次定义即成为 MCP 工具，
自带四段式因果推理链、可靠性指标与 trace_id，并可由终端用户对话初始化个性化配置。

---

## 🤖 如果你是一个 AI Agent 第一次读到这个文件 —— STOP

**你是被用户部署到本项目的 Agent（Claude Code / Cursor / Cline / OpenClaw / 任何 MCP 客户端）。**

不要立刻跑 `uv run` / `make install` / 写代码。本节是**给你看的部署协议**，按下面的顺序与用户对话，再执行。

### 协议第 0 步：用一句话自我介绍并告诉用户你要做什么

> "Hi，我是 [agent name]。我刚拿到了 FlowMind Skill SDK —— 这是个对 Agent 友好的 Python 技能框架。在动手部署前，我需要先和你过几个问题，确认你的环境 + 用法偏好，然后我会自动跑通。准备好了吗？"

### 协议第 1 步：通过对话采集 4 件事

每次问一件事，按用户回答接着问下一件。不要一次塞所有问题。

| # | 必问 | 选项 / 示例 | 用途 |
|---|---|---|---|
| 1 | **你打算用哪个 Agent 平台跑？** | Claude Desktop / Cursor / Cline / OpenClaw / 自建 Python | 决定要不要配 MCP |
| 2 | **目标部署语言 / 项目类型？** | 视频本地化（v0.3）/ 库存分析 / FAQ 检索 / 营销生图 | 决定要不要 init config |
| 3 | **要不要现在跑 `flowmind-init` 配视频本地化偏好？**（仅当 #2 选了视频本地化） | y / n（y 推荐） | 写 `flowmind.config.toml` |
| 4 | **要不要装 MCP 服务器？（Claude Desktop 等 GUI 客户端必装）** | y / n（推荐 y） | 走 `flowmind-mcp-setup` |

**实现方式**：用 `flowmind.interactive.run_interactive_init(ask_fn=...)` 让 SDK 自己逐项提问给用户，你只需要提供 ask_fn（CLI 用内置 input()，你驱动对话时传自己的 callable）。

```python
# Agent 驱动对话的标准模式
from flowmind.interactive import run_interactive_init
cfg = run_interactive_init(ask_fn=my_chat_ask_fn)
# → 9 个问题逐个问（目标语言 / 源语言 / TTS / 字号 / 位置 / 文件后缀）
# → 用户每题直接按 Enter 用默认也行
# → 自动写 TOML + reload
```

### 协议第 2 步：按答案执行

```
if #1 in (Claude Desktop, Cursor, Cline, OpenClaw):
    # 走 MCP 接入：触发 flowmind-mcp-setup skill 或读 docs/agent-integration.md
    # 给用户具体的 MCP 配置 JSON 片段 + 配到客户端的命令

if #2 == "视频本地化" and #3 == "y":
    # 已经在协议第 1 步通过 interactive 跑过 init_for_user 了
    # 验证：cat flowmind.config.toml

if #4 == "y":
    # MCP server 启动：uv run flowmind-mcp（stdio）
    # 给用户 stdio 配置 JSON（含 command + args）
```

### 协议第 3 步：部署验证（必做，别跳过）

```bash
# 1. 装依赖
uv sync --extra dev

# 2. 跑 8 个技能的冒烟测试（必须全绿）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -p pytest_asyncio

# 3. 端到端 Agent 视角测试
# 触发 flowmind-test-skill，或者直接跑：
for f in examples/*_demo.py; do PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python "$f"; done

# 4. 发现能力（schema 驱动断言，避免猜字段）
uv run python -c "
from flowmind import discover
for s in discover():
    print(s['id'], '-', s['description'])
"
```

把每步的输出摘要反馈给用户。**所有 8 个技能都跑通 + 配置文件存在 + 至少 1 个 demo 跑通 = 部署成功**。

### 协议第 4 步：交付给用户

> "部署完成。你现在可以：
> - **用 MCP**：在你 [Claude Desktop / Cursor / Cline] 里应该看到 8 个工具（`inventory_risk` / `feishu_kb_search` / `marketing_image_gen` / 5 个 `localize_*`）
> - **直接 Python**：`from flowmind import invoke, discover` 就能用
> - **继续开发**：触发 `flowmind-add-skill` 加新技能；触发 `flowmind-handle-pr` 处理 PR
>
> 任何问题直接问我，我会读 CLAUDE.md / AGENTS.md 找答案。"

---

## 人类用户视角（人类读 README，不是 Agent）

如果你**不是** Agent 在读这段，跳过上面 🤖 段。往下看：

## 安装

```bash
uv sync --extra dev
```

## 作为 MCP 服务器运行

```bash
uv run flowmind-mcp   # stdio 传输
```

## 直接调用（非 MCP）

```python
import flowmind.skills  # 触发技能注册
from flowmind.skill import invoke

result = invoke("inventory_risk", {"items": [
    {"sku": "A", "on_hand": 100, "unit_cost": 2.0, "sales_30d": 60},
]})
print(result.ok, result.data.summary, result.reasoning)
```

## 可用技能

- `inventory_risk` —— 库销比/库存风险分析。输入 SKU 列表，输出风险分级、
  资金占用汇总与四段式推理链。完整清单见 `python -c "import flowmind.skills, json; from flowmind.manifest import build_manifest; print(json.dumps(build_manifest(), ensure_ascii=False, indent=2))"`。
- `feishu_kb_search` —— 飞书 FAQ 检索
- `marketing_image_gen` —— 营销生图（多平台/多风格）
- `localize_batch` / `localize_status` / `localize_cancel` / `localize_download` / `localize_retry` —— 视频本地化 5 步编排

## 给 Agent 的初始化剧本（AGENT INIT PLAYBOOK）

> 本节面向**装载此包的 Agent**。首次为某用户使用本 SDK 前，请执行以下步骤，
> 通过对话把技能阈值调整为「用户自己的默认」。不要让开发者改代码——
> 一切定制都写入 `flowmind.config.toml`。

**步骤 1：检查是否已初始化**

```python
from flowmind.config import is_initialized
if not is_initialized():
    ...  # 执行步骤 2、3
```

**步骤 2：与用户对话采集业务画像**

依次询问（用户不答则用括号内通用默认）：
- 经营类目与结算货币？（`currency="USD"`）
- 期望的健康周转天数上限？（`dsi_healthy_max=60`）
- 关注/预警的周转天数分界？（`dsi_watch_max=90`、`dsi_warn_max=120`）
- 视为「断货风险」的低周转天数？（`dsi_low=15`）
- 单 SKU「资金占用过高」的金额阈值？（`capital_high=100000`）

**步骤 3：写入用户专属配置**

```python
from flowmind.config import FlowmindConfig, InventoryConfig, save_config
save_config(FlowmindConfig(inventory=InventoryConfig(
    currency="CNY",          # ← 用步骤 2 采集到的值替换
    dsi_healthy_max=45,
    dsi_watch_max=75,
    dsi_warn_max=100,
    dsi_low=10,
    capital_high=80000,
)))
```

此后所有技能调用将自动采用用户设定的阈值（`flowmind.config.toml`），
未设定项回落通用默认。用户可随时要求重新初始化以调整。

**或者用对话式向导（推荐）**：

```bash
uv run flowmind-init      # CLI 9 步向导
```

或 Agent 调：

```python
from flowmind.interactive import run_interactive_init
cfg = run_interactive_init(ask_fn=my_llm_ask)  # Agent 驱动对话
```