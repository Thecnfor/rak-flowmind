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
