"""P0a: localize_batch 自动分批 — 超过 max_videos_per_batch 时内部 chunk。

设计：
- 输入 N 个路径，max=100，N=250 → 拆 3 批 (100/100/50) → 3 次 POST
- batch_count 字段报告拆了几批
- batch_ids 字段列所有批号（首条也写到 batch_id 字段以兼容）
- job_ids 合并所有批
- 单批失败：INTERNAL+transient，附 successful_batch_ids 给 Agent 知道哪些提交了
"""
from __future__ import annotations

import requests

import flowmind.skills  # noqa: F401
from flowmind.config import FlowmindConfig, LocalizerConfig
from flowmind.skill import invoke


# ── 工具 ──

def _path(i, ext=".mp4"):
    return f"/fake/v{i}{ext}"


def _install_post_chunked(monkeypatch, *, per_call_response=None, fail_on_call_index=None):
    """按调用次数返回不同响应；模拟分批场景。

    per_call_response: list[dict]，每个元素是一次 POST 的响应体
    fail_on_call_index: 哪个调用抛异常（0-based）
    """
    import flowmind.skills.localize_batch as lb
    calls = []
    call_idx = [0]

    def fake_post(url, json=None, timeout=None, **_kw):
        idx = call_idx[0]
        call_idx[0] += 1
        calls.append({"idx": idx, "url": url, "json": json, "timeout": timeout})
        if fail_on_call_index is not None and idx == fail_on_call_index:
            raise requests.exceptions.ConnectionError(f"call {idx} failed")
        if per_call_response is not None:
            resp = per_call_response[idx] if idx < len(per_call_response) else None
        else:
            resp = None
        body = resp or {"batch_id": f"b{idx}", "job_ids": [f"j{idx}"], "total": 1, "message": "ok"}
        # 把 batch_id / job_ids 按当前 chunk 大小调整
        chunk_size = len(json["video_paths"]) if json and "video_paths" in json else 1
        body = dict(body)
        body.setdefault("batch_id", f"b{idx}")
        body["job_ids"] = [f"j{idx}-{k}" for k in range(chunk_size)]
        body["total"] = chunk_size

        class _R:
            pass
        r = _R()
        r.status_code = 200
        r._json = body
        def raise_for_status():
            pass
        def json_fn():
            return r._json
        r.raise_for_status = raise_for_status
        r.json = json_fn
        return r

    # health 探活
    def fake_get(url, timeout=None, **_kw):
        class _R:
            status_code = 200
            _json = {"status": "ok"}
            def raise_for_status(self): pass
            def json(self): return self._json
        return _R()
    monkeypatch.setattr(lb.requests, "get", fake_get)
    monkeypatch.setattr(lb.requests, "post", fake_post)
    return calls


def _set_max(monkeypatch, max_videos_per_batch: int):
    cfg = FlowmindConfig(localizer=LocalizerConfig(max_videos_per_batch=max_videos_per_batch))
    monkeypatch.setattr("flowmind.skills.localize_batch.load_config", lambda: cfg)


# ── 单批：不拆 ──

def test_under_limit_makes_single_post(monkeypatch):
    """50 个路径、max=100 → 1 次 POST，batch_count=1。"""
    _set_max(monkeypatch, 100)
    calls = _install_post_chunked(monkeypatch)
    paths = [_path(i) for i in range(50)]
    r = invoke("localize_batch", {"video_paths": paths})
    assert r.ok is True
    assert len(calls) == 1
    assert r.data.batch_count == 1
    assert len(r.data.batch_ids) == 1
    assert len(r.data.job_ids) == 50


# ── 多批：自动 chunk ──

def test_over_limit_chunks_into_multiple_posts(monkeypatch):
    """250 个路径、max=100 → 3 次 POST (100/100/50)。"""
    _set_max(monkeypatch, 100)
    calls = _install_post_chunked(monkeypatch)
    paths = [_path(i) for i in range(250)]
    r = invoke("localize_batch", {"video_paths": paths})
    assert r.ok is True
    assert len(calls) == 3
    sizes = [len(c["json"]["video_paths"]) for c in calls]
    assert sizes == [100, 100, 50], f"实际分桶: {sizes}"
    assert r.data.batch_count == 3
    assert len(r.data.batch_ids) == 3
    assert len(r.data.job_ids) == 250
    # 合并后的 job_ids 应该覆盖所有 chunk
    all_job_ids = set(r.data.job_ids)
    expected = {f"j{i}-{k}" for i in range(3) for k in range(sizes[i])}
    assert all_job_ids == expected


def test_exact_multiple_of_max_no_remainder_chunk(monkeypatch):
    """200 个路径、max=100 → 2 次 POST (100/100)，不留空尾。"""
    _set_max(monkeypatch, 100)
    calls = _install_post_chunked(monkeypatch)
    paths = [_path(i) for i in range(200)]
    r = invoke("localize_batch", {"video_paths": paths})
    assert r.ok is True
    assert len(calls) == 2
    assert r.data.batch_count == 2


# ── 部分失败：透出已成功的 batch_id ──

def test_one_chunk_failure_returns_degraded_with_successful_batches(monkeypatch):
    """3 批中第 2 批失败（ConnectionError）→ degraded + environment，partial success 在 data 里。

    v0.3 设计：分类信息在 data.failure_category / data.successful_batch_ids，
    不依赖 SkillError（contracts.py 不变量）。
    """
    _set_max(monkeypatch, 100)
    _install_post_chunked(monkeypatch, fail_on_call_index=1)
    paths = [_path(i) for i in range(250)]
    r = invoke("localize_batch", {"video_paths": paths})
    assert r.metrics.degraded is True
    assert r.data.failure_category == "environment"
    assert r.data.successful_batch_ids == ["b0"], \
        f"实际 successful_batch_ids: {r.data.successful_batch_ids}"
    assert r.data.failed_chunk_index == 1
    assert r.data.retriable is False


# ── 推理链反映分批信息 ──

def test_chunked_request_reasoning_mentions_batch_count(monkeypatch):
    """拆 N 批时推理链结论要说明。"""
    _set_max(monkeypatch, 100)
    _install_post_chunked(monkeypatch)
    paths = [_path(i) for i in range(150)]
    r = invoke("localize_batch", {"video_paths": paths})
    assert r.ok is True
    chain = r.reasoning[0]
    assert "2" in chain.conclusion, f"推理结论应提拆批数: {chain.conclusion}"