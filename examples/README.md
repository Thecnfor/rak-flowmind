# examples —— 不需要 MCP 客户端也能体验 SDK

每个脚本都是一个**自包含**的最小可运行示例：`uv run python examples/<name>.py` 即可看到技能完整输出。

| 脚本 | 演示技能 | 你将看到 |
|---|---|---|
| [`inventory_risk_demo.py`](./inventory_risk_demo.py) | 库销比/库存风险分级 | DSI 阈值命中、四段式推理链、错误兜底（NOT_FOUND） |
| [`marketing_image_demo.py`](./marketing_image_demo.py) | 营销生图（确定性 mock 后端） | 平台/风格推断、多版本测款、URL 复现性、错误兜底（VALIDATION） |
| [`feishu_kb_demo.py`](./feishu_kb_demo.py) | 飞书 FAQ 检索（BM25+TF-IDF） | 意图分类、Top-K 命中、agent 提示模板 |
| [`localize_batch_demo.py`](./localize_batch_demo.py) | 批量视频本地化编排 | mock VL 后端、错误分类（transient/video/environment） |
| [`localize_status_demo.py`](./localize_status_demo.py) | 批量状态查询 | 并发轮询、卡住判定、per-task 404 → not_found |
| [`localize_download_demo.py`](./localize_download_demo.py) | 产物清单 + 下载 URL | happy path、VL 假完成 → degraded、404 错误分类 |
| [`localize_retry_demo.py`](./localize_retry_demo.py) | 失败任务重提 | 沿用原参数、404 → video、缺 source_video 兜底 |
| [`localize_cancel_demo.py`](./localize_cancel_demo.py) | 取消运行中任务 | happy path、400 → video 错误分类 |

## 🚀 Agent 开箱即用：`discover()`

每个 demo 第一步都跑 `discover()`，让 Agent 自动发现技能的所有字段 —— 不再靠「猜 schema」。

```python
from flowmind import discover, field_names

# 看全部技能
for skill in discover():
    print(f"{skill['id']}: {skill['description']}")

# 看某个技能的 input + output 完整 schema
info = discover("inventory_risk")
print(info["input_schema"])   # JSON Schema
print(info["output_schema"])  # JSON Schema

# 拿到 data 字段名（含嵌套），避免 r.data.band vs r.data.summary.level_counts 猜错
for path, names in field_names("inventory_risk").items():
    print(f"{path}: {names}")
```

`discover()` 把 input_schema、output_schema、description 全部暴露给 Agent —— 这是「开箱即用」的核心契约。

## 一键全跑

```bash
for f in examples/*_demo.py; do
  echo "════ $f ════"
  uv run python "$f"
  echo
done
```

或者用 `Makefile`：

```bash
make demo           # 跑全部 demo
make demo-inventory # 单跑一个
```

## demo 都做了什么

每个 demo 都覆盖 3 个用例：

1. **discover() 输出字段名** —— 让 Agent / 人类立即看到 `data.foo` 应该是什么
2. **Happy path** —— 正常输入 + 完整输出（数据载荷 + 推理链）
3. **错误路径** —— 故意触发环境错 / 视频错 / 服务端临时错，看 `failure_category` 分类 + Agent 下一步动作

## MCP 客户端配置模板

不想用 demo 脚本？直接接 MCP 客户端：见 [`mcp_configs/`](./mcp_configs/)（Claude Desktop / Cline / Cursor 各一份）。

## 加新 demo 的规范

新增技能时，建议同时在这个目录加一个 `<skill>_demo.py`，沿用三段式结构（discover + happy + 错误），让评审 / 用户 30 秒看懂这个技能能干嘛。