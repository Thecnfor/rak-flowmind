"""localize_batch 技能测试：预检、分级、四段式链、HTTP 错误兜底。"""
from __future__ import annotations

import requests

import flowmind.skills  # noqa: F401  触发技能注册
from flowmind.skill import invoke


# ── 工具：构造入参 ──

def _args(paths, *, target_lang="en", source_lang="zh", enable_tts=None,
          chat_id=None, remove_subtitles=None, remove_subtitles_strategy=None):
    """构造入参；None 表示不传该字段（让 skill 走自身/config 默认）。"""
    out = {
        "video_paths": paths,
        "target_lang": target_lang,
        "source_lang": source_lang,
    }
    if enable_tts is not None:
        out["enable_tts"] = enable_tts
    if chat_id is not None:
        out["chat_id"] = chat_id
    if remove_subtitles is not None:
        out["remove_subtitles"] = remove_subtitles
    if remove_subtitles_strategy is not None:
        out["remove_subtitles_strategy"] = remove_subtitles_strategy
    return out


def _path(i, ext=".mp4"):
    return f"/fake/v{i}{ext}"


# ── 工具：HTTP mock ──

class _FakeResp:
    """伪装 requests.Response：可控 status_code / json / 异常。"""

    def __init__(self, *, status_code=200, json_data=None, raise_for_status_exc=None):
        self.status_code = status_code
        self._json = json_data or {}
        self._raise_exc = raise_for_status_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._json


def _install_post(monkeypatch, *, status_code=200, json_data=None, side_effect=None, raise_for_status_exc=None):
    """把 requests.post 替换成可控 fake；返回调用记录列表。

    也同时 mock 技能模块内的 requests.get，让 fail-fast 的 GET /health 默认返回 200。
    调用方想专门测 health 失败时，可直接在自己用例里另设 monkeypatch 覆盖 requests.get。
    """
    import flowmind.skills.localize_batch as lb

    calls: list[dict] = []

    def fake_post(url, json=None, timeout=None, **_kw):
        calls.append({"url": url, "json": json, "timeout": timeout})
        if side_effect is not None:
            raise side_effect
        return _FakeResp(
            status_code=status_code,
            json_data=json_data,
            raise_for_status_exc=raise_for_status_exc,
        )

    def fake_get(url, timeout=None, **_kw):
        return _FakeResp(status_code=200, json_data={"status": "ok"})

    # 直接 patch 技能模块内的 requests.post / requests.get（不污染全局 requests）
    monkeypatch.setattr(lb.requests, "post", fake_post)
    monkeypatch.setattr(lb.requests, "get", fake_get)
    return calls


# ── 预检：入参校验（确定性，不发 HTTP） ──

def test_empty_video_paths_is_validation_error(monkeypatch):
    """空列表应在 pydantic 校验阶段被拒，绝不发 HTTP。"""
    calls = _install_post(monkeypatch)
    result = invoke("localize_batch", _args([]))
    assert result.ok is False
    assert result.error.code == "VALIDATION"
    assert calls == [], "不应触发 HTTP 调用"


def test_unsupported_target_lang_is_validation_error(monkeypatch):
    """目标语言不在 supported_target_langs → VALIDATION。"""
    calls = _install_post(monkeypatch)
    result = invoke("localize_batch", _args([_path(1)], target_lang="xx"))
    assert result.ok is False
    assert result.error.code == "VALIDATION"
    assert calls == []


def test_unsupported_source_lang_is_validation_error(monkeypatch):
    """源语言不在 supported_source_langs → VALIDATION。"""
    calls = _install_post(monkeypatch)
    result = invoke("localize_batch", _args([_path(1)], source_lang="xx"))
    assert result.ok is False
    assert result.error.code == "VALIDATION"
    assert calls == []


# ── 预检：扩展名拒绝（确定性，不发 HTTP） ──

def test_disallowed_extension_rejected_but_others_submitted(monkeypatch):
    """混合扩展名：仅拒绝非 .mp4，剩余合法路径仍提交；rejected_count > 0。"""
    calls = _install_post(
        monkeypatch,
        status_code=200,
        json_data={"batch_id": "b1", "job_ids": ["j1", "j2"], "total": 2, "message": "ok"},
    )
    paths = [_path(1, ".mp4"), _path(2, ".avi"), _path(3, ".mp4"), _path(4, ".mov")]
    result = invoke("localize_batch", _args(paths))
    assert result.ok is True
    assert result.data.rejected_count == 2
    assert result.data.submitted_count == 2
    # HTTP 调用只发了 2 个合法路径
    assert calls and len(calls) == 1
    sent = calls[0]["json"]["video_paths"]
    assert len(sent) == 2
    assert all(p.endswith(".mp4") for p in sent)


def test_all_disallowed_extensions_returns_validation_error(monkeypatch):
    """全部扩展名非法 → 没有可提交项 → VALIDATION，不发 HTTP。"""
    calls = _install_post(monkeypatch)
    result = invoke("localize_batch", _args([_path(1, ".avi"), _path(2, ".mov")]))
    assert result.ok is False
    assert result.error.code == "VALIDATION"
    assert calls == []


