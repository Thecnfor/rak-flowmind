# FlowMind Skill SDK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个「对龙虾(OpenClaw)及任意 Agent 友好」的 Python Skill SDK：技能一次定义即成为 MCP 工具、自带四段式因果推理链/可靠性指标/trace_id，并可由终端用户通过对话初始化个性化配置。

**Architecture:** 纯 Python + pydantic 的传输无关核心（契约层 `contracts` → 规则引擎 `rules` → 配置层 `config` → 技能框架 `skill`(注册表+`@skill`+`invoke`) → 参考技能 `inventory_risk`），外加薄 MCP 暴露层 `server`（FastMCP 遍历注册表）与自描述 `manifest`。技能返回轻量 `SkillOutput`，框架 `invoke()` 统一套上对外 `SkillResult` 信封。

**Tech Stack:** Python 3.11、pydantic v2、`mcp>=1.27,<2`(FastMCP)、`tomli-w`(写 TOML)、pytest + pytest-asyncio、ruff、uv。

## Global Constraints

- Python 版本下限：`requires-python = ">=3.11"`（`.python-version` = 3.11）。
- 依赖固定：`mcp>=1.27,<2`、`pydantic>=2`、`tomli-w>=1.0`；dev：`pytest>=8`、`pytest-asyncio>=0.23`、`ruff>=0.6`。
- 代码规范：注释/文档字符串/日志用**中文**，标识符（变量/函数/类）用**英文**（遵循 CLAUDE.md）。
- `trace_id` 必须贯穿每次调用（透传优先，缺失则生成）。
- 错误**永不静默**：任何失败都返回结构化 `SkillResult(ok=False, error=...)` 或 `degraded=True`，绝不吞异常、不返回半成品。
- **不留任何代码 TODO 给开发者**：所有规则谓词与通用默认阈值本计划全部写完；「可自定义」只经 `config` + 终端用户对话初始化暴露。
- 提交规范：`<type>: <中文描述>`，type ∈ feat/fix/docs/refactor/test/chore。
- 每个技能返回 `SkillOutput`；对外统一信封 `SkillResult` 只由 `invoke()` 组装。
- `DSI`（周转天数）在无动销（`sales_30d==0`）时为 `None`，避免 `Infinity` 破坏 JSON 序列化。

---

## File Structure

- `pyproject.toml` — 包元数据、依赖、入口点 `flowmind-mcp`、pytest 配置。
- `src/flowmind/__init__.py` — 包标识（空）。
- `src/flowmind/contracts.py` — 契约：`RuleHit`/`Evidence`/`ReasoningChain`/`ReliabilityMetrics`/`TraceContext`/`SkillError`/`SkillResult[T]`/`SkillOutput[T]` + `new_trace()`。
- `src/flowmind/rules.py` — `Rule` 数据类 + `evaluate_rules()`（声明式规则求值 → `RuleHit`+`Evidence`）。
- `src/flowmind/config.py` — `InventoryConfig`/`FlowmindConfig` + `load_config`/`save_config`/`is_initialized`。
- `src/flowmind/skill.py` — `SkillSpec`、`_REGISTRY`、`skill()` 装饰器、`registry()`、`invoke()`。
- `src/flowmind/skills/__init__.py` — 导入各技能触发注册（`from . import inventory_risk`）。
- `src/flowmind/skills/inventory_risk.py` — 参考技能：库销比/库存风险。
- `src/flowmind/manifest.py` — `build_manifest()` 由注册表生成能力清单。
- `src/flowmind/server.py` — FastMCP 服务器：遍历注册表登记工具；`main()` 入口。
- `README.md` — 人类文档 + Agent 初始化剧本。
- `tests/test_contracts.py`、`tests/test_rules.py`、`tests/test_config.py`、`tests/test_inventory_risk.py`、`tests/test_manifest.py`、`tests/test_server_mcp.py`。

---

## Task 1: 项目脚手架与工具链

**Files:**
- Create: `pyproject.toml`（覆盖现有占位）
- Create: `src/flowmind/__init__.py`
- Create: `tests/__init__.py`, `tests/test_smoke.py`
- Delete: `main.py`（根目录占位）

**Interfaces:**
- Produces: 可安装的包 `flowmind`；`uv run pytest` 可执行。

- [ ] **Step 1: 写 `pyproject.toml`**

```toml
[project]
name = "rak-flowmind"
version = "0.1.0"
description = "FlowMind Skill SDK —— 对龙虾(OpenClaw)友好的技能底座"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.27,<2",
    "pydantic>=2",
    "tomli-w>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "ruff>=0.6",
]

[project.scripts]
flowmind-mcp = "flowmind.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/flowmind"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 2: 建包骨架**

创建空文件 `src/flowmind/__init__.py`（内容：`"""FlowMind Skill SDK 包。"""`）与 `tests/__init__.py`（空）。删除根目录 `main.py`。

- [ ] **Step 3: 写冒烟测试** `tests/test_smoke.py`

```python
"""冒烟测试：确认包可导入。"""

def test_import_package():
    import flowmind
    assert flowmind is not None
```

- [ ] **Step 4: 同步依赖并运行**

Run: `uv sync --extra dev && uv run pytest tests/test_smoke.py -v`
Expected: 依赖安装成功；`test_import_package` PASS。

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml src/flowmind/__init__.py tests/__init__.py tests/test_smoke.py
git rm main.py
git commit -m "chore: 初始化 flowmind 包骨架与工具链"
```

---

## Task 2: 契约层 `contracts.py`

**Files:**
- Create: `src/flowmind/contracts.py`
- Test: `tests/test_contracts.py`

**Interfaces:**
- Produces:
  - `RuleHit(rule_id:str, name:str, expression:str, hit:bool)`
  - `Evidence(metric:str, value:float|str, threshold:float|str|None=None, comparison:str, window:str|None=None)`
  - `ReasoningChain(conclusion:str, triggered_rules:list[RuleHit], evidence:list[Evidence], causal_analysis:str, risk_note:str, confidence:float=1.0)`
  - `ReliabilityMetrics(latency_ms:float, confidence:float, sample_size:int, degraded:bool=False, degradation_reason:str|None=None)`
  - `TraceContext(trace_id:str, source:str="openclaw", target:str="flowmind", timestamp:str)`
  - `SkillError(code:str, message:str, retriable:bool=False, details:dict|None=None)`
  - `SkillOutput[T](data:T, reasoning:list[ReasoningChain]=[], confidence:float=1.0, sample_size:int=0, degraded:bool=False, degradation_reason:str|None=None)`
  - `SkillResult[T](ok:bool, skill:str, version:str, trace:TraceContext, data:T|None=None, reasoning:list[ReasoningChain]=[], metrics:ReliabilityMetrics, error:SkillError|None=None)`
  - `new_trace(source:str="openclaw", target:str="flowmind", trace_id:str|None=None) -> TraceContext`

