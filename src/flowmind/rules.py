"""声明式规则引擎：规则求值后自动产出「触发规则」与「数据证据」。

推理链的第二、三段不手写——由规则求值生成，保证多技能格式统一。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from flowmind.contracts import Evidence, RuleHit


@dataclass
class Rule:
    """一条声明式规则。

    predicate: 给定指标字典判断是否命中。
    evidence: 命中时抽取的数据证据列表。
    """
    id: str
    name: str
    expression: str  # 人类可读表达式，写入 RuleHit
    predicate: Callable[[dict], bool]
    evidence: Callable[[dict], list[Evidence]]


def evaluate_rules(rules: list[Rule], metrics: dict) -> tuple[list[RuleHit], list[Evidence]]:
    """对指标求值所有规则，收集命中的 RuleHit 及其 Evidence。"""
    hits: list[RuleHit] = []
    evidence: list[Evidence] = []
    for rule in rules:
        if rule.predicate(metrics):
            hits.append(RuleHit(rule_id=rule.id, name=rule.name, expression=rule.expression, hit=True))
            evidence.extend(rule.evidence(metrics))
    return hits, evidence
