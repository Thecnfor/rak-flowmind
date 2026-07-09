# feishu_kb_search 检索准确度修复 + 话题外防御

**日期**: 2026-07-09
**作者**: nnn
**状态**: 已批准 — 进入实施

## 背景

PR #2 (`feat: 新增飞书知识库 FAQ 检索技能 feishu_kb_search`) 已合并,但用户反馈**检索不准确、机器人回复多余话题**。根因有两个:

1. **Seed 语料太小**:`feishu_kb_seed.json` 仅 8 条样例,BM25 在 8 文档上无法形成稳定词频分布,长尾问题几乎必召回错误。
2. **无 scope 防御**:任何输入都强制返回 Top-K 答案,无置信度兜底,LLM 上层会"强行套用"完全不相关的 FAQ。

用户已提供完整企业 FAQ:`C:\Users\nnn\Desktop\FAQ\FAQ问答库\` 8 份 docx,共 ~200 条 Q&A。

## 目标

1. 把 seed 从 8 条扩到 ~200 条,显著提升召回准确度。
2. 增加 hard-gate:Top-1 置信度低于阈值时,返回 `top_k=[]` + `degraded=True`,Agent 收到后只能输出"暂未收录,请转人工"。
3. 严格保证回答**完全来自 KB**:LLM 不再"整合",只透传 Top-1 的 `answer` 原文。

## 设计

### 数据流(已通过用户确认)

```
用户问题 → 清洗 → 意图分类(扩词典) → 加载 FAQ(扩 seed) → BM25+TF-IDF 双路召回
→ RRF 融合 → 类别加权 rerank → ★ hard-gate → 四段式链 → SkillOutput
```

### 改动清单

| 文件 | 改动 | 行数估计 |
|---|---|---|
| `src/flowmind/skills/feishu_kb.py` | 加 hard-gate + 改 `agent_reply_hint` 强调"原文透传"+ 扩 4 类关键词 | ~50 |
| `src/flowmind/skills/feishu_kb_seed.json` | 从 8 条扩到 ~200 条(由 docx 解析产出) | +~600 |
| `src/flowmind/config.py` | 新增 `FeishuKbConfig.min_top1_score: float = 0.015` | +3 |
| `scripts/build_seed_from_docx.py` | 新增:一次性解析 8 份 docx 为 seed JSON | ~150 |
| `tests/test_feishu_kb.py` | 新增 3 个测试 | +40 |

### Hard-Gate 语义

```python
if not top_k or top_k[0].final_score < cfg.min_top1_score:
    return SkillOutput(
        data=FeishuKbReport(top_k=[], ...),
        reasoning=[_build_chain(..., top_k=[])],
        confidence=0.0,
        sample_size=len(faqs),
        degraded=True,
        degradation_reason=f"Top-1 final_score {top_k[0].final_score:.4f} < 阈值 {cfg.min_top1_score}",
    )
```

阈值默认 `0.015`,由 `FeishuKbConfig.min_top1_score` 暴露,用户可通过 `flowmind.config.toml` 覆盖。

### Agent 提示词调整(严格忠于 KB)

| 状态 | agent_reply_hint 内容 |
|---|---|
| 命中 | "请直接引用 Top 1 的 answer 原文(不要改写、不要补充、不要推测),末尾附『来源:FAQ-编号 · 飞书链接』" |
| 未命中 | "暂未收录此类问题,请联系人工客服或换个问法。" |

### 词典扩展(基于 8 份 docx 真实问题高频词)

仅追加,不替换现有词典。例如:
- 用车指导: + "应急启动"、"机械钥匙"、"迎宾"、"腿托"、"腿托舒展"、"暖风"、"空气净化"
- 充电补能: + "充电桩"、"随车充电枪"、"交流桩"、"直流桩"、"保温"、"智能保温"、"充电时长"
- 故障排查: + "胎压复位"、"处理措施"、"点亮条件"、"报警灯"、"充电枪按钮卡滞"
- 产品咨询: + "零重力座椅"、"吸顶屏"、"车机"、"语音助手"、"迎宾模式"、"按摩"

## 文档/脚本/测试

### `scripts/build_seed_from_docx.py` 解析策略

8 份 docx 用了 3 种结构,按文件定制:

| docx | 结构 | 解析规则 |
|---|---|---|
| 五菱、宝骏 CVT 变速器 | "N、问:... 答:..." | 标准正则 |
| 五菱、宝骏新能源汽车 | 编号问 + 多段答 + 长说明(无问号) | 标准正则 + 段落合并 |
| 五菱凯捷 | "N.问:..." + 子弹点列表 | 标准正则 + 跳过纯说明段 |
| 五菱宏光 MINI | "N、问:... 答:..." | 标准正则 |
| GAMEBOY 充电 | "N、问:... 答:1).xx 2).yy" | 标准正则 + 多 part 合并到 answer |
| 华境 S | "N.问:... 答:..." | 标准正则 |
| 吉林智成指示灯 | "N、...灯的点亮条件...处理措施..." | **无问号**:重写为"X 灯的点亮条件是什么？处理措施？" |
| 影响冬季续航 | "一.问:... 答:..." | 标准正则(1 个) |

每条产出 `{id, category, question, answer, source_url}`:
- `id`: `FAQ-{seq:04d}` 沿用种子文件命名风格
- `category`: 由文件名+内容启发式推断(`故障排查` / `充电补能` / `用车指导` / `产品咨询`)
- `source_url`: `feishu://kb/<doc_basename>#<seq>`

### 新增测试(共 3 个)

| 测试 | 断言 |
|---|---|
| `test_seed_size_at_least_100` | 加载默认 seed 后,`len(faqs) >= 100` |
| `test_faq_self_match` | 取 seed 中一条 FAQ 的 `question` 直接查询,Top-1 应命中自己(`faq_id` 相同或 answer 包含原文核心短语) |
| `test_offtopic_returns_degraded` | 查询"今天北京天气怎么样" → `result.ok is True` 且 `result.data.top_k == []` 且 `result.degraded is True` |

## 边界

- 不改 BM25 / TF-IDF / RRF / ReasoningChain / SkillOutput / server.py / contracts.py
- 不引入 LLM / embedding / 新依赖
- 不删除现有 8 条 seed(只是被 ~200 条新 seed 替换;新 seed 仍含原 8 条以保留向后兼容)
- 不在 skill 层做 NLG — Agent 层负责"原文透传"

## 提交格式

按 CLAUDE.md:
- spec commit: `docs: feishu_kb_search 检索准确度修复 + 话题外防御设计`
- code commit: `feat: feishu_kb_search 扩 seed(~200) + hard-gate 防话题外`
- follow-up: `test: feishu_kb_search 新增 seed/hard-gate/FAQ 自命中测试`

## 风险与回滚

- **风险 1**: 新 seed JSON 解析失败 → build script 用 `json.JSONDecodeError` 兜底 + 测试覆盖
- **风险 2**: 阈值 0.015 误判(把正常查询判为话题外) → 默认值从 50 个真实查询的 final_score 分布中位数 -1σ 校准
- **回滚**: 单 commit revert,seed JSON 改回 8 条版本