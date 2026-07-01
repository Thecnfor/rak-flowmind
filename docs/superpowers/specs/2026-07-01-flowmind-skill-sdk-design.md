# FlowMind Skill SDK 设计文档

- 日期：2026-07-01
- 项目：`rak-flowmind`
- 状态：已定稿（待用户复核）
- 关联材料：`FlowMind技术文档.docx`、`【赛道二】纸质材料-统一模板-龙虾×FlowMind.docx`

## 1. 背景与定位

`龙虾×FlowMind` 是「广东财经大学AI能力大赛·赛道二(OpenClaw/龙虾)」的参赛作品，定位为「面向跨境电商的全域感知与自进化智能运营底座」。OpenClaw（龙虾）本身提供调度中枢、哨兵感知、四专家、风险熔断、自评测等引擎能力。

**本项目 `rak-flowmind` 不重复实现龙虾引擎**，而是构建一个「**对龙虾（及任何 Agent）友好的 Skill SDK**」：

> 让技能作者只写业务逻辑，就能产出**自带四段式因果推理链、可靠性指标、trace_id、并原生以 MCP 工具形态暴露**的高质量技能；从而「打包扔给任何会说 MCP 的 Agent，即可高质量完成任务」。

核心约束：**只有 uv/Python 环境**。文档中的 n8n、Docker、ComfyUI、LangGraph 等属于「理想部署态」，不在本基座范围内；基座是纯 Python 的技能 SDK。

## 2. 目标与非目标

### 2.1 目标（本次「打基座」范围）

1. **契约层**：定义「对龙虾友好」的统一数据契约（`SkillResult` / `ReasoningChain` / `ReliabilityMetrics` / `TraceContext` / `SkillError`）。这是基座价值的核心。
2. **技能框架**：`@skill` 装饰器 + 注册表，使「定义一个技能 = 得到契约化返回 + 一个 MCP 工具」（skills 融合 mcp）。
3. **规则引擎**：声明式规则求值，自动产出四段式推理链中的「触发规则」与「数据证据」。从参考技能中提炼，不提前抽象。
4. **能力清单**：由注册表生成机器可读的技能清单（含可靠性画像），供龙虾/Agent 发现与挂载。
5. **MCP Server**：遍历注册表，将每个技能暴露为 MCP tool（pydantic 返回 → 自动 structured output）。
6. **参考技能**：`inventory_risk`（库销比/库存风险分析），纯确定性、无外部依赖，验证整条链路。
7. **配置与 Agent 引导初始化**：技能内置通用默认值开箱即用；配置层支持「用户自己的默认」覆盖；`README.md` 作为 Agent 初始化剧本，引导用户通过对话生成专属配置。
8. **测试**：契约 / 规则 / 配置 / 技能 / MCP 五组测试，TDD 驱动。

### 2.2 非目标（本次明确不做）

- 不实现龙虾引擎的调度中枢、哨兵、专家编组、熔断执行、自进化沙盒。
- 不做 demo / 演示脚本。
- 不接入真实外部数据源（Amazon/TikTok API、爬虫、OCR）。
- 不接入 LLM：参考技能为确定性计算，四段式推理链由规则求值确定性生成（龙虾自身的 LLM 负责生成性表达）。
- 不做前端、飞书交互、部署编排。

## 3. 架构

### 3.1 分层理念

- **Skill 是唯一主角**：契约描述技能进出、规则驱动技能推理、清单编录技能、server 端出技能。
- **skills 融合 mcp**：MCP 不是独立的上层或可选适配器，而是技能的天然表达形态。一次 `@skill` 定义同时完成：注册进 registry、声明 pydantic 入/出参、成为一个 MCP tool。
- **契约稳、框架活**：契约层一开始就钉死（它是友好度规格书）；框架/规则引擎从唯一的真实技能里长出来，只提炼已出现的模式（YAGNI）。

### 3.2 包结构（`src/` 布局）

