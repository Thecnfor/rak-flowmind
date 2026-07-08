---
name: flowmind-test-skill
description: End-to-end exercise any FlowMind `@skill` function the way a real Agent would — read the source, plan realistic scenarios (happy path / edge cases / error paths), call `invoke()`, assert against the actual schema, and emit a JSON + Markdown report. Use this whenever the user wants to "测试 skill X", "验证 skill Y 能不能跑", "跑一下所有 skill", "测试 localize_batch", "检查 skill 端到端", or asks "this skill 真的能用吗" about any of the 8 registered FlowMind skills. Triggers on "测一下", "试一下", "test skill", "exercise", "verify", "smoke test", or any phrasing implying "exercise a skill end-to-end and show me whether it works".
---

# flowmind-test-skill

把「读一个 skill → 像 Agent 一样实际调它 → 输出一份可读报告」做成可重复流程。

## 何时用

- 用户：「测试 inventory_risk」「跑一下 localize_batch」「验证 feishu_kb_search」「测全部 8 个 skill」「这个 skill 真能用吗」
- 自己改了某个 skill 源码后想回归
- 加新 skill 后想确认端到端 OK

## 何时不用

- 用户只想**读源码**——直接 Read，不要触发
- 用户想要**单元测试覆盖率**——那是 `uv run pytest tests/`，不是这个 skill 的活
- 用户想**改 skill 实现**——那是 `flowmind-add-skill` / 直接改
- 非 FlowMind 项目（这个 skill 强绑定 `flowmind.discover()` / `invoke()` 协议）

## 工作流（5 步）

### Step 1：确定目标 skill 集

从用户输入解析：
- 具体 skill_id（`inventory_risk` / `localize_batch` / ...）→ 单测
- "all" / "全部" / "8 个" → 测所有 8 个
- 没指定 → 跑全部 8 个

可用的 8 个 skill（用 `flowmind.discover()` 实时拿，不要硬编码）：

```python
from flowmind import discover
[skill["id"] for skill in discover()]
```

### Step 2：拿 schema + 字段路径（**避免猜字段名**）

```python
from flowmind import discover, field_names

info = discover("inventory_risk")           # 含 input_schema + output_schema + description
fields = field_names("inventory_risk")      # 嵌套字段路径字典
# 例如 fields["data.summary"] = ['total_capital_occupied', 'level_counts', ...]
```

读 `src/flowmind/skills/<id>.py` 第一段 docstring 和 `@skill(...)` 装饰器提取**业务语义**（不是字段名——字段名已经能从 discover 拿到了）。

### Step 3：规划场景

按 skill 类型分两类，并且**两类有不同的错误返回契约**——这是关键差异，写错 `expect_ok` 整个 driver 就废：

**A. 纯计算类（无外部依赖）**：`inventory_risk` / `feishu_kb_search` / `marketing_image_gen`
- happy path：典型真实输入
- boundary：极小 / 极大 / 边界值（empty / 单条 / 大量）
- 错误路径：`invoke()` 在 `**ValidationError**` 时返回 `r.ok=False + r.error.code="VALIDATION"`；在 **未知 skill_id** 时返回 `r.ok=False + r.error.code="NOT_FOUND"`
- 输出校验：`r.ok`、`r.data.<关键字段>`、`r.reasoning` 长度、`r.metrics.latency_ms >= 0`、`r.trace.trace_id` 非空
- 错误断言：`r.error.code` + `r.error.details["errors"]` 含具体字段错