# ── 预检：批量超额警告（确定性，不发 HTTP） ──

def test_batch_size_over_limit_emits_warning_chain(monkeypatch):
    """数量 > max_videos_per_batch → 仍提交但推理链出现警告。"""
    _install_post(
        monkeypatch,
        status_code=200,
        json_data={"batch_id": "big", "job_ids": ["j"] * 150, "total": 150, "message": "ok"},
    )
    # 超过默认 max_videos_per_batch=100
    paths = [_path(i) for i in range(150)]
    result = invoke("localize_batch", _args(paths))
    assert result.ok is True
    assert result.data.total == 150
    assert result.data.batch_size_warning is True
    # 推理链四要素齐全
    chain = result.reasoning[0]
    assert chain.conclusion and chain.causal_analysis and chain.risk_note
    # 警告规则被命中
    assert any(r.rule_id == "LOC-W01" for r in chain.triggered_rules)


# ── Happy path（mock HTTP） ──

def test_happy_path_submits_and_returns_batch_result(monkeypatch):
    """正常提交：返回 batch_id / job_ids / 推理链齐全 / 命中 0 条警告规则。"""
    calls = _install_post(
        monkeypatch,
        status_code=200,
        json_data={"batch_id": "abc123", "job_ids": ["j1", "j2"], "total": 2, "message": "Batch created"},
    )
    result = invoke("localize_batch", _args([_path(1), _path(2)], enable_tts=True))
    assert result.ok is True
    assert result.skill == "localize_batch"
    assert result.data.batch_id == "abc123"
    assert result.data.job_ids == ["j1", "j2"]
    assert result.data.total == 2
    assert result.data.submitted_count == 2
    assert result.data.rejected_count == 0
    assert result.data.tts_recommended is True
    # HTTP 调用地址正确
    assert calls and calls[0]["url"].endswith("/api/v1/batch")
    assert calls[0]["json"]["target_lang"] == "en"
    assert calls[0]["json"]["source_lang"] == "zh"
    assert calls[0]["json"]["enable_tts"] is True


def test_urls_skip_extension_check(monkeypatch):
    """http(s):// 开头的路径不校验扩展名，直接放行。"""
    _install_post(
        monkeypatch,
        status_code=200,
        json_data={"batch_id": "u1", "job_ids": ["j1"], "total": 1, "message": "ok"},
    )
    result = invoke("localize_batch", _args(["https://example.com/v.mp4"]))
    assert result.ok is True
    assert result.data.rejected_count == 0


# ── HTTP 错误兜底 ──

def test_http_4xx_returns_internal_error(monkeypatch):
    """VL 返回 4xx → INTERNAL（含 details），不抛裸异常。"""
    _install_post(
        monkeypatch,
        status_code=400,
        json_data={"detail": "Video file not found: /fake/v1.mp4"},
        raise_for_status_exc=requests.HTTPError("400 Client Error"),
    )
    result = invoke("localize_batch", _args([_path(1)]))
    assert result.ok is False
    assert result.error.code == "INTERNAL"
    assert "400" in result.error.message or "Video file" in result.error.message


def test_http_connection_error_returns_internal_error(monkeypatch):
    """连接失败 → INTERNAL（v0.1 不区分 retriable，留作框架增强）。"""
    _install_post(monkeypatch, side_effect=requests.exceptions.ConnectionError("refused"))
    result = invoke("localize_batch", _args([_path(1)]))
    assert result.ok is False
    assert result.error.code == "INTERNAL"


def test_http_timeout_returns_internal_error(monkeypatch):
    """超时 → INTERNAL（v0.1 不区分 retriable）。"""
    _install_post(monkeypatch, side_effect=requests.exceptions.Timeout("slow"))
    result = invoke("localize_batch", _args([_path(1)]))
    assert result.ok is False
    assert result.error.code == "INTERNAL"


# ── 推理链 / 成本档位 / TTS 推荐 ──

def test_reasoning_chain_has_four_stages(monkeypatch):
    """happy path 必产 1 条 ReasoningChain，四字段全非空。"""
    _install_post(
        monkeypatch,
        status_code=200,
        json_data={"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"},
    )
    result = invoke("localize_batch", _args([_path(1)]))
    assert len(result.reasoning) >= 1
    chain = result.reasoning[0]
    assert chain.conclusion
    assert chain.causal_analysis
    assert chain.risk_note
    assert isinstance(chain.triggered_rules, list)
    assert isinstance(chain.evidence, list)


def test_cost_band_thresholds(monkeypatch):
    """视频数量 < cost_low_max → 低；> cost_high_min → 高；之间 → 中。"""
    def submit_with_count(n):
        _install_post(
            monkeypatch,
            status_code=200,
            json_data={"batch_id": "b", "job_ids": [f"j{i}" for i in range(n)], "total": n, "message": "ok"},
        )
        return invoke("localize_batch", _args([_path(i) for i in range(n)]))

    # 5 个 < 20 → 低
    r = submit_with_count(5)
    assert r.ok is True and r.data.cost_band == "低"
    # 50 个在 (20, 100) → 中
    r = submit_with_count(50)
    assert r.data.cost_band == "中"
    # 200 个 ≥ 100 → 高
    r = submit_with_count(200)
    assert r.data.cost_band == "高"