```
rak-flowmind/
  pyproject.toml          # 依赖: mcp, pydantic  | dev: pytest, pytest-asyncio, ruff
  README.md               # 双重身份: 人类文档 + Agent 初始化剧本(见 §8)
  src/flowmind/
    __init__.py
    contracts.py          # 契约层: SkillResult / ReasoningChain / ReliabilityMetrics / TraceContext / SkillError
    config.py             # 配置层: 各技能配置模型 + 通用默认 + load/save + 初始化状态
    rules.py              # 声明式规则引擎 → 自动填 触发规则+数据证据 (阈值来自 config)
    skill.py              # Skill 抽象 + @skill 装饰器 + 注册表 (融合点)
    manifest.py           # 由注册表生成能力清单(JSON)
    server.py             # MCP Server: 遍历注册表, 每个 skill 即一个 MCP tool
    skills/
      __init__.py
      inventory_risk.py   # 参考技能: 库销比/库存风险
  tests/
    test_contracts.py
    test_rules.py
    test_config.py
    test_inventory_risk.py
    test_server_mcp.py
```

- 入口点：`flowmind-mcp = "flowmind.server:main"`（启动 MCP Server，默认 stdio 传输）。
- 根目录占位 `main.py` 将被移除/替换。
- 依赖 `mcp` 与 `pydantic` 均为核心依赖（不设 optional）。

## 4. 契约层（`contracts.py`）

全部使用 pydantic v2，自动获得 JSON Schema。

### 4.1 `ReasoningChain` —— 四段式因果推理链

严格对齐文档能力③：`【决策结论】→【触发规则】→【数据证据】→【因果推理与风险提示】`。

```python
class RuleHit(BaseModel):            # 触发规则
    rule_id: str                     # 如 "INV-P03"
    name: str                        # 如 "滞销资金占用过高"
    expression: str                  # 如 "周转天数>90 且 库销比>3"
    hit: bool

class Evidence(BaseModel):           # 数据证据
    metric: str                      # 如 "周转天数(DSI)"
    value: float | str
    threshold: float | str | None = None
    comparison: str                  # 如 ">"、"命中区间"
    window: str | None = None        # 如 "近30天"

class ReasoningChain(BaseModel):
    conclusion: str                  # 决策结论
    triggered_rules: list[RuleHit]   # 触发规则
    evidence: list[Evidence]         # 数据证据
    causal_analysis: str             # 因果推理
    risk_note: str                   # 风险提示
    confidence: float = 1.0
```

### 4.2 `ReliabilityMetrics` —— 可靠性指标（喂给龙虾熔断/评测，能力④⑤）

```python
class ReliabilityMetrics(BaseModel):
    latency_ms: float
    confidence: float
    sample_size: int                 # 处理记录数
    degraded: bool = False           # 是否降级运行
    degradation_reason: str | None = None
```

### 4.3 `TraceContext` —— trace_id 全链路贯穿

```python
class TraceContext(BaseModel):
    trace_id: str
    source: str = "openclaw"
    target: str = "flowmind"
    timestamp: str                   # ISO8601
```

### 4.4 `SkillResult[T]` 与 `SkillError` —— 统一返回信封（错误永不静默）

```python
class SkillError(BaseModel):
    code: str                        # 如 "VALIDATION" / "INTERNAL"
    message: str
    retriable: bool = False
    details: dict | None = None

class SkillResult(BaseModel, Generic[T]):
    ok: bool
    skill: str
    version: str
    trace: TraceContext
    data: T | None = None            # 业务载荷 (每技能不同)
    reasoning: list[ReasoningChain] = []
    metrics: ReliabilityMetrics
    error: SkillError | None = None
```

设计要点：
- 泛型 `T` 承载各技能不同的业务载荷；信封（推理链/指标/trace/error）全平台统一。
- `degraded` 字段呼应 CLAUDE.md「自动降级」铁律：外部依赖缺失不崩溃，返回 `degraded=True` + 原因。
- 四段式链**不手写**：由规则引擎求值 `RuleHit`/`Evidence` 自动填充，技能作者只补 `causal_analysis` / `risk_note`。

## 5. 技能框架与融合点（`skill.py`）

```python
@skill(id="inventory_risk", name="库销比/库存风险分析", version="0.1.0")
def inventory_risk(inp: InventoryInput) -> SkillResult[InventoryReport]:
    ...
```

`@skill` 装饰器职责（融合点）：
1. **注册**：将技能登记进全局 `registry`（供 `manifest.py` 发现）。
2. **schema**：由函数签名的 pydantic 入参与 `SkillResult[...]` 返回类型，提供输入/输出 schema。
3. **MCP 工具化**：`server.py` 遍历注册表时，把每个技能通过 MCP SDK 的 `@mcp.tool()` 暴露为工具（pydantic 返回 → SDK 自动生成 output schema 与 structured content）。
4. **横切统一**：在调用边界统一注入 `TraceContext`（透传或生成 trace_id、打时间戳）、计时填充 `latency_ms`、异常兜底为 `SkillError`。

