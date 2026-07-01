"""技能框架测试：注册、invoke 组装信封、错误路径。"""
from __future__ import annotations

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


class _PEP563Model(BaseModel):
    """PEP 563 风格测试用输入模型：模块启用 from __future__ import annotations。"""
    value: int


# 通过 __annotations__ 字符串化首参注解：模拟 PEP 563 行为。
# typing.get_type_hints 会按函数所在模块（此处即 test_skill）的
# 全局命名空间把字符串 "_PEP563Model" / "SkillOutput" 解析回真实类型。
def _pep563_func(inp: _PEP563Model) -> SkillOutput[_Out]:  # type: ignore[valid-type]
    return SkillOutput(
        data=_Out(doubled=inp.value * 2),
        reasoning=[ReasoningChain(conclusion="ok", causal_analysis="*2", risk_note="无")],
        sample_size=1,
    )


_pep563_func.__annotations__ = {
    "inp": "_PEP563Model",
    "return": "SkillOutput",
}


# NOTE: 必须在设置 __annotations__ 之后再装饰，确保装饰器看到的就是字符串化注解。
_skill_pep563 = skill(id="_pep563_skill", name="字符串注解", version="0.1.0")(_pep563_func)


def test_skill_resolves_stringized_annotations():
    """skill 装饰器必须能解析 PEP 563 字符串化注解，确保 input_model 是真实类型。"""
    assert "_pep563_skill" in registry()
    assert registry()["_pep563_skill"].input_model is _PEP563Model


def test_skill_rejects_non_basemodel_annotation():
    """非 BaseModel 的首参注解必须抛 TypeError（中文错误信息）。"""
    def _bad(inp: int) -> SkillOutput[_Out]:
        return SkillOutput(data=_Out(doubled=inp), sample_size=1)

    with pytest.raises(TypeError, match="BaseModel 子类"):
        skill(id="_bad", name="错", version="0.1.0")(_bad)


def test_skill_rejects_duplicate_id():
    """同一 id 二次注册必须抛 ValueError，防止静默覆盖。"""

    @skill(id="_dup_id", name="首次", version="0.1.0")
    def _first(inp: _In) -> SkillOutput[_Out]:
        return SkillOutput(data=_Out(doubled=inp.n), sample_size=1)

    assert "_dup_id" in registry()

    with pytest.raises(ValueError, match="技能 id 已注册，禁止重复"):
        @skill(id="_dup_id", name="重复", version="0.1.0")
        def _second(inp: _In) -> SkillOutput[_Out]:
            return SkillOutput(data=_Out(doubled=inp.n), sample_size=1)