**B. HTTP 依赖类**：`localize_batch` / `localize_status` / `localize_cancel` / `localize_download` / `localize_retry`
- ⚠️ **契约特殊**：这些 skill 在技能体内 catch + 分类后返回 **degraded SkillOutput**（不是 raise），所以 `r.ok=True` + `r.metrics.degraded=True` + `r.data.failure_category=<cat>`。**不要断言 `r.ok is False`！**
- 必装 backend mock：替换 skill 模块的 `requests.{get,post,delete}` 为可控制的 fake
- 健康检查场景：mock /health 返 200 / 503 / ConnectionError
- happy path：mock 返 200 + 合理 JSON → `r.ok=True, degraded=False, data.batch_id/job_ids/cancelled/files/new_task_id 等正常字段`
- 错误分类场景：mock 返 5xx / 4xx / ConnectionError → `r.ok=True, degraded=True, data.failure_category ∈ {transient / video / environment / unknown}, data.retriable`（transient=True, 其他=False）
- 边界：空 task_ids / 不存在的 task_id / partial success（多任务中部分 404）
- 入参 validation 失败（不是 HTTP 错）：走 `r.ok=False + r.error.code="VALIDATION"` 路径（和 A 类一样）

#### 错误返回契约速查表

| 场景 | r.ok | r.error.code | r.metrics.degraded | r.data.failure_category |
|---|---|---|---|---|
| inventory_risk 入参缺 items | False | "VALIDATION" | False | None |
| inventory_risk 调成功 | True | None | False | None |
| localize_batch /health 503 | **True** | None | **True** | "transient" |
| localize_batch POST 503 | **True** | None | **True** | "transient" |
| localize_batch POST 404 | **True** | None | **True** | "video" |
| localize_batch POST ConnectionError | **True** | None | **True** | "environment" |
| localize_batch 视频扩展名不合法 | False | "VALIDATION" | False | None |
| 未知 skill_id | False | "NOT_FOUND" | False | None |

写 driver 时先把每个 scenario 的 `expect_ok` / `expect_degraded` / `expect_category` 都填好，再用 `discover()` 的 `output_schema.properties` 校一遍字段名。

### Step 4：执行

#### 4.1 创建工作目录

```bash
mkdir -p .test-runs/<skill_id>-<timestamp>
cd .test-runs/<skill_id>-<timestamp>
```

#### 4.2 写 driver 脚本 `run_<skill_id>.py`

通用模板（按需替换 `SKILL_ID` 和后端 mock）：

```python
"""flowmind-test-skill driver for <skill_id>."""
import json
from pathlib import Path

import flowmind.skills  # noqa: F401  触发注册
from flowmind import discover, field_names, invoke


SCENARIOS = [
    {
        "name": "happy_path_typical",
        "args": {...},
        "expect_ok": True,                 # 见「错误返回契约速查表」
        "expect_degraded": False,
        "expect_category": None,
        "assertions": [
            lambda r: r.ok is True,
            lambda r: r.data.<key_field> is not None,  # 用 discover() 拿字段名
            lambda r: r.metrics.latency_ms >= 0,
            lambda r: bool(r.trace.trace_id),
        ],
    },
    {
        "name": "error_<scenario>",
        "args": {...},
        "expect_ok": True,                 # localize_* 是 True + degraded
        "expect_degraded": True,
        "expect_category": "transient",
        "assertions": [
            lambda r: r.metrics.degraded is True,
            lambda r: r.data.failure_category == "transient",
            lambda r: r.data.retriable is True,
        ],
    },
    # 视场景补充
]


def main():
    schema_info = discover("<skill_id>")
    fields = field_names("<skill_id>")
    results = []
    for sc in SCENARIOS:
        sc.get("setup", lambda: None)()
        try:
            r = invoke("<skill_id>", sc["args"])
            passed = all(a(r) for a in sc["assertions"])
            ok_match = (r.ok == sc["expect_ok"])
            degraded_match = (r.metrics.degraded == sc.get("expect_degraded", False))
            cat_match = sc.get("expect_category") is None or getattr(r.data, "failure_category", None) == sc["expect_category"]
            results.append({
                "scenario": sc["name"],
                "passed": passed and ok_match and degraded_match and cat_match,
                "ok_match": ok_match, "degraded_match": degraded_match, "cat_match": cat_match,
            })
        except Exception as exc:
            results.append({"scenario": sc["name"], "passed": False, "error": str(exc)})
    # 写 report.json + report.md ...


if __name__ == "__main__":
    main()
```

