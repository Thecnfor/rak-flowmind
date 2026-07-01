"""技能框架：@skill 装饰器 + 注册表 + invoke。

这是「skills 融合 mcp」的融合点：一次 @skill 定义即登记进注册表，
server 端遍历注册表把每个技能暴露为 MCP 工具。
invoke() 统一为技能套上 SkillResult 信封（trace/计时/错误兜底）。
"""
from __future__ import annotations

import inspect
import typing
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
    """把一个业务函数登记为技能。函数签名首参注解即输入模型。

    注解通过 ``typing.get_type_hints`` 解析，因此模块是否启用
    ``from __future__ import annotations``（PEP 563）都不影响：字符串注解
    会按函数所在模块的全局命名空间求值回真实类型。
    """
    def deco(func: Callable[[Any], SkillOutput]) -> Callable[[Any], SkillOutput]:
        params = list(inspect.signature(func).parameters.values())
        if not params:
            raise TypeError(f"技能 {id} 必须有一个输入模型参数")
        first_name = params[0].name
        try:
            hints = typing.get_type_hints(func)
        except Exception as exc:
            raise TypeError(f"技能 {id} 的首参注解解析失败：{exc}") from exc
        input_model = hints.get(first_name)
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
