# FlowMind Skill SDK

对龙虾(OpenClaw)及任意 Agent 友好的技能底座。技能一次定义即成为 MCP 工具，
自带四段式因果推理链、可靠性指标与 trace_id，并可由终端用户对话初始化个性化配置。

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

---

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