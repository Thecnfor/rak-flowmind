"""discover() / field_names() / manifest 增强测试。

目标：保证 Agent 拿到的 schema 是真实可用的，不会再发生「猜错 data.foo 字段名」的事。
"""
from __future__ import annotations

import flowmind.skills  # noqa: F401  触发注册
from flowmind.discover import discover, field_names
from flowmind.manifest import build_manifest
from flowmind.skill import registry


# ── discover() ──

def test_discover_no_args_returns_all_skills():
    """不传参数 → 包含全部 8 个真实技能的列表。

    注意：test_skill.py 注入了 `_double` / `_boom` 测试桩，可能让 registry > 8；
    这里只断言「包含这 8 个」，不卡总数（测试桩存在性是 test_skill.py 的事）。
    """
    expected = {
        "feishu_kb_search", "inventory_risk", "localize_batch", "localize_cancel",
        "localize_download", "localize_retry", "localize_status", "marketing_image_gen",
    }
    skills = discover()
    assert isinstance(skills, list)
    assert expected.issubset({s["id"] for s in skills}), \
        f"缺失技能：{expected - {s['id'] for s in skills}}"


def test_discover_each_skill_has_full_contract():
    """每个真实技能 dict 都包含完整契约字段（test_skill.py 注入的 _double/_boom
    测试桩不进 discover() —— 它们没 description / output_model，是测试工具）。

    实际上 discover() 不会过滤，但这里我们用 sid 前缀避开 _test 桩。
    """
    skills = discover()
    for s in skills:
        if s["id"].startswith("_"):
            continue  # 跳过 test_skill.py 注入的 _double / _boom 桩
        assert "id" in s and isinstance(s["id"], str)
        assert "name" in s and isinstance(s["name"], str)
        assert "version" in s and isinstance(s["version"], str)
        assert "description" in s and isinstance(s["description"], str) and len(s["description"]) > 0
        assert "input_schema" in s and isinstance(s["input_schema"], dict)
        assert "output_schema" in s and isinstance(s["output_schema"], dict)
        assert "reliability_profile" in s


def test_discover_single_skill_returns_dict():
    info = discover("inventory_risk")
    assert isinstance(info, dict)
    assert info["id"] == "inventory_risk"
    assert info["output_schema"]["type"] == "object"


def test_discover_unknown_skill_raises_with_helpful_message():
    try:
        discover("does_not_exist")
    except KeyError as exc:
        msg = str(exc)
        assert "does_not_exist" in msg
        assert "inventory_risk" in msg  # 列出了可用 skill
        assert "discover()" in msg        # 提示不带参数
    else:
        raise AssertionError("应该抛 KeyError")


# ── field_names() ──

def test_field_names_returns_flat_paths():
    """field_names 给出嵌套路径，避免猜 data.foo vs data.foo.bar。"""
    paths = field_names("inventory_risk")
    assert "data" in paths
    assert "items" in paths["data"]
    assert "summary" in paths["data"]
    assert "currency" in paths["data"]
    # 嵌套字段
    assert "data.items[]" in paths
    assert "sku" in paths["data.items[]"]
    assert "risk_level" in paths["data.items[]"]
    assert "data.summary" in paths
    assert "level_counts" in paths["data.summary"]


def test_field_names_feishu_kb_has_top_k_not_hits():
    """feishu_kb 的命中列表字段叫 top_k 不是 hits——discover 必须如实反映。"""
    paths = field_names("feishu_kb_search")
    assert "data.top_k[]" in paths
    assert "hits" not in paths["data"]   # 实际字段没有 hits
    assert "results" not in paths["data"]
    assert "final_score" in paths["data.top_k[]"]
    assert "question" in paths["data.top_k[]"]


def test_field_names_localize_batch_exposes_failure_fields():
    """localize_batch 必须暴露 degraded 报告所需字段。"""
    paths = field_names("localize_batch")
    assert "failure_category" in paths["data"]
    assert "retriable" in paths["data"]
    assert "successful_batch_ids" in paths["data"]
    assert "warning" in paths["data"]


# ── build_manifest() 一致性 ──

def test_manifest_matches_registry():
    """manifest 里的真实 skill 集合 == registry 里的真实 skill 集合（不含 _test 桩）。"""
    real_skills = {sid for sid in registry() if not sid.startswith("_")}
    manifest = build_manifest()
    real_in_manifest = {s["id"] for s in manifest["skills"] if not s["id"].startswith("_")}
    assert real_skills == real_in_manifest, \
        f"diff: missing={real_skills - real_in_manifest}, extra={real_in_manifest - real_skills}"


def test_manifest_output_schema_is_valid_json_schema():
    """output_schema 是合法的 JSON Schema（至少有 type=object 和 properties）。

    只验证真实技能，跳过 _test 桩。
    """
    for s in build_manifest()["skills"]:
        if s["id"].startswith("_"):
            continue
        schema = s["output_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema


# ── SkillSpec 注册时带 description + output_model ──

def test_skill_spec_has_description_and_output_model():
    """注册元数据必须含 description 和 output_model（v0.3 增强后）。

    只检查 8 个真实技能，不检查 test_skill.py 注入的 _double/_boom 测试桩
    （它们是测试工具，不需要 docstring / 返回注解）。
    """
    real_ids = {sid for sid in registry() if not sid.startswith("_")}
    for sid in real_ids:
        spec = registry()[sid]
        assert spec.description, f"{sid} 缺 description（应该从 docstring 提）"
        assert spec.output_model is not None, f"{sid} 缺 output_model（应该从返回注解提）"


def test_skill_output_model_matches_actual_data_type():
    """output_model 应该是 SkillResult.data 实际类型。"""
    from flowmind.skill import invoke
    # 用最便宜的 inventory_risk 验证一遍
    r = invoke("inventory_risk", {"items": [{"sku": "A", "on_hand": 100, "sales_30d": 30, "unit_cost": 50.0}]})
    spec = registry()["inventory_risk"]
    assert isinstance(r.data, spec.output_model), \
        f"output_model={spec.output_model} 但 r.data 是 {type(r.data)}"


# ── __init__.py 导出 ──

def test_discover_importable_from_flowmind_root():
    """discover / field_names / build_manifest 都从 flowmind 顶层导出。"""
    import flowmind
    assert hasattr(flowmind, "discover")
    assert hasattr(flowmind, "field_names")
    assert hasattr(flowmind, "build_manifest")
    assert hasattr(flowmind, "invoke")
    assert hasattr(flowmind, "registry")
    assert hasattr(flowmind, "skill")