**HTTP 依赖类必须先 mock**：

```python
import flowmind.skills.localize_batch as lb_mod

def install_fake_backend(health="ok", post_status=200, post_json=None, post_side_effect=None):
    def fake_get(url, timeout=None, **_kw):
        class _R: ...
        return _R()
    def fake_post(url, json=None, timeout=None, **_kw):
        if post_side_effect: raise post_side_effect
        class _R: ...
        return _R()
    lb_mod.requests.get = fake_get
    lb_mod.requests.post = fake_post
```

#### 4.3 跑 driver

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python run_<skill_id>.py
```

### Step 5：生成报告

写到 `.test-runs/<skill_id>-<timestamp>/`：

**`report.json`**（机器可读 / CI 用）：

```json
{
  "skill_id": "inventory_risk",
  "timestamp": "2026-07-08T...",
  "schema": {"input": {...}, "output": {...}, "fields": {...}},
  "scenarios": [
    {
      "name": "happy_path_typical",
      "passed": true,
      "ok": true,
      "latency_ms": 0.42,
      "data_preview": "...",
      "assertions_total": 4,
      "assertions_passed": 4
    }
  ],
  "summary": {
    "total": 8,
    "passed": 7,
    "failed": 1,
    "pass_rate": 0.875
  }
}
```

**`report.md`**（人类可读）：

```markdown
# flowmind-test-skill report: inventory_risk

**生成时间**: 2026-07-08 ...
**测试通过率**: 7/8 (87.5%)

## Schema 速览
- 输入字段: items (list, required)
- 输出字段: data.items[].sku / on_hand / ..., data.summary.level_counts, data.currency

## 场景结果

| # | 场景 | 结果 | 延迟 |
|---|---|---|---|
| 1 | happy_path_typical | ✅ PASS | 0.42ms |
| 2 | boundary_low_dsi | ✅ PASS | 0.38ms |
| ... |
| 8 | error_invalid_items | ❌ FAIL | - |

## 失败详情
### error_invalid_items
- 期望: r.metrics.degraded == True
- 实际: r.ok == True（应该走 validation 错误路径但实际通过了）
- 输入: `{"items": []}`
```

## 输出控制台摘要

跑完打印一行：

```
[flowmind-test-skill] inventory_risk: 7/8 passed (87.5%) → .test-runs/inventory_risk-20260708-xxx/report.md
```

如果通过率 < 100%，**显眼地用红色 / 加粗提示**，让用户知道有问题要看。

## 重要原则

1. **永远先用 `discover()` / `field_names()` 拿 schema**，不要凭印象写断言——避免「猜 r.data.band 还是 r.data.summary.level_counts」这类典型坑。
2. **HTTP 依赖的 skill 必装 mock**，否则会被真实 localhost:8000 撞死。
3. **断言要分两类**：「存在性 / 类型」是硬性，「值合理性」是软性。报告里分开统计。
4. **scenario 名字要描述性**（`error_404_video_not_found` 而不是 `test_5`），让人一眼看懂。
5. **trace_id 永远要非空**——这是项目铁律，违反就是契约 bug。
6. **mock 装在 skill 模块的 `requests` 命名空间**（`lb_mod.requests.post = fake`），不要 monkey-patch 全局 `requests`——会污染其他测试。

## 不做的事

- ❌ 不改 skill 源码（这是测试 skill，不是 `flowmind-add-skill`）
- ❌ 不跑 `uv run pytest`（那是单元测试，本 skill 是端到端 Agent 视角）
- ❌ 不创建 SkillResult 之外的输出格式（JSON + md 两份够了）
- ❌ 不测 MCP server（那是 `flowmind-mcp-setup` 的活）