技能作者视角只有 skill；MCP、schema、清单登记、trace/计时全自动发生 —— 这是「skills 融合 mcp」的落地。

> MCP SDK API（如 `FastMCP`/`MCPServer` 的确切导入路径与 `mcp.run()` 传输参数）在实现阶段以当前版本文档为准最终敲定；本设计已确认「pydantic 返回类型 → 自动 structured output」这一关键能力成立。

## 6. 规则引擎（`rules.py`）

声明式规则，从参考技能的需要中长出来：

```python
class Rule:
    id: str
    name: str
    expression: str                  # 人类可读表达式(写进 RuleHit)
    predicate: Callable[[Metrics], bool]
    evidence: Callable[[Metrics], list[Evidence]]
```

- 对每条记录的计算指标 `Metrics` 求值所有规则 → 命中的 `RuleHit` + 关联 `Evidence` → 组装 `ReasoningChain`。
- 阈值可配置，提供跨境电商默认值。
- 该引擎只服务当前一个技能；当第二个技能出现且复用同一模式时，再固化抽象。

## 7. 参考技能：`inventory_risk`（`skills/inventory_risk.py`）

### 7.1 输入 `InventoryInput`

SKU 记录列表，每条：
- `sku: str`
- `on_hand: int`（在库数量）
- `in_transit: int = 0`（在途数量）
- `unit_cost: float`（单位成本）
- `sales_30d: int`（近30天销量）
- 可选：`price: float | None`、`category: str | None`

### 7.2 计算指标

- 周转天数 `DSI = on_hand / (sales_30d / 30)`（`sales_30d == 0` 视为无穷/滞销）
- 库销比 `= on_hand / sales_30d`（月度口径）
- 资金占用 `= on_hand * unit_cost`
- 滞销判定 `= (sales_30d == 0 and on_hand > 0)`

### 7.3 规则与风险分级

风险级别：`健康 / 关注 / 预警 / 危险`。规则（阈值来自 `config.py`，用户配置 > 通用默认，见 §8）：
- `INV-P01 滞销积压`：`sales_30d==0 且 on_hand>0` → 危险
- `INV-P02 周转过慢`：`DSI > 危险阈值`
- `INV-P03 慢周转+资金占用高`：`DSI > 预警阈值 且 资金占用 > 金额阈值`
- `INV-P04 断货风险`：`DSI < 低阈值`（卖太快、需补货）

> **实现方针**：规则谓词、`Metrics` 计算、`ReasoningChain` 组装、通用默认阈值**全部由本项目实现完成，不留任何代码 TODO 给开发者**。所有阈值/规则参数经 `config.py` 暴露为可配置项；**个性化定制只发生在终端用户的对话式初始化**（见 §8）——由消费此包的 Agent 引导用户设定，写入 `flowmind.config.toml`，覆盖通用默认。开发者与实现者都不手写「适合某个人」的业务默认值。

### 7.4 输出 `InventoryReport`（作为 `SkillResult.data`）

- 每 SKU：指标 + 风险级别 + 命中规则
- 汇总：总资金占用、滞销占用金额、各级别 SKU 数量、Top 风险 SKU 列表
- `reasoning`：对每个被标记 SKU 生成的四段式链
- `metrics`：`latency_ms` / `sample_size=len(records)` / `confidence`

## 8. 配置与 Agent 引导初始化（Config & Agent-guided Init）

设计目标：技能开箱即用（内置通用默认），但可被「用户自己的默认」覆盖；用户配置由消费此包的 Agent 通过对话引导生成。这让「打包扔给任何 Agent」形成闭环——装好即可被引导个性化。

### 8.1 配置解析优先级

`flowmind.config.toml`（用户配置）**>** 技能内置通用默认值。阈值**不硬编码在规则内**，规则从 `config.py` 解析。用户配置文件不入库（见 `.gitignore`）。

### 8.2 `config.py`

