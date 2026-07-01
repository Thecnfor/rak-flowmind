"""参考技能测试：分级、汇总、四段式链、边界与错误。"""
import flowmind.skills  # noqa: F401  触发技能注册
from flowmind.skill import invoke


def _args(items):
    return {"items": items}


def test_healthy_item_no_flag():
    # DSI = 100 / (60/30) = 50 天 → 健康
    result = invoke("inventory_risk", _args([
        {"sku": "A", "on_hand": 100, "unit_cost": 2.0, "sales_30d": 60},
    ]))
    assert result.ok is True
    item = result.data.items[0]
    assert item.risk_level == "健康"
    assert result.data.summary.level_counts["健康"] == 1


def test_dead_stock_is_danger_with_chain():
    # 有货零动销 → 危险 + 命中 INV-P01
    result = invoke("inventory_risk", _args([
        {"sku": "B", "on_hand": 50, "unit_cost": 10.0, "sales_30d": 0},
    ]))
    item = result.data.items[0]
    assert item.risk_level == "危险"
    assert "INV-P01" in item.hit_rules
    assert item.dsi is None
    assert result.data.summary.dead_stock_capital == 500.0
    # 四段式链四要素齐全
    chain = result.reasoning[0]
    assert chain.conclusion and chain.causal_analysis and chain.risk_note
    assert any(r.rule_id == "INV-P01" for r in chain.triggered_rules)
    assert len(chain.evidence) >= 1


def test_slow_turn_high_capital_escalates():
    # DSI = 1000/(30/30)=1000 天, 资金占用=1000*200=200000 → 危险, 命中 P02/P03
    result = invoke("inventory_risk", _args([
        {"sku": "C", "on_hand": 1000, "unit_cost": 200.0, "sales_30d": 30},
    ]))
    item = result.data.items[0]
    assert item.risk_level == "危险"
    assert "INV-P02" in item.hit_rules


def test_low_dsi_is_restock_warning():
    # DSI = 5/(60/30)=2.5 天 (<15) → 预警(断货风险), 命中 INV-P04
    result = invoke("inventory_risk", _args([
        {"sku": "D", "on_hand": 5, "unit_cost": 3.0, "sales_30d": 60},
    ]))
    item = result.data.items[0]
    assert item.risk_level == "预警"
    assert "INV-P04" in item.hit_rules


def test_summary_top_risks_and_totals():
    result = invoke("inventory_risk", _args([
        {"sku": "A", "on_hand": 100, "unit_cost": 2.0, "sales_30d": 60},   # 健康
        {"sku": "B", "on_hand": 50, "unit_cost": 10.0, "sales_30d": 0},    # 危险
    ]))
    summary = result.data.summary
    assert summary.total_capital_occupied == 100 * 2.0 + 50 * 10.0
    assert "B" in summary.top_risks


def test_empty_input_is_validation_error():
    result = invoke("inventory_risk", {"items": []})
    assert result.ok is False and result.error.code == "VALIDATION"


def test_negative_on_hand_is_validation_error():
    result = invoke("inventory_risk", _args([
        {"sku": "X", "on_hand": -1, "unit_cost": 1.0, "sales_30d": 1},
    ]))
    assert result.ok is False and result.error.code == "VALIDATION"
