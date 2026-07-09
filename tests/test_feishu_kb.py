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


def test_seed_size_at_least_100() -> None:
    """默认 seed 至少 100 条,确保覆盖度。"""
    from flowmind.skills.feishu_kb import _load_default_faqs

    faqs = _load_default_faqs()
    assert len(faqs) >= 100, f"seed 仅 {len(faqs)} 条,不足以稳定 BM25 召回"


def test_faq_self_match() -> None:
    """FAQ 自命中:用 seed 里一条 question 直接查,Top-1 应高置信命中自己。"""
    from flowmind.skills.feishu_kb import _load_default_faqs

    faqs = _load_default_faqs()
    assert len(faqs) >= 10
    sample = faqs[10]  # 取非首条,避免位置偏差
    result = invoke(
        "feishu_kb_search",
        _args(sample["question"]),
    )
    assert result.ok is True
    assert len(result.data.top_k) >= 1
    top1 = result.data.top_k[0]
    # Top-1 应是样本本身,或高置信命中(同一问题表述)
    assert top1.faq_id == sample["id"] or sample["answer"][:30] in top1.answer
    assert top1.final_score > 0.05, f"自命中置信度太低: {top1.final_score}"


def test_offtopic_returns_degraded() -> None:
    """话题外防御:无关查询返回 degraded=True + top_k=[] + 转人工 hint。"""
    result = invoke("feishu_kb_search", _args("今天北京天气怎么样"))
    assert result.ok is True  # 不报错,只是没命中
    assert result.data.top_k == []
    assert "暂未收录" in result.data.agent_reply_hint or "人工" in result.data.agent_reply_hint


def test_garbage_query_returns_degraded() -> None:
    """纯噪音 query 也走 hard-gate。"""
    result = invoke("feishu_kb_search", _args("asdfgh qwerty"))
    assert result.data.top_k == []
    assert "暂未收录" in result.data.agent_reply_hint


# ====================== 三语支持测试 ======================


def test_detect_chinese() -> None:
    """中文检测:含中文字符 → zh。"""
    from flowmind.skills.feishu_kb import _detect_language

    assert _detect_language("CVT 顿挫") == "zh"
    assert _detect_language("我的车充电很慢") == "zh"


def test_detect_english() -> None:
    """英文检测:纯 ASCII Latin → en。"""
    from flowmind.skills.feishu_kb import _detect_language

    assert _detect_language("CVT jerking") == "en"
    assert _detect_language("how to charge my car") == "en"


def test_detect_thai() -> None:
    """泰文检测:含泰文字符(U+0E00-U+0E7F) → th。"""
    from flowmind.skills.feishu_kb import _detect_language

    assert _detect_language("อาการสะดุด") == "th"
    assert _detect_language("รถชาร์จไฟไม่เข้า") == "th"


def test_english_query_not_blocked_by_chinese_keyword_gate() -> None:
    """英文查询不应被中文关键词 hard-gate 拦截(应能命中 FAQ-0002)。"""
    result = invoke("feishu_kb_search", _args("CVT jerking problem"))
    assert result.ok is True
    # 不应被 hard-gate 拦截 → top_k 应非空
    assert len(result.data.top_k) >= 1
    # agent_reply_hint 应包含翻译指令(英文提示词)
    assert "English" in result.data.agent_reply_hint


def test_thai_query_not_blocked() -> None:
    """泰文查询也应能命中 FAQ。"""
    result = invoke("feishu_kb_search", _args("รถชาร์จไฟไม่เข้า"))
    assert result.ok is True
    assert len(result.data.top_k) >= 1
    # agent_reply_hint 应包含翻译指令(泰文提示词"ภาษาไทย")
    assert "ภาษาไทย" in result.data.agent_reply_hint