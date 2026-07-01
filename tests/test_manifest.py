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