- [ ] **Step 1: 写失败测试** `tests/test_contracts.py`

```python
"""契约层测试：序列化、JSON Schema、泛型载荷、trace 工厂。"""
import json
from pydantic import BaseModel
from flowmind.contracts import (
    RuleHit, Evidence, ReasoningChain, ReliabilityMetrics,
    TraceContext, SkillError, SkillOutput, SkillResult, new_trace,
)


class _Payload(BaseModel):
    value: int


def test_new_trace_generates_id_and_timestamp():
    tr = new_trace()
    assert tr.trace_id
    assert tr.source == "openclaw" and tr.target == "flowmind"
    assert "T" in tr.timestamp  # ISO8601

def test_new_trace_passthrough_id():
    tr = new_trace(trace_id="abc-123")
    assert tr.trace_id == "abc-123"

def test_reasoning_chain_four_parts():
    chain = ReasoningChain(
        conclusion="结论",
        triggered_rules=[RuleHit(rule_id="R1", name="规则", expression="x>1", hit=True)],
        evidence=[Evidence(metric="x", value=2, threshold=1, comparison=">")],
        causal_analysis="因为 x>1",
        risk_note="注意波动",
    )
    assert chain.confidence == 1.0
    assert chain.triggered_rules[0].hit is True

def test_skill_result_json_roundtrip_with_generic_payload():
    result = SkillResult[_Payload](
        ok=True, skill="demo", version="0.1.0", trace=new_trace(),
        data=_Payload(value=7),
        reasoning=[],
        metrics=ReliabilityMetrics(latency_ms=1.2, confidence=1.0, sample_size=1),
    )
    dumped = result.model_dump_json()
    parsed = json.loads(dumped)
    assert parsed["ok"] is True
    assert parsed["data"]["value"] == 7
    assert parsed["metrics"]["sample_size"] == 1

def test_skill_result_error_shape():
    result = SkillResult(
        ok=False, skill="demo", version="0.1.0", trace=new_trace(),
        metrics=ReliabilityMetrics(latency_ms=0.0, confidence=0.0, sample_size=0),
        error=SkillError(code="VALIDATION", message="坏参数"),
    )
    assert result.ok is False
    assert result.error.code == "VALIDATION"

def test_output_schema_generatable():
    schema = SkillResult[_Payload].model_json_schema()
    assert schema["type"] == "object"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_contracts.py -v`
Expected: FAIL（`ModuleNotFoundError: flowmind.contracts`）。

- [ ] **Step 3: 实现 `src/flowmind/contracts.py`**

```python
"""契约层：定义「对龙虾友好」的统一数据结构。

这是整个 SDK 的规格核心——任何返回 SkillResult 的技能天然对龙虾友好。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class RuleHit(BaseModel):
    """触发规则：四段式推理链的第二段。"""
    rule_id: str
    name: str
    expression: str  # 人类可读的规则表达式
    hit: bool


class Evidence(BaseModel):
    """数据证据：四段式推理链的第三段。"""
    metric: str
    value: float | str
    threshold: float | str | None = None
    comparison: str  # 如 ">"、"=="、"命中区间"
    window: str | None = None  # 如 "近30天"


class ReasoningChain(BaseModel):
    """四段式因果推理链：决策结论 → 触发规则 → 数据证据 → 因果推理与风险提示。"""
    conclusion: str          # 决策结论
    triggered_rules: list[RuleHit] = Field(default_factory=list)  # 触发规则
    evidence: list[Evidence] = Field(default_factory=list)        # 数据证据
    causal_analysis: str     # 因果推理
    risk_note: str           # 风险提示
    confidence: float = 1.0


class ReliabilityMetrics(BaseModel):
    """可靠性指标：供龙虾熔断/评测模块读取。"""
    latency_ms: float
    confidence: float
    sample_size: int
    degraded: bool = False
    degradation_reason: str | None = None


class TraceContext(BaseModel):
    """全链路追踪上下文：trace_id 贯穿每次调用。"""
    trace_id: str
    source: str = "openclaw"
    target: str = "flowmind"
    timestamp: str  # ISO8601


class SkillError(BaseModel):
    """结构化错误：错误永不静默。"""
    code: str  # 如 "VALIDATION" / "INTERNAL" / "NOT_FOUND"
    message: str
    retriable: bool = False
    details: dict | None = None


class SkillOutput(BaseModel, Generic[T]):
    """技能内部产出：业务数据 + 推理链。由框架套上 SkillResult 信封。"""
    data: T
    reasoning: list[ReasoningChain] = Field(default_factory=list)
    confidence: float = 1.0
    sample_size: int = 0
    degraded: bool = False
    degradation_reason: str | None = None


class SkillResult(BaseModel, Generic[T]):
    """对外统一返回信封：龙虾/Agent 消费此结构。"""
    ok: bool
    skill: str
    version: str
    trace: TraceContext
    data: T | None = None
    reasoning: list[ReasoningChain] = Field(default_factory=list)
    metrics: ReliabilityMetrics
    error: SkillError | None = None


def new_trace(
    source: str = "openclaw",
    target: str = "flowmind",
    trace_id: str | None = None,
) -> TraceContext:
    """创建追踪上下文：调用方给了 trace_id 就透传，否则生成。"""
    return TraceContext(
        trace_id=trace_id or str(uuid.uuid4()),
        source=source,
        target=target,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_contracts.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add src/flowmind/contracts.py tests/test_contracts.py
git commit -m "feat: 契约层 contracts（四段式推理链/可靠性指标/SkillResult 信封）"
```

---

## Task 3: 规则引擎 `rules.py`

**Files:**
- Create: `src/flowmind/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: `RuleHit`, `Evidence`（Task 2）。
- Produces:
  - `Rule(id:str, name:str, expression:str, predicate:Callable[[dict],bool], evidence:Callable[[dict],list[Evidence]])`（dataclass）
  - `evaluate_rules(rules:list[Rule], metrics:dict) -> tuple[list[RuleHit], list[Evidence]]`（只收集命中的规则及其证据）

- [ ] **Step 1: 写失败测试** `tests/test_rules.py`

```python
"""规则引擎测试：命中规则与证据的收集。"""
from flowmind.rules import Rule, evaluate_rules
from flowmind.contracts import Evidence