- 每技能一个 pydantic 配置模型（如 `InventoryConfig`，含各阈值字段并给出通用默认值）。
- `load_config()`：读取 `flowmind.config.toml`（不存在则全用默认），与默认合并，返回类型化配置。
- `save_config()` / `write_skill_config()`：供初始化对话把用户设定写回文件。
- `is_initialized()`：判断用户是否已完成初始化（配置文件是否存在/是否含用户段）。

### 8.3 README.md 作为 Agent 初始化剧本

项目根 `README.md` 含明确面向「消费此包的 Agent」的一节：

- 首次使用时先检查 `is_initialized()`；
- 若未初始化，引导用户完成对话式初始化：逐项询问业务画像（经营类目、资金规模、期望周转天数、滞销容忍度等），据答案调用 `save_config()` 写出 `flowmind.config.toml`；
- 列出可用技能及其含义（与 `manifest.py` 输出保持一致）。

README 同时是人类可读文档。

### 8.4 与技能的关系

- 技能 `run()` 内经 `load_config()` 取阈值；未初始化时用通用默认，仍可正常返回结果（如需可用 `degraded` 标注「未个性化配置」）。
- 新增技能只需定义自己的配置模型 + 默认值，即自动纳入同一套初始化流程，无需改动初始化剧本骨架。

## 9. 调用数据流

```
Agent/龙虾 → (MCP tool call) → server.py
  → 注册表定位技能
  → pydantic 校验入参
  → 注入/透传 TraceContext(trace_id、timestamp)、起计时
  → skill.run(): 计算 Metrics → rules 求值 → 组装 ReasoningChain
  → 组装 SkillResult(data + reasoning + metrics + trace)
  → 计时填入 metrics.latency_ms
  → 作为 structured content 返回
```

- trace_id：调用方提供则透传，否则生成。
- 非 MCP 直接调用路径（供测试与非 MCP 场景）：技能函数本身即可直接调用并返回 `SkillResult`。

## 10. 错误处理

呼应 CLAUDE.md「自动降级、永不静默」铁律与 silent-failure 防范：
- 入参非法 → `SkillResult(ok=False, error=SkillError(code="VALIDATION"))`，不吞异常、不返回半成品。
- 技能内部异常 → 在调用边界兜住 → `SkillResult(ok=False, error=SkillError(code="INTERNAL", retriable=...))`。
- 外部/可选依赖缺失 → `ok=True, degraded=True, degradation_reason=...`，返回可用的部分结果。
- 任何情况都返回结构化 `SkillResult`，龙虾据 `ok`/`error`/`degraded` 决定信任与熔断。

## 11. 测试策略（TDD）

- `test_contracts.py`：`SkillResult`/`ReasoningChain` 序列化为 JSON、schema 生成正确、泛型载荷可用。
- `test_rules.py`：给定 `Metrics`，规则命中与 `Evidence` 产出正确。
- `test_inventory_risk.py`：已知数据集 → 已知分级与汇总；四段式链四要素齐全；边界（0 销量、空输入、负数 → 结构化 VALIDATION 错误）。
- `test_config.py`：无配置文件时回落通用默认；有 `flowmind.config.toml` 时用户值覆盖默认；`save_config`→`load_config` 往返一致；`is_initialized` 判定正确。
- `test_server_mcp.py`：MCP 内存客户端 `list_tools` 能发现技能、`call_tool` 返回良构 structured content。
- 全程红-绿-重构；确定性技能使测试稳定、无外部依赖。

## 12. 依赖与工具链

- 运行时：`mcp`、`pydantic`（v2）
- 开发：`pytest`、`pytest-asyncio`、`ruff`
- 环境：`uv`（Python 3.11，锁定于 `.python-version`）
- 代码规范：注释/文档/日志用中文，标识符用英文（遵循 CLAUDE.md）。

## 13. 验收标准

1. `uv run pytest` 全绿。
2. `uv run flowmind-mcp` 可启动 MCP Server（stdio）。
3. MCP 客户端可发现 `inventory_risk` 工具并调用，返回包含四段式 `reasoning`、`metrics`、`trace` 的 `SkillResult`。
4. `manifest.py` 可输出含 `inventory_risk` 的能力清单（含可靠性画像）。
5. 无用户配置时技能用通用默认正常运行；写入 `flowmind.config.toml` 后阈值被用户值覆盖；`README.md` 含可被 Agent 执行的初始化剧本。
6. 新增一个技能仅需写一个 `@skill` 函数 + 其规则 + 其配置模型，无需改动 server/契约层/初始化骨架。
