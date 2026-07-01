"""规则引擎测试：命中规则与证据的收集。"""
from flowmind.rules import Rule, evaluate_rules
from flowmind.contracts import Evidence


def _rules():
    return [
        Rule(
            id="R-HI", name="过高", expression="x > 10",
            predicate=lambda m: m["x"] > 10,
            evidence=lambda m: [Evidence(metric="x", value=m["x"], threshold=10, comparison=">")],
        ),
        Rule(
            id="R-LO", name="过低", expression="x < 0",
            predicate=lambda m: m["x"] < 0,
            evidence=lambda m: [Evidence(metric="x", value=m["x"], threshold=0, comparison="<")],
        ),
    ]

def test_only_hit_rules_collected():
    hits, evidence = evaluate_rules(_rules(), {"x": 42})
    assert [h.rule_id for h in hits] == ["R-HI"]
    assert all(h.hit for h in hits)
    assert evidence[0].metric == "x" and evidence[0].value == 42

def test_no_hits_returns_empty():
    hits, evidence = evaluate_rules(_rules(), {"x": 5})
    assert hits == [] and evidence == []