def _rules():
    return [
        Rule(
            id="R-HI", name="过高", expression="x > 10",
            predicate=lambda m: m["x"] > 10,
            evidence=lambda m: [Evidence(metric="x", value=m["x"], threshold=10, comparison=">")],
        ),
        Rule(
            id="R-LO", name="过低", expression="x < 0",
            predicate=lambda m: m["x"] < 0,
            evidence=lambda m: [Evidence(metric="x", value=m["x"], threshold=0, comparison="<")],
        ),
    ]

def test_only_hit_rules_collected():
    hits, evidence = evaluate_rules(_rules(), {"x": 42})
    assert [h.rule_id for h in hits] == ["R-HI"]
    assert all(h.hit for h in hits)
    assert evidence[0].metric == "x" and evidence[0].value == 42

def test_no_hits_returns_empty():
    hits, evidence = evaluate_rules(_rules(), {"x": 5})
    assert hits == [] and evidence == []
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_rules.py -v`
Expected: FAIL（`ModuleNotFoundError: flowmind.rules`）。

- [ ] **Step 3: 实现 `src/flowmind/rules.py`**

```python
"""声明式规则引擎：规则求值后自动产出「触发规则」与「数据证据」。

推理链的第二、三段不手写——由规则求值生成，保证多技能格式统一。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from flowmind.contracts import Evidence, RuleHit


@dataclass
class Rule:
    """一条声明式规则。

    predicate: 给定指标字典判断是否命中。
    evidence: 命中时抽取的数据证据列表。
    """
    id: str
    name: str
    expression: str  # 人类可读表达式，写入 RuleHit
    predicate: Callable[[dict], bool]
    evidence: Callable[[dict], list[Evidence]]


def evaluate_rules(rules: list[Rule], metrics: dict) -> tuple[list[RuleHit], list[Evidence]]:
    """对指标求值所有规则，收集命中的 RuleHit 及其 Evidence。"""
    hits: list[RuleHit] = []
    evidence: list[Evidence] = []
    for rule in rules:
        if rule.predicate(metrics):
            hits.append(RuleHit(rule_id=rule.id, name=rule.name, expression=rule.expression, hit=True))
            evidence.extend(rule.evidence(metrics))
    return hits, evidence
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_rules.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add src/flowmind/rules.py tests/test_rules.py
git commit -m "feat: 声明式规则引擎 rules（命中规则与证据自动收集）"
```

---

## Task 4: 配置层 `config.py`

**Files:**
- Create: `src/flowmind/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `InventoryConfig(dsi_healthy_max:float=60.0, dsi_watch_max:float=90.0, dsi_warn_max:float=120.0, dsi_low:float=15.0, capital_high:float=100000.0, currency:str="USD")`
  - `FlowmindConfig(inventory:InventoryConfig=InventoryConfig())`
  - `DEFAULT_CONFIG_PATH: Path`（= `Path("flowmind.config.toml")`）
  - `load_config(path:Path=DEFAULT_CONFIG_PATH) -> FlowmindConfig`
  - `save_config(cfg:FlowmindConfig, path:Path=DEFAULT_CONFIG_PATH) -> None`
  - `is_initialized(path:Path=DEFAULT_CONFIG_PATH) -> bool`

- [ ] **Step 1: 写失败测试** `tests/test_config.py`

```python
"""配置层测试：默认回落、用户覆盖、往返一致、初始化判定。"""
from flowmind.config import (
    InventoryConfig, FlowmindConfig, load_config, save_config, is_initialized,
)


def test_defaults_when_no_file(tmp_path):
    path = tmp_path / "flowmind.config.toml"
    cfg = load_config(path)
    assert cfg.inventory.dsi_healthy_max == 60.0
    assert cfg.inventory.currency == "USD"

def test_is_initialized_reflects_file(tmp_path):
    path = tmp_path / "flowmind.config.toml"
    assert is_initialized(path) is False
    save_config(FlowmindConfig(), path)
    assert is_initialized(path) is True

def test_user_values_override_defaults(tmp_path):
    path = tmp_path / "flowmind.config.toml"
    cfg = FlowmindConfig(inventory=InventoryConfig(dsi_healthy_max=30.0, currency="CNY"))
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.inventory.dsi_healthy_max == 30.0
    assert loaded.inventory.currency == "CNY"
    # 未指定的字段仍回落默认
    assert loaded.inventory.dsi_warn_max == 120.0

def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "flowmind.config.toml"
    cfg = FlowmindConfig(inventory=InventoryConfig(capital_high=50000.0))
    save_config(cfg, path)
    assert load_config(path).inventory.capital_high == 50000.0
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: flowmind.config`）。

- [ ] **Step 3: 实现 `src/flowmind/config.py`**

```python
"""配置层：技能内置通用默认，用户配置文件可覆盖。

个性化定制只发生在终端用户的对话式初始化——由消费此包的 Agent
按 README 剧本引导用户，调用 save_config() 写出 flowmind.config.toml。
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path("flowmind.config.toml")


class InventoryConfig(BaseModel):
    """库销比/库存风险技能的可配置阈值（附通用默认值）。"""
    dsi_healthy_max: float = 60.0   # 周转天数 <=此值：健康
    dsi_watch_max: float = 90.0     # <=此值：关注
    dsi_warn_max: float = 120.0     # <=此值：预警；超过：危险
    dsi_low: float = 15.0           # 低于此值：断货风险
    capital_high: float = 100000.0  # 资金占用高阈值（货币单位）
    currency: str = "USD"


class FlowmindConfig(BaseModel):
    """FlowMind 总配置：每技能一段。"""
    inventory: InventoryConfig = Field(default_factory=InventoryConfig)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> FlowmindConfig:
    """读取配置文件；不存在则全用通用默认。用户值覆盖默认，缺项回落默认。"""
    if not path.exists():
        return FlowmindConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return FlowmindConfig.model_validate(data)


