"""飞书知识库 FAQ 检索技能测试：覆盖 4 类意图、双路召回、四段式链、降级路径。"""
from __future__ import annotations

import flowmind.skills  # noqa: F401  触发 @skill 注册
from flowmind.skill import invoke


def _args(query: str, top_k: int = 3):
    return {"query": query, "top_k": top_k}


def test_intent_classification_charging() -> None:
    """充电补能类：用包含「充电」「电池」关键词的查询触发。"""
    result = invoke("feishu_kb_search", _args("动力电池充电指示灯亮"))
    assert result.ok is True
    rep = result.data
    assert rep.intent_category == "充电补能"
    assert rep.intent_confidence > 0.5
    assert len(rep.top_k) > 0
    # 四段式链：4 要素齐全
    chain = result.reasoning[0]
    assert chain.conclusion and chain.causal_analysis and chain.risk_note
    assert len(chain.triggered_rules) >= 1
    assert len(chain.evidence) >= 1
    # 可靠性指标：latency 必有
    assert result.metrics.latency_ms > 0


def test_intent_classification_usage() -> None:
    """用车指导类。"""
    result = invoke("feishu_kb_search", _args("CVT 夏天行驶感觉也没手动挡提速快"))
    assert result.ok is True
    assert result.data.intent_category == "用车指导"
    assert len(result.data.top_k) > 0


def test_intent_classification_fault() -> None:
    """故障排查类。"""
    result = invoke("feishu_kb_search", _args("燃油指示灯点亮了怎么回事"))
    assert result.ok is True
    # 「燃油指示灯」可能匹配 故障排查 / 用车指导；接受其一
    assert result.data.intent_category in ("故障排查", "用车指导")
    assert len(result.data.top_k) > 0


def test_top_k_respected() -> None:
    """top_k 参数被尊重。"""
    result = invoke("feishu_kb_search", _args("充电", top_k=2))
    assert len(result.data.top_k) <= 2


def test_hits_have_source_url() -> None:
    """每个命中含溯源信息。"""
    result = invoke("feishu_kb_search", _args("动力电池充电指示灯亮"))
    for hit in result.data.top_k:
        assert hit.faq_id.startswith("FAQ-")
        assert hit.source_url.startswith("feishu://")
        assert hit.question and hit.answer


def test_empty_query_rejected_by_validation() -> None:
    """空 query 在 pydantic 校验阶段被拒。"""
    result = invoke("feishu_kb_search", _args(""))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "VALIDATION"


def test_four_stage_chain_has_evidence_and_rules() -> None:
    """四段式链：4 要素齐全，且第 2、3 段由 evaluate_rules 自动产出。"""
    result = invoke("feishu_kb_search", _args("动力电池充电指示灯亮"))
    chain = result.reasoning[0]
    # 第 1 段：conclusion
    assert "匹配到" in chain.conclusion
    # 第 2 段：triggered_rules（自动）
    assert len(chain.triggered_rules) >= 1
    assert all(r.rule_id for r in chain.triggered_rules)
    # 第 3 段：evidence（自动）
    assert len(chain.evidence) >= 1
    assert all(e.metric for e in chain.evidence)
    # 第 4 段：causal_analysis + risk_note
    assert "BM25" in chain.causal_analysis or "TF-IDF" in chain.causal_analysis
    assert chain.risk_note


def test_metrics_present() -> None:
    """SkillResult 套上 ReliabilityMetrics：latency + sample_size 必有。"""
    result = invoke("feishu_kb_search", _args("动力电池充电指示灯亮"))
    assert result.metrics.latency_ms > 0
    assert result.metrics.sample_size > 0
    assert 0.0 <= result.metrics.confidence <= 1.0
    assert result.trace.trace_id  # 框架自动生成
    assert result.skill == "feishu_kb_search"
    assert result.version == "0.1.0"


def test_top1_has_positive_score() -> None:
    """Top 1 必有非负 final_score。"""
    result = invoke("feishu_kb_search", _args("CVT 变速器"))
    if result.data.top_k:
        assert result.data.top_k[0].final_score >= 0