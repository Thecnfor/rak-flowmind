"""飞书知识库 FAQ 检索技能：把飞书 Wiki/知识库同步到本地，对用户提问做
4 类意图分类 + BM25+TF-IDF 双路召回 + RRF 融合 + 重排，输出 Top 3 命中
与四段式因果推理链。

设计要点（遵循 FlowMind 约定）：
- 输入用 pydantic 模型校验，输出 SkillOutput[T] 套 SkillResult 信封
- 4 段式链第 2、3 段用 evaluate_rules() 自动产出
- 错误走 degraded=True + SkillError，不抛
- 阈值走 config（用户可覆盖），含通用默认
- trace_id 透传由 invoke() 框架负责，本函数不关心
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import jieba
import numpy as np
from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from flowmind.config import load_config
from flowmind.contracts import Evidence, ReasoningChain, SkillOutput
from flowmind.rules import Rule, evaluate_rules
from flowmind.skill import skill

_VERSION = "0.1.0"

# 4 大营销意图（与种子数据 SUBCATEGORY_TO_INTENT 对齐）
INTENTS: tuple[str, ...] = (
    "产品咨询",
    "故障排查",
    "充电补能",
    "用车指导",
)

# 4 大类关键词词典（启发式权重，足够 demo；生产应从数据自学习）
INTENT_KEYWORDS: dict[str, dict[str, float]] = {
    "产品咨询": {
        "车型": 1.0, "配置": 1.2, "动力": 1.2, "续航": 1.0, "马力": 1.2,
        "扭矩": 1.3, "轴距": 1.2, "外观": 0.8, "内饰": 0.8, "空间": 0.9,
        "智驾": 1.5, "智能驾驶": 1.6, "辅助驾驶": 1.5, "自动驾驶": 1.5,
        "车道保持": 1.6, "自动泊车": 1.6, "ACC": 1.3, "NGP": 1.4,
        "L2": 1.2, "LCC": 1.2, "NOA": 1.6, "车机": 1.2, "OTA": 1.2,
    },
    "故障排查": {
        "故障": 1.4, "报错": 1.5, "故障码": 1.6, "报警": 1.4, "异响": 1.6,
        "抖动": 1.4, "顿挫": 1.6, "失速": 1.8, "无法启动": 1.6,
        "打不着火": 1.6, "黑屏": 1.3, "死机": 1.2, "动力丢失": 1.8,
        "动力中断": 1.8, "跑偏": 1.4, "漏水": 1.5, "漏油": 1.7,
        "不制冷": 1.4, "烧机油": 1.8, "冒烟": 1.5, "跳枪": 1.6,
        "充不进去电": 1.8, "充不上电": 1.8, "充不进电": 1.8,
    },
    "充电补能": {
        "充电": 1.2, "快充": 1.5, "慢充": 1.4, "充电桩": 1.6, "充电枪": 1.5,
        "家用充电": 1.5, "公共充电": 1.4, "充电站": 1.4, "充电时间": 1.4,
        "充电功率": 1.5, "充电接口": 1.4, "直流": 1.2, "交流": 1.0,
        "电池": 1.0, "电池保养": 1.5, "电池寿命": 1.4, "电池衰减": 1.5,
        "实际续航": 1.3, "续航里程": 1.2, "冬季续航": 1.5, "夏季续航": 1.4,
        "预约充电": 1.5, "定时充电": 1.5, "V2L": 1.4, "外放电": 1.4,
    },
    "用车指导": {
        "怎么开": 1.4, "怎么用": 1.3, "如何使用": 1.3, "怎么操作": 1.3,
        "使用方法": 1.3, "保养": 1.4, "保养周期": 1.6, "首保": 1.5,
        "维护": 1.3, "换胎": 1.4, "轮胎": 1.0, "雨刮": 1.2, "玻璃水": 1.2,
        "机油": 1.3, "刹车油": 1.4, "防冻液": 1.4, "儿童锁": 1.4,
        "安全座椅": 1.4, "拖车": 1.3, "搭电": 1.4, "电瓶": 1.3,
        "胎压": 1.4, "质保": 1.5, "三包": 1.5, "救援": 1.4, "4S店": 1.3,
    },
}


# ====================== Pydantic 模型 ======================


class FeishuKbInput(BaseModel):
    """飞书知识库检索技能入参。"""
    query: str = Field(min_length=1, description="用户原句")
    top_k: int = Field(default=3, ge=1, le=20, description="返回条数（默认 3）")


class FaqItem(BaseModel):
    """单条 FAQ 命中。"""
    rank: int
    faq_id: str
    category: str
    question: str
    answer: str
    source_url: str = ""
    final_score: float = 0.0


class FeishuKbReport(BaseModel):
    """技能业务载荷。"""
    query: str
    cleaned_query: str
    intent_category: str
    intent_confidence: float
    matched_keywords: list[str] = Field(default_factory=list)
    top_k: list[FaqItem] = Field(default_factory=list)
    agent_reply_hint: str = ""  # 给上层 Agent 的回复模板指引


# ====================== 内部辅助 ======================


_HTML_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_URL_RE = re.compile(r"https?://[^\s]+|www\.[^\s]+")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "☀-⛿"
    "✀-➿"
    "]"
)
_FULL2HALF = {
    "，": ",", "。": ".", "；": ";", "：": ":", "？": "?", "！": "!",
    "（": "(", "）": ")", "【": "[", "】": "]", "～": "~", "、": ",",
}


def _clean(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _HTML_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _EMOJI_RE.sub(" ", text)
    text = _CTRL_RE.sub(" ", text)
    text = "".join(_FULL2HALF.get(ch, ch) for ch in text)
    return _WS_RE.sub(" ", text).strip()


@lru_cache(maxsize=1)
def _jieba_ready() -> bool:
    jieba.initialize()
    return True


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    _jieba_ready()
    return [t for t in jieba.cut(text.lower()) if t.strip()]


def _classify(cleaned: str) -> tuple[str, float, list[str]]:
    """返回 (category, confidence, matched_keywords)。"""
    if not cleaned:
        return "用车指导", 0.0, []
    matched: dict[str, list[str]] = {c: [] for c in INTENTS}
    raw: dict[str, float] = {c: 0.0 for c in INTENTS}
    cleaned_lower = cleaned.lower()
    for cat, kws in INTENT_KEYWORDS.items():
        for kw, w in kws.items():
            if kw.lower() in cleaned_lower:
                matched[cat].append(kw)
                raw[cat] += w
    if max(raw.values()) <= 0:
        return "用车指导", 0.0, []
    sorted_cats = sorted(raw.items(), key=lambda x: x[1], reverse=True)
    top_cat, top_score = sorted_cats[0]
    second = sorted_cats[1][1] if len(sorted_cats) > 1 else 0.0
    margin = (top_score - second) / max(top_score, 1.0)
    confidence = min(0.5 * margin + 0.5 * min(top_score / 3.0, 1.0) + 0.1, 0.99)
    return top_cat, round(confidence, 3), matched[top_cat]


@dataclass
class _Candidate:
    faq_id: str
    category: str
    question: str
    answer: str
    source_url: str
    bm25_score: float
    vector_score: float
    rrf_score: float


def _hybrid_search(faqs: list[dict], cleaned: str, top_n: int) -> list[_Candidate]:
    """BM25 + TF-IDF 双路召回 + RRF 融合。"""
    if not faqs or not cleaned.strip():
        return []
    docs = [(f.get("question", "") + " " + f.get("answer", "")).strip() for f in faqs]
    corpus_tokens = [_tokenize(d) for d in docs]
    if not any(corpus_tokens):
        return []
    bm25 = BM25Okapi(corpus_tokens)
    q_tokens = _tokenize(cleaned)
    if not q_tokens:
        return []
    bm25_scores = np.asarray(bm25.get_scores(q_tokens), dtype="float32")
    bm25_order = np.argsort(-bm25_scores)[:top_n]
    bm25_results: list[tuple[int, float]] = [
        (int(i), float(bm25_scores[i])) for i in bm25_order if bm25_scores[i] > 0
    ]

    tokenized_str = [" ".join(toks) for toks in corpus_tokens]
    try:
        vectorizer = TfidfVectorizer(token_pattern=r"(?u)\S+", lowercase=True, min_df=1)
        tfidf_matrix = vectorizer.fit_transform(tokenized_str)
        q_vec = vectorizer.transform([" ".join(q_tokens)])
        sims = linear_kernel(q_vec, tfidf_matrix).flatten()
        vec_order = np.argsort(-sims)[:top_n]
        vec_results: list[tuple[int, float]] = [
            (int(i), float(sims[i])) for i in vec_order if sims[i] > 0
        ]
    except ValueError:
        vec_results = []

    # RRF 融合
    by_idx: dict[int, _Candidate] = {}
    for rank, (i, raw) in enumerate(bm25_results, start=1):
        c = by_idx.setdefault(i, _Candidate(
            faq_id=faqs[i].get("id", f"FAQ-{i:04d}"),
            category=faqs[i].get("category", "未分类"),
            question=faqs[i].get("question", ""),
            answer=faqs[i].get("answer", ""),
            source_url=faqs[i].get("source_url", ""),
            bm25_score=0.0, vector_score=0.0, rrf_score=0.0,
        ))
        c.bm25_score = raw
        c.rrf_score += 1.0 / (60 + rank)
    for rank, (i, raw) in enumerate(vec_results, start=1):
        c = by_idx.setdefault(i, _Candidate(
            faq_id=faqs[i].get("id", f"FAQ-{i:04d}"),
            category=faqs[i].get("category", "未分类"),
            question=faqs[i].get("question", ""),
            answer=faqs[i].get("answer", ""),
            source_url=faqs[i].get("source_url", ""),
            bm25_score=0.0, vector_score=0.0, rrf_score=0.0,
        ))
        c.vector_score = raw
        c.rrf_score += 1.0 / (60 + rank)
    return sorted(by_idx.values(), key=lambda x: x.rrf_score, reverse=True)


def _rerank(candidates: list[_Candidate], intent_category: str, top_k: int) -> list[FaqItem]:
    """类别命中加权 + 跨类多样 + 去重 → Top K。"""
    scored: list[tuple[float, _Candidate]] = []
    for c in candidates:
        bonus = 0.05 if c.category == intent_category else 0.0
        final = c.rrf_score + bonus
        scored.append((final, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    picked: list[tuple[float, _Candidate]] = []
    per_cat_limit = max(1, top_k // 2 + 1)
    cat_count: dict[str, int] = {}
    for s in scored:
        c = s[1]
        q = c.question.strip()
        if q in seen:
            continue
        if cat_count.get(c.category, 0) >= per_cat_limit:
            continue
        seen.add(q)
        picked.append(s)
        cat_count[c.category] = cat_count.get(c.category, 0) + 1
        if len(picked) >= top_k:
            break
    if len(picked) < top_k:
        for s in scored:
            if s in picked:
                continue
            picked.append(s)
            if len(picked) >= top_k:
                break
    out: list[FaqItem] = []
    for rank, (final, c) in enumerate(picked, start=1):
        out.append(FaqItem(
            rank=rank, faq_id=c.faq_id, category=c.category,
            question=c.question, answer=c.answer, source_url=c.source_url,
            final_score=round(final, 4),
        ))
    return out


@lru_cache(maxsize=1)
def _load_default_faqs() -> tuple[dict, ...]:
    """加载默认种子数据（与 skill 文件同目录的 seed_faqs.json）。"""
    seed = Path(__file__).parent / "feishu_kb_seed.json"
    if not seed.exists():
        return ()
    return tuple(json.loads(seed.read_text(encoding="utf-8")))


def _rules(intent_category: str, top1_score: float, has_hits: bool) -> list[Rule]:
    """把命中情况描述为声明式规则，供 evaluate_rules 生成第 2、3 段。"""
    return [
        Rule(
            id="KB-INTENT",
            name="意图分类命中",
            expression=f"intent_category == {intent_category}",
            predicate=lambda m: m.get("intent_category") == intent_category,
            evidence=lambda m: [Evidence(
                metric="意图类别", value=m.get("intent_category", ""),
                threshold="产品咨询/故障排查/充电补能/用车指导", comparison="==",
            )],
        ),
        Rule(
            id="KB-HAS-HITS",
            name="有候选命中",
            expression="len(top_k) > 0",
            predicate=lambda m: m.get("has_hits", False),
            evidence=lambda m: [Evidence(
                metric="Top K 候选数", value=len(m.get("top_k_list", [])),
                threshold=1, comparison=">=",
            )],
        ),
        Rule(
            id="KB-HIGH-CONF",
            name="Top 1 高置信度",
            expression="top1_score >= 0.06",
            predicate=lambda m: m.get("top1_score", 0.0) >= 0.06,
            evidence=lambda m: [Evidence(
                metric="Top 1 final_score", value=round(m.get("top1_score", 0.0), 4),
                threshold=0.06, comparison=">=",
            )],
        ),
    ]


def _build_chain(
    query: str,
    intent_category: str,
    intent_confidence: float,
    matched_keywords: list[str],
    top_k: list[FaqItem],
) -> ReasoningChain:
    """组装四段式因果推理链。"""
    has_hits = len(top_k) > 0
    top1_score = top_k[0].final_score if top_k else 0.0
    metrics = {
        "intent_category": intent_category,
        "has_hits": has_hits,
        "top1_score": top1_score,
        "top_k_list": top_k,
    }
    hits, evidence = evaluate_rules(_rules(intent_category, top1_score, has_hits), metrics)
    if has_hits and top1_score >= 0.06:
        conclusion = f"匹配到 {len(top_k)} 个候选 FAQ，最高 final_score={top1_score:.3f}"
    elif has_hits:
        conclusion = f"匹配到 {len(top_k)} 个候选 FAQ，但 Top 1 置信度偏低（{top1_score:.3f}）"
    else:
        conclusion = "未匹配到任何 FAQ，判定为意图不清晰"
    causal = (
        f"用户问题归类为「{intent_category}」（置信度 {intent_confidence}，"
        f"命中关键词 {matched_keywords or '无'}）。"
        f"通过 BM25 + TF-IDF 双路召回、RRF 融合（k=60）、"
        f"类别命中加权 + 跨类多样重排，取 Top {len(top_k)}。"
    )
    risk = (
        "若 Top 1 final_score < 0.02：建议转人工客服，不要强行套用。"
        if has_hits and top1_score < 0.02
        else "若分类置信度 < 0.4：建议转人工或追问澄清。"
    )
    return ReasoningChain(
        conclusion=conclusion,
        triggered_rules=hits,
        evidence=evidence,
        causal_analysis=causal,
        risk_note=risk,
    )


def _agent_reply_hint(query: str, intent_category: str, top_k: list[FaqItem]) -> str:
    """给上层 Agent 的回复模板指引（不是 SkillOutput 必需，是辅助）。"""
    if not top_k:
        return (
            "未召回任何 FAQ。请礼貌告知用户当前问题暂无标准答案，"
            "并引导转人工客服。"
        )
    return (
        f"用户问题：{query}\n"
        f"系统分类：{intent_category}\n"
        f"系统已检索 {len(top_k)} 条相关 FAQ，请你：\n"
        f"  1) 用自然语言整合 Top {len(top_k)} 的答案，**优先用第 1 条**；\n"
        f"  2) 在回复**末尾**附『来源：FAQ-编号 · 飞书链接』；\n"
        f"  3) 回复要像飞书同事的语气，专业、简洁、有人情味。"
    )


# ====================== @skill 入口 ======================


@skill(id="feishu_kb_search", name="飞书知识库 FAQ 检索", version=_VERSION)
def feishu_kb_search(inp: FeishuKbInput) -> SkillOutput[FeishuKbReport]:
    """把飞书知识库 FAQ 同步到本地，对用户提问做 4 类意图分类 +
    BM25+TF-IDF 双路召回 + RRF 融合 + 类别加权重排，输出 Top K 命中
    与四段式因果推理链。

    适用场景：车企 FAQ 智能客服、knowledge base 检索、客服意图分发。
    依赖：jieba（中文分词）+ rank-bm25 + scikit-learn + numpy（见 pyproject.toml）。
    """
    cfg = load_config().feishu_kb
    cleaned = _clean(inp.query)
    intent_category, intent_conf, matched = _classify(cleaned)

    # 加载 FAQ（默认从 seed 文件；生产可换成 faqs.json）
    faqs = list(_load_default_faqs())
    if not faqs:
        return SkillOutput(
            data=FeishuKbReport(
                query=inp.query, cleaned_query=cleaned,
                intent_category=intent_category, intent_confidence=intent_conf,
                matched_keywords=matched, top_k=[],
                agent_reply_hint=f"未加载到任何 FAQ 数据，请配置 {cfg.data_path}。",
            ),
            reasoning=[_build_chain(inp.query, intent_category, intent_conf, matched, [])],
            confidence=0.0, sample_size=0, degraded=True,
            degradation_reason="FAQ 数据未配置或文件不存在",
        )

    # 检索 + 重排
    candidates = _hybrid_search(faqs, cleaned, top_n=cfg.retrieval_top_n)
    top_k = _rerank(candidates, intent_category=intent_category, top_k=inp.top_k)

    return SkillOutput(
        data=FeishuKbReport(
            query=inp.query,
            cleaned_query=cleaned,
            intent_category=intent_category,
            intent_confidence=intent_conf,
            matched_keywords=matched,
            top_k=top_k,
            agent_reply_hint=_agent_reply_hint(inp.query, intent_category, top_k),
        ),
        reasoning=[_build_chain(inp.query, intent_category, intent_conf, matched, top_k)],
        confidence=intent_conf,
        sample_size=len(faqs),
    )


__all__ = ["feishu_kb_search", "FeishuKbInput", "FeishuKbReport", "FaqItem"]