def save_config(cfg: FlowmindConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """把配置写回 TOML 文件（供初始化对话调用）。"""
    path.write_text(tomli_w.dumps(cfg.model_dump()), encoding="utf-8")


def is_initialized(path: Path = DEFAULT_CONFIG_PATH) -> bool:
    """判断用户是否已完成个性化初始化。"""
    return path.exists()
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add src/flowmind/config.py tests/test_config.py
git commit -m "feat: 配置层 config（通用默认 + 用户 TOML 覆盖 + 初始化判定）"
```

---

## Task 5: 技能框架 `skill.py`（注册表 + `@skill` + `invoke`）

**Files:**
- Create: `src/flowmind/skill.py`
- Create: `src/flowmind/skills/__init__.py`（本任务先留空占位注释）
- Test: 见 Task 6 的 `tests/test_inventory_risk.py` 覆盖端到端；本任务的框架单元测试写在 `tests/test_skill.py`

**Interfaces:**
- Consumes: `SkillOutput`, `SkillResult`, `SkillError`, `ReliabilityMetrics`, `new_trace`, `TraceContext`（Task 2）。
- Produces:
  - `SkillSpec(id:str, name:str, version:str, func:Callable, input_model:type)`（dataclass）
  - `skill(*, id:str, name:str, version:str)` 装饰器（登记进 `_REGISTRY`，从函数首参注解推断 `input_model`，原样返回函数）
  - `registry() -> dict[str, SkillSpec]`
  - `invoke(skill_id:str, raw_args:dict, trace:TraceContext|None=None) -> SkillResult`

- [ ] **Step 1: 写失败测试** `tests/test_skill.py`

```python
"""技能框架测试：注册、invoke 组装信封、错误路径。"""
import pytest
from pydantic import BaseModel
from flowmind.skill import skill, registry, invoke
from flowmind.contracts import SkillOutput, ReasoningChain


class _In(BaseModel):
    n: int


class _Out(BaseModel):
    doubled: int


@skill(id="_double", name="翻倍", version="0.1.0")
def _double(inp: _In) -> SkillOutput[_Out]:
    chain = ReasoningChain(conclusion="翻倍完成", causal_analysis="n*2", risk_note="无")
    return SkillOutput(data=_Out(doubled=inp.n * 2), reasoning=[chain], sample_size=1)


def test_registered():
    assert "_double" in registry()
    assert registry()["_double"].input_model is _In

def test_invoke_wraps_envelope():
    result = invoke("_double", {"n": 21})
    assert result.ok is True
    assert result.skill == "_double" and result.version == "0.1.0"
    assert result.data.doubled == 42
    assert result.metrics.sample_size == 1
    assert result.metrics.latency_ms >= 0.0
    assert result.trace.trace_id
    assert result.reasoning[0].conclusion == "翻倍完成"

def test_invoke_passthrough_trace():
    from flowmind.contracts import new_trace
    tr = new_trace(trace_id="fixed-1")
    result = invoke("_double", {"n": 1}, trace=tr)
    assert result.trace.trace_id == "fixed-1"

def test_invoke_unknown_skill():
    result = invoke("_nope", {})
    assert result.ok is False and result.error.code == "NOT_FOUND"

def test_invoke_validation_error():
    result = invoke("_double", {"n": "not-int"})
    assert result.ok is False and result.error.code == "VALIDATION"

def test_invoke_internal_error():
    @skill(id="_boom", name="炸", version="0.1.0")
    def _boom(inp: _In) -> SkillOutput[_Out]:
        raise RuntimeError("boom")
    result = invoke("_boom", {"n": 1})
    assert result.ok is False and result.error.code == "INTERNAL"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_skill.py -v`
Expected: FAIL（`ModuleNotFoundError: flowmind.skill`）。

- [ ] **Step 3: 实现 `src/flowmind/skill.py`**

```python
"""技能框架：@skill 装饰器 + 注册表 + invoke。

这是「skills 融合 mcp」的融合点：一次 @skill 定义即登记进注册表，
server 端遍历注册表把每个技能暴露为 MCP 工具。
invoke() 统一为技能套上 SkillResult 信封（trace/计时/错误兜底）。
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from flowmind.contracts import (
    ReliabilityMetrics,
    SkillError,
    SkillOutput,
    SkillResult,
    TraceContext,
    new_trace,
)


@dataclass
class SkillSpec:
    """一个已注册技能的元数据。"""
    id: str
    name: str
    version: str
    func: Callable[[Any], SkillOutput]
    input_model: type[BaseModel]


_REGISTRY: dict[str, SkillSpec] = {}


def skill(*, id: str, name: str, version: str) -> Callable:
    """把一个业务函数登记为技能。函数签名首参注解即输入模型。"""
    def deco(func: Callable[[Any], SkillOutput]) -> Callable[[Any], SkillOutput]:
        params = list(inspect.signature(func).parameters.values())
        if not params:
            raise TypeError(f"技能 {id} 必须有一个输入模型参数")
        input_model = params[0].annotation
        if not (isinstance(input_model, type) and issubclass(input_model, BaseModel)):
            raise TypeError(f"技能 {id} 的首参注解必须是 pydantic BaseModel 子类")
        _REGISTRY[id] = SkillSpec(id=id, name=name, version=version, func=func, input_model=input_model)
        return func
    return deco


def registry() -> dict[str, SkillSpec]:
    """返回注册表快照。"""
    return dict(_REGISTRY)


def _fail(skill_id: str, trace: TraceContext, error: SkillError) -> SkillResult:
    """构造失败信封（错误永不静默）。"""
    return SkillResult(
        ok=False,
        skill=skill_id,
        version=_REGISTRY[skill_id].version if skill_id in _REGISTRY else "unknown",
        trace=trace,
        metrics=ReliabilityMetrics(latency_ms=0.0, confidence=0.0, sample_size=0),
        error=error,
    )


def invoke(skill_id: str, raw_args: dict, trace: TraceContext | None = None) -> SkillResult:
    """调用技能并组装对外 SkillResult 信封。任何失败均返回结构化结果。"""
    tr = trace or new_trace()
    spec = _REGISTRY.get(skill_id)
    if spec is None:
        return _fail(skill_id, tr, SkillError(code="NOT_FOUND", message=f"未知技能：{skill_id}"))

    try:
        inp = spec.input_model.model_validate(raw_args)
    except ValidationError as exc:
        return _fail(skill_id, tr, SkillError(code="VALIDATION", message="入参校验失败", details={"errors": exc.errors(include_url=False)}))

    start = perf_counter()
    try:
        out: SkillOutput = spec.func(inp)
    except Exception as exc:  # 兜底：技能内部异常不外泄为崩溃
        return _fail(skill_id, tr, SkillError(code="INTERNAL", message=str(exc)))

    latency_ms = (perf_counter() - start) * 1000.0
    metrics = ReliabilityMetrics(
        latency_ms=latency_ms,
        confidence=out.confidence,
        sample_size=out.sample_size,
        degraded=out.degraded,
        degradation_reason=out.degradation_reason,
    )
    return SkillResult(
        ok=True,
        skill=spec.id,
        version=spec.version,
        trace=tr,
        data=out.data,
        reasoning=out.reasoning,
        metrics=metrics,
    )
```

- [ ] **Step 4: 建技能包占位** `src/flowmind/skills/__init__.py`

```python
"""技能包：导入各技能以触发 @skill 注册。"""
# Task 6 将加入：from flowmind.skills import inventory_risk  # noqa: F401
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_skill.py -v`
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add src/flowmind/skill.py src/flowmind/skills/__init__.py tests/test_skill.py
git commit -m "feat: 技能框架 skill（注册表 + @skill + invoke 信封组装）"
```

---

## Task 6: 参考技能 `skills/inventory_risk.py`

**Files:**
- Create: `src/flowmind/skills/inventory_risk.py`
- Modify: `src/flowmind/skills/__init__.py`（加入导入触发注册）
- Test: `tests/test_inventory_risk.py`

**Interfaces:**
- Consumes: `skill`, `invoke`（Task 5）；`Rule`, `evaluate_rules`（Task 3）；`InventoryConfig`, `load_config`（Task 4）；`SkillOutput`, `ReasoningChain`, `Evidence`（Task 2）。
- Produces:
  - `InventoryItem(sku:str, on_hand:int, unit_cost:float, sales_30d:int, in_transit:int=0, price:float|None=None, category:str|None=None)`
  - `InventoryInput(items:list[InventoryItem])`
  - `SkuAnalysis(sku:str, on_hand:int, sales_30d:int, dsi:float|None, inventory_sales_ratio:float|None, capital_occupied:float, risk_level:str, hit_rules:list[str])`
  - `InventorySummary(total_capital_occupied:float, dead_stock_capital:float, level_counts:dict[str,int], top_risks:list[str])`
  - `InventoryReport(items:list[SkuAnalysis], summary:InventorySummary, currency:str)`
  - 已注册技能 `inventory_risk`（version `0.1.0`）返回 `SkillOutput[InventoryReport]`

- [ ] **Step 1: 写失败测试** `tests/test_inventory_risk.py`

```python
"""参考技能测试：分级、汇总、四段式链、边界与错误。"""
from flowmind.skill import invoke


def _args(items):
    return {"items": items}


def test_healthy_item_no_flag():
    # DSI = 100 / (60/30) = 50 天 → 健康
    result = invoke("inventory_risk", _args([
        {"sku": "A", "on_hand": 100, "unit_cost": 2.0, "sales_30d": 60},
    ]))
    assert result.ok is True
    item = result.data.items[0]
    assert item.risk_level == "健康"
    assert result.data.summary.level_counts["健康"] == 1

def test_dead_stock_is_danger_with_chain():
    # 有货零动销 → 危险 + 命中 INV-P01
    result = invoke("inventory_risk", _args([
        {"sku": "B", "on_hand": 50, "unit_cost": 10.0, "sales_30d": 0},
    ]))
    item = result.data.items[0]
    assert item.risk_level == "危险"
    assert "INV-P01" in item.hit_rules
    assert item.dsi is None
    assert result.data.summary.dead_stock_capital == 500.0
    # 四段式链四要素齐全
    chain = result.reasoning[0]
    assert chain.conclusion and chain.causal_analysis and chain.risk_note
    assert any(r.rule_id == "INV-P01" for r in chain.triggered_rules)
    assert len(chain.evidence) >= 1

def test_slow_turn_high_capital_escalates():
    # DSI = 1000/(30/30)=1000 天, 资金占用=1000*200=200000 → 危险, 命中 P02/P03
    result = invoke("inventory_risk", _args([
        {"sku": "C", "on_hand": 1000, "unit_cost": 200.0, "sales_30d": 30},
    ]))
    item = result.data.items[0]
    assert item.risk_level == "危险"
    assert "INV-P02" in item.hit_rules

def test_low_dsi_is_restock_warning():
    # DSI = 5/(60/30)=2.5 天 (<15) → 预警(断货风险), 命中 INV-P04
    result = invoke("inventory_risk", _args([
        {"sku": "D", "on_hand": 5, "unit_cost": 3.0, "sales_30d": 60},
    ]))
    item = result.data.items[0]
    assert item.risk_level == "预警"
    assert "INV-P04" in item.hit_rules

def test_summary_top_risks_and_totals():
    result = invoke("inventory_risk", _args([
        {"sku": "A", "on_hand": 100, "unit_cost": 2.0, "sales_30d": 60},   # 健康
        {"sku": "B", "on_hand": 50, "unit_cost": 10.0, "sales_30d": 0},    # 危险
    ]))
    summary = result.data.summary
    assert summary.total_capital_occupied == 100 * 2.0 + 50 * 10.0
    assert "B" in summary.top_risks

def test_empty_input_is_validation_error():
    result = invoke("inventory_risk", {"items": []})
    assert result.ok is False and result.error.code == "VALIDATION"

def test_negative_on_hand_is_validation_error():
    result = invoke("inventory_risk", _args([
        {"sku": "X", "on_hand": -1, "unit_cost": 1.0, "sales_30d": 1},
    ]))
    assert result.ok is False and result.error.code == "VALIDATION"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_inventory_risk.py -v`
Expected: FAIL（技能未注册 → `NOT_FOUND`，断言失败）。

- [ ] **Step 3: 实现 `src/flowmind/skills/inventory_risk.py`**

```python
"""参考技能：库销比/库存风险分析。

纯确定性计算，无外部依赖。阈值来自 config（用户配置 > 通用默认）。
输出每 SKU 分析 + 汇总，并对被标记 SKU 生成四段式因果推理链。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, PositiveInt, field_validator

from flowmind.config import InventoryConfig, load_config
from flowmind.contracts import Evidence, ReasoningChain, SkillOutput
from flowmind.rules import Rule, evaluate_rules
from flowmind.skill import skill

_VERSION = "0.1.0"
_LEVEL_ORDER = {"危险": 3, "预警": 2, "关注": 1, "健康": 0}


class InventoryItem(BaseModel):
    """单个 SKU 的库存与销量记录。"""
    sku: str
    on_hand: int = Field(ge=0)          # 在库数量
    unit_cost: float = Field(ge=0)      # 单位成本
    sales_30d: int = Field(ge=0)        # 近30天销量
    in_transit: int = Field(default=0, ge=0)  # 在途数量
    price: float | None = None
    category: str | None = None


class InventoryInput(BaseModel):
    """库销比技能入参：至少一条记录。"""
    items: list[InventoryItem]

    @field_validator("items")
    @classmethod
    def _non_empty(cls, v: list[InventoryItem]) -> list[InventoryItem]:
        if not v:
            raise ValueError("items 不能为空")
        return v


class SkuAnalysis(BaseModel):
    """单 SKU 分析结果。"""
    sku: str
    on_hand: int
    sales_30d: int
    dsi: float | None                    # 周转天数；无动销为 None
    inventory_sales_ratio: float | None  # 库销比；无动销为 None
    capital_occupied: float
    risk_level: str
    hit_rules: list[str] = Field(default_factory=list)


class InventorySummary(BaseModel):
    """全局汇总。"""
    total_capital_occupied: float
    dead_stock_capital: float
    level_counts: dict[str, int]
    top_risks: list[str]


class InventoryReport(BaseModel):
    """库销比技能业务载荷。"""
    items: list[SkuAnalysis]
    summary: InventorySummary
    currency: str


def _metrics(item: InventoryItem) -> dict:
    """计算单 SKU 指标；无动销时 DSI/库销比为 None。"""
    dsi = None if item.sales_30d == 0 else item.on_hand / (item.sales_30d / 30.0)
    ratio = None if item.sales_30d == 0 else item.on_hand / item.sales_30d
    return {
        "sku": item.sku,
        "on_hand": item.on_hand,
        "sales_30d": item.sales_30d,
        "unit_cost": item.unit_cost,
        "dsi": dsi,
        "ratio": ratio,
        "capital": item.on_hand * item.unit_cost,
    }


def _rules(cfg: InventoryConfig) -> list[Rule]:
    """基于配置阈值构造规则集。"""
    return [
        Rule(
            id="INV-P01", name="滞销积压", expression="sales_30d==0 且 on_hand>0",
            predicate=lambda m: m["sales_30d"] == 0 and m["on_hand"] > 0,
            evidence=lambda m: [
                Evidence(metric="近30天销量", value=m["sales_30d"], threshold=0, comparison="==", window="近30天"),
                Evidence(metric="在库数量", value=m["on_hand"], threshold=0, comparison=">"),
            ],
        ),
        Rule(
            id="INV-P02", name="周转过慢", expression=f"DSI > {cfg.dsi_warn_max}",
            predicate=lambda m: m["dsi"] is not None and m["dsi"] > cfg.dsi_warn_max,
            evidence=lambda m: [
                Evidence(metric="周转天数(DSI)", value=round(m["dsi"], 1), threshold=cfg.dsi_warn_max, comparison=">", window="近30天"),
            ],
        ),
        Rule(
            id="INV-P03", name="慢周转+资金占用高",
            expression=f"DSI > {cfg.dsi_watch_max} 且 资金占用 > {cfg.capital_high}",
            predicate=lambda m: m["dsi"] is not None and m["dsi"] > cfg.dsi_watch_max and m["capital"] > cfg.capital_high,
            evidence=lambda m: [
                Evidence(metric="周转天数(DSI)", value=round(m["dsi"], 1), threshold=cfg.dsi_watch_max, comparison=">"),
                Evidence(metric="资金占用", value=round(m["capital"], 2), threshold=cfg.capital_high, comparison=">"),
            ],
        ),
        Rule(
            id="INV-P04", name="断货风险", expression=f"DSI < {cfg.dsi_low}",
            predicate=lambda m: m["dsi"] is not None and m["dsi"] < cfg.dsi_low,
            evidence=lambda m: [
                Evidence(metric="周转天数(DSI)", value=round(m["dsi"], 1), threshold=cfg.dsi_low, comparison="<", window="近30天"),
            ],
        ),
    ]


def _level(m: dict, cfg: InventoryConfig) -> str:
    """按指标与阈值判定风险等级。"""
    if m["sales_30d"] == 0 and m["on_hand"] > 0:
        return "危险"
    dsi = m["dsi"]
    if dsi is None:  # 零库存零动销
        return "健康"
    if dsi < cfg.dsi_low:
        return "预警"  # 断货风险
    if dsi <= cfg.dsi_healthy_max:
        base = "健康"
    elif dsi <= cfg.dsi_watch_max:
        base = "关注"
    elif dsi <= cfg.dsi_warn_max:
        base = "预警"
    else:
        base = "危险"
    if base == "关注" and m["capital"] > cfg.capital_high:
        base = "预警"  # 资金占用高则升级
    return base


def _advice(m: dict, level: str) -> str:
    """按情形给出处置建议。"""
    if m["sales_30d"] == 0 and m["on_hand"] > 0:
        return "立即清仓去化，停止补货"
    if m["dsi"] is not None and m["dsi"] < 15:
        return "加快补货，防止断货"
    if level in ("预警", "危险"):
        return "促销/调价加速去化"
    if level == "关注":
        return "关注动销，控制补货节奏"
    return "保持现状"


def _chain(m: dict, level: str, cfg: InventoryConfig, hits, evidence) -> ReasoningChain:
    """组装四段式因果推理链。"""
    dsi_txt = "无动销" if m["dsi"] is None else f"{m['dsi']:.1f} 天"
    return ReasoningChain(
        conclusion=f"SKU {m['sku']} 风险等级：{level}；建议：{_advice(m, level)}",
        triggered_rules=hits,
        evidence=evidence,
        causal_analysis=(
            f"周转天数={dsi_txt}、资金占用={m['capital']:.2f}{cfg.currency}，"
            f"命中 {len(hits)} 条规则，综合判定为「{level}」。"
        ),
        risk_note=_advice(m, level),
    )


@skill(id="inventory_risk", name="库销比/库存风险分析", version=_VERSION)
def inventory_risk(inp: InventoryInput) -> SkillOutput[InventoryReport]:
    """分析每个 SKU 的周转与资金占用，输出风险分级、汇总与推理链。"""
    cfg = load_config().inventory
    rules = _rules(cfg)

    analyses: list[SkuAnalysis] = []
    chains: list[ReasoningChain] = []
    level_counts: dict[str, int] = {"健康": 0, "关注": 0, "预警": 0, "危险": 0}
    total_capital = 0.0
    dead_capital = 0.0

    for item in inp.items:
        m = _metrics(item)
        level = _level(m, cfg)
        hits, evidence = evaluate_rules(rules, m)
        level_counts[level] += 1
        total_capital += m["capital"]
        if m["sales_30d"] == 0 and m["on_hand"] > 0:
            dead_capital += m["capital"]

        analyses.append(SkuAnalysis(
            sku=item.sku,
            on_hand=item.on_hand,
            sales_30d=item.sales_30d,
            dsi=None if m["dsi"] is None else round(m["dsi"], 1),
            inventory_sales_ratio=None if m["ratio"] is None else round(m["ratio"], 2),
            capital_occupied=round(m["capital"], 2),
            risk_level=level,
            hit_rules=[h.rule_id for h in hits],
        ))
        if level != "健康":
            chains.append(_chain(m, level, cfg, hits, evidence))

    # Top 风险：按等级严重度、其次资金占用排序，取前 5 个 SKU
    ranked = sorted(
        [a for a in analyses if a.risk_level != "健康"],
        key=lambda a: (_LEVEL_ORDER[a.risk_level], a.capital_occupied),
        reverse=True,
    )
    top_risks = [a.sku for a in ranked[:5]]

    report = InventoryReport(
        items=analyses,
        summary=InventorySummary(
            total_capital_occupied=round(total_capital, 2),
            dead_stock_capital=round(dead_capital, 2),
            level_counts=level_counts,
            top_risks=top_risks,
        ),
        currency=cfg.currency,
    )
    return SkillOutput(data=report, reasoning=chains, confidence=1.0, sample_size=len(inp.items))
```

- [ ] **Step 4: 注册技能** —— 修改 `src/flowmind/skills/__init__.py`

```python
"""技能包：导入各技能以触发 @skill 注册。"""
from flowmind.skills import inventory_risk  # noqa: F401
```

同时确保 `invoke` 能找到技能：本任务测试通过 `from flowmind.skill import invoke` 前，需先 `import flowmind.skills`。为此在 `tests/test_inventory_risk.py` 顶部加入：

```python
import flowmind.skills  # noqa: F401  触发技能注册
```

（放在 `from flowmind.skill import invoke` 之前。）

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_inventory_risk.py -v`
Expected: 全部 PASS。

- [ ] **Step 6: 全量回归**

Run: `uv run pytest -v`
Expected: 全部 PASS（contracts/rules/config/skill/inventory_risk/smoke）。

- [ ] **Step 7: 提交**

```bash
git add src/flowmind/skills/inventory_risk.py src/flowmind/skills/__init__.py tests/test_inventory_risk.py
git commit -m "feat: 参考技能 inventory_risk（库销比/库存风险 + 四段式推理链）"
```

---

## Task 7: 能力清单 `manifest.py`

**Files:**
- Create: `src/flowmind/manifest.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: `registry()`（Task 5）；技能注册副作用需 `import flowmind.skills`。
- Produces: `build_manifest() -> dict`，结构：`{"skills": [{"id", "name", "version", "input_schema", "reliability_profile"}]}`。

- [ ] **Step 1: 写失败测试** `tests/test_manifest.py`

```python
"""能力清单测试：可发现技能及其输入 schema。"""
import flowmind.skills  # noqa: F401  触发注册
from flowmind.manifest import build_manifest


def test_manifest_lists_inventory_risk():
    manifest = build_manifest()
    ids = [s["id"] for s in manifest["skills"]]
    assert "inventory_risk" in ids

def test_manifest_entry_shape():
    manifest = build_manifest()
    entry = next(s for s in manifest["skills"] if s["id"] == "inventory_risk")
    assert entry["name"] == "库销比/库存风险分析"
    assert entry["version"] == "0.1.0"
    assert entry["input_schema"]["type"] == "object"
    assert "items" in entry["input_schema"]["properties"]
    assert entry["reliability_profile"]["deterministic"] is True
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: FAIL（`ModuleNotFoundError: flowmind.manifest`）。

- [ ] **Step 3: 实现 `src/flowmind/manifest.py`**

```python
"""能力清单：由注册表生成机器可读描述，供龙虾/Agent 发现与挂载。"""
from __future__ import annotations

from flowmind.skill import registry


def build_manifest() -> dict:
    """生成能力清单。每个技能附输入 schema 与可靠性画像。"""
    skills = []
    for spec in registry().values():
        skills.append({
            "id": spec.id,
            "name": spec.name,
            "version": spec.version,
            "input_schema": spec.input_model.model_json_schema(),
            "reliability_profile": {
                "deterministic": True,     # 纯确定性计算
                "emits_reasoning_chain": True,
                "typical_latency_ms": "<50",
                "confidence": 1.0,
            },
        })
    return {"skills": skills}
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add src/flowmind/manifest.py tests/test_manifest.py
git commit -m "feat: 能力清单 manifest（技能发现 + 输入 schema + 可靠性画像）"
```

---

## Task 8: MCP 暴露层 `server.py`

**Files:**
- Create: `src/flowmind/server.py`
- Test: `tests/test_server_mcp.py`

**Interfaces:**
- Consumes: `registry()`, `invoke()`（Task 5）；`import flowmind.skills` 触发注册；`SkillResult`（Task 2）；FastMCP（`mcp.server.fastmcp`）。
- Produces:
  - 模块级 `mcp`（FastMCP 实例，已登记全部技能为工具）
  - `register_all(server) -> None`（遍历注册表登记工具）
  - `main() -> None`（`mcp.run()` stdio 入口，供 `flowmind-mcp`）

- [ ] **Step 1: 写失败测试** `tests/test_server_mcp.py`

```python
"""MCP 暴露层测试：工具被发现、调用返回结构化内容。

注：MCP 版本细节多变，本测试仅验证「已登记 + 调用不报错」，
丰富的正确性断言在 test_inventory_risk（invoke 层）中完成。
"""
import pytest
from flowmind.server import mcp


@pytest.mark.asyncio
async def test_tool_is_listed():
    tools = await mcp.list_tools()
    assert any(t.name == "inventory_risk" for t in tools)

@pytest.mark.asyncio
async def test_tool_call_returns_content():
    result = await mcp.call_tool(
        "inventory_risk",
        {"inp": {"items": [{"sku": "A", "on_hand": 100, "unit_cost": 2.0, "sales_30d": 60}]}},
    )
    # FastMCP 不同版本返回形态不一（内容序列 或 (content, structured) 元组），
    # 只断言拿到了非空结果。
    assert result is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_server_mcp.py -v`
Expected: FAIL（`ModuleNotFoundError: flowmind.server`）。

- [ ] **Step 3: 实现 `src/flowmind/server.py`**

```python
"""MCP 暴露层：遍历注册表，把每个技能登记为一个 MCP 工具。

skills 融合 mcp——技能只需 @skill 定义，无需改动本文件即被暴露。
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import flowmind.skills  # noqa: F401  触发技能注册
from flowmind.contracts import SkillResult
from flowmind.skill import invoke, registry

mcp = FastMCP("FlowMind Skills")


def _make_tool(spec):
    """为一个技能构造 MCP 工具函数（输入=其 pydantic 模型，输出=SkillResult）。"""
    input_model = spec.input_model
    skill_id = spec.id

    def tool(inp) -> SkillResult:
        raw = inp.model_dump() if hasattr(inp, "model_dump") else dict(inp)
        return invoke(skill_id, raw)

    # 让 FastMCP 从注解推断输入 schema 与返回类型
    tool.__name__ = skill_id
    tool.__doc__ = spec.name
    tool.__annotations__ = {"inp": input_model, "return": SkillResult}
    return tool


def register_all(server: FastMCP) -> None:
    """把注册表中所有技能登记为 MCP 工具。"""
    for spec in registry().values():
        server.add_tool(_make_tool(spec), name=spec.id, description=spec.name)


register_all(mcp)


def main() -> None:
    """flowmind-mcp 入口：以 stdio 传输启动 MCP 服务器。"""
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过（如遇 API 不符则校正）**

Run: `uv run pytest tests/test_server_mcp.py -v`
Expected: 全部 PASS。

若失败且报 `ImportError`/`AttributeError`（说明本机装的是 v2 或 API 略有差异），先运行一次性探针确认真实 API，再据此校正 `server.py` 的导入与 `add_tool`/`list_tools`/`call_tool` 调用：

Run: `uv run python -c "import mcp, inspect; from mcp.server.fastmcp import FastMCP; s=FastMCP('t'); print([m for m in dir(s) if not m.startswith('_')])"`
Expected: 打印出包含 `add_tool`、`list_tools`、`call_tool`、`run` 的方法名列表。

- [ ] **Step 5: 手动验证入口可启动**

Run: `timeout 2 uv run flowmind-mcp; echo "exit=$?"`
Expected: 进程启动并等待 stdio 输入，被 timeout 终止（`exit=124`），无导入/启动异常堆栈。

- [ ] **Step 6: 全量回归**

Run: `uv run pytest -v`
Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add src/flowmind/server.py tests/test_server_mcp.py
git commit -m "feat: MCP 暴露层 server（遍历注册表登记工具 + flowmind-mcp 入口）"
```

---

## Task 9: README（人类文档 + Agent 初始化剧本）

**Files:**
- Create: `README.md`（覆盖现有空文件）

**Interfaces:**
- Consumes: `is_initialized`, `save_config`, `FlowmindConfig`, `InventoryConfig`（Task 4）；`build_manifest`（Task 7）；`invoke`（Task 5）；`flowmind-mcp`（Task 8）。

- [ ] **Step 1: 写 `README.md`**

````markdown
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
````

- [ ] **Step 2: 验证 README 中的代码可运行**

Run: `uv run python -c "import flowmind.skills; from flowmind.skill import invoke; r=invoke('inventory_risk', {'items':[{'sku':'A','on_hand':100,'unit_cost':2.0,'sales_30d':60}]}); print(r.ok, r.data.summary.level_counts)"`
Expected: 打印 `True {'健康': 1, '关注': 0, '预警': 0, '危险': 0}`。

Run: `uv run python -c "from flowmind.config import FlowmindConfig, InventoryConfig, save_config, load_config, is_initialized; import pathlib; p=pathlib.Path('/tmp/fm_probe.toml'); save_config(FlowmindConfig(inventory=InventoryConfig(currency='CNY')), p); print(load_config(p).inventory.currency); p.unlink()"`
Expected: 打印 `CNY`。

- [ ] **Step 3: 提交**

```bash
git add README.md
git commit -m "docs: README（使用说明 + Agent 初始化剧本）"
```

---

## Task 10: 收尾——全量校验与 lint

**Files:** 无新增（校验既有代码）。

- [ ] **Step 1: 全量测试**

Run: `uv run pytest -v`
Expected: 全部 PASS（test_smoke/contracts/rules/config/skill/inventory_risk/manifest/server_mcp）。

- [ ] **Step 2: lint**

Run: `uv run ruff check src tests`
Expected: `All checks passed!`（如有告警，按提示修正后重跑至通过；修正不得改变行为）。

- [ ] **Step 3: 验收自查**（对照 spec §13）

逐条确认：
1. `uv run pytest` 全绿 ✓
2. `uv run flowmind-mcp` 可启动（Task 8 Step 5 已验）✓
3. MCP 可发现并调用 `inventory_risk`，返回含 `reasoning`/`metrics`/`trace` 的 `SkillResult` ✓
4. `build_manifest()` 含 `inventory_risk`（含可靠性画像）✓
5. 无用户配置时用通用默认运行；写入 `flowmind.config.toml` 后被用户值覆盖；README 含 Agent 初始化剧本 ✓
6. 新增技能仅需一个 `@skill` 函数 + 其规则 + 其配置模型，无需改 server/契约层 ✓

- [ ] **Step 4: 提交（如 lint 有修正）**

```bash
git add -A
git commit -m "chore: 收尾 lint 与全量校验"
```

---

## Self-Review（本计划对照 spec）

- **Spec 覆盖**：契约(§4→Task2)、技能框架/融合(§5→Task5)、规则引擎(§6→Task3)、参考技能(§7→Task6)、配置与初始化(§8→Task4+Task9)、数据流(§9→Task5 invoke)、错误处理(§10→Task5 invoke 三类错误)、测试(§11→各任务 TDD)、依赖工具链(§12→Task1)、验收(§13→Task10)。全部有对应任务。
- **占位符扫描**：无 TBD/TODO/“稍后实现”；规则谓词与默认阈值在 Task6/Task4 全部写实；MCP API 差异处给出**具体探针命令**而非模糊占位。
- **类型一致性**：`invoke`/`registry`/`skill`/`SkillOutput`/`SkillResult`/`new_trace`/`evaluate_rules`/`Rule`/`load_config`/`InventoryConfig`/`InventoryInput`/`InventoryItem`/`InventoryReport`/`build_manifest`/`register_all`/`main` 跨任务命名一致；技能返回 `SkillOutput`、对外信封 `SkillResult` 由 `invoke` 组装，全程统一。
- **与 spec 的精化**：新增内部 `SkillOutput`（DRY 信封，spec §5 的实现细化，对外契约不变）；新增 `tests/test_skill.py` 与 `tests/test_manifest.py`（spec 测试清单的合理补充）。这些不改变任何对外契约。