def test_tts_recommendation_off_when_user_disabled(monkeypatch):
    """用户显式 enable_tts=False → 推荐 False（不强行开启）。"""
    _install_post(
        monkeypatch,
        json_data={"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"},
    )
    result = invoke("localize_batch", _args([_path(1)], enable_tts=False))
    assert result.data.tts_recommended is False


def test_metrics_and_trace_present(monkeypatch):
    """ReliabilityMetrics / TraceContext 都被框架填好。"""
    _install_post(
        monkeypatch,
        json_data={"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"},
    )
    result = invoke("localize_batch", _args([_path(1)]))
    assert result.ok is True
    assert result.metrics.latency_ms >= 0.0
    assert result.metrics.sample_size == 1
    assert result.trace.trace_id


# ── 新增契约（#1 remove_subtitles + #2 enable_tts 默认值 + #3 strategy） ──

def test_enable_tts_default_is_true_in_payload(monkeypatch):
    """业务默认要配音：不传 enable_tts 时，payload 应为 True。"""
    calls = _install_post(
        monkeypatch,
        json_data={"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"},
    )
    result = invoke("localize_batch", _args([_path(1)]))
    assert result.ok is True
    # 默认值 = True
    assert calls[0]["json"]["enable_tts"] is True
    assert result.data.tts_recommended is True


def test_enable_tts_explicit_false_overrides_default(monkeypatch):
    """用户显式传 False 时走 False（不能强行开）。"""
    calls = _install_post(
        monkeypatch,
        json_data={"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"},
    )
    result = invoke("localize_batch", _args([_path(1)], enable_tts=False))
    assert result.ok is True
    assert calls[0]["json"]["enable_tts"] is False
    assert result.data.tts_recommended is False


def test_remove_subtitles_default_true_in_payload(monkeypatch):
    """#1：默认应去除字幕（与 VL 默认一致）；不传时 payload 应为 True。"""
    calls = _install_post(
        monkeypatch,
        json_data={"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"},
    )
    result = invoke("localize_batch", _args([_path(1)]))
    assert result.ok is True
    assert calls[0]["json"]["remove_subtitles"] is True
    assert result.data.remove_subtitles is True


def test_remove_subtitles_explicit_false_overrides(monkeypatch):
    """用户显式 False 时不去除。"""
    calls = _install_post(
        monkeypatch,
        json_data={"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"},
    )
    result = invoke("localize_batch", _args([_path(1)], remove_subtitles=False))
    assert result.ok is True
    assert calls[0]["json"]["remove_subtitles"] is False
    assert result.data.remove_subtitles is False


def test_remove_subtitles_strategy_in_payload(monkeypatch):
    """#3：策略字段透传到 VL（v0.3：唯一受支持 ocr_erase_redraw）。"""
    calls = _install_post(
        monkeypatch,
        json_data={"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"},
    )
    result = invoke(
        "localize_batch",
        _args([_path(1)], remove_subtitles_strategy="ocr_erase_redraw"),
    )
    assert result.ok is True
    assert calls[0]["json"]["remove_subtitles_strategy"] == "ocr_erase_redraw"
    assert result.data.remove_subtitles_strategy == "ocr_erase_redraw"


def test_remove_subtitles_strategy_default_in_payload(monkeypatch):
    """#3：不传 strategy 时走 config 默认 ocr_erase_redraw（v0.3 OCR+擦除+重绘）。"""
    calls = _install_post(
        monkeypatch,
        json_data={"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"},
    )
    invoke("localize_batch", _args([_path(1)]))
    assert calls[0]["json"]["remove_subtitles_strategy"] == "ocr_erase_redraw"


def test_remove_subtitles_strategy_rejects_invalid_value(monkeypatch):
    """#3：非法 strategy → VALIDATION，不发 HTTP。
    v0.3 起：delogo/inpaint/overlay/auto 全部被拒；只 ocr_erase_redraw。
    """
    calls = _install_post(monkeypatch)
    result = invoke(
        "localize_batch",
        _args([_path(1)], remove_subtitles_strategy="delogo"),
    )
    assert result.ok is False
    assert result.error.code == "VALIDATION"
    assert calls == []


def test_report_includes_remove_fields(monkeypatch):
    """LocalizerReport 反映两个新字段。"""
    _install_post(
        monkeypatch,
        json_data={"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"},
    )
    result = invoke(
        "localize_batch",
        _args(
            [_path(1)],
            remove_subtitles=False,
            remove_subtitles_strategy="ocr_erase_redraw",
        ),
    )
    d = result.data
    assert d.remove_subtitles is False
    assert d.remove_subtitles_strategy == "ocr_erase_redraw"