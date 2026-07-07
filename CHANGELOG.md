# CHANGELOG

按 commit 时间倒序记录所有演进。每个版本列出 **改了什么 / 为什么 / 怎么用**。

格式参考 [Keep a Changelog](https://keepachangelog.com/)，但简化为 commit 级粒度（仓库用 git log 作为完整历史）。

---

## v0.3.1 — VL 端 `ocr_erase_redraw` 真接通

**为什么**：`b93c619` 在 SDK 这边把默认策略改成 `ocr_erase_redraw`，但实际探测发现：
- VL 的 `BatchTaskRequest` 之前**根本没有 `remove_subtitles_strategy` 字段**（schema 过时）
- 即使有，VL 端 `engine.py:176-177` 的 ocr_erase_redraw 分支是**占位**，实现是 inpaint 别名
- `pipeline/inpainter.py` 源码被删，只剩 .pyc 字节码
- 策略字段在 `routes.py → manager._run_job → engine.run` 三处**全部断链**

**改了什么（VL 仓库）**：
- `pipeline/inpainter.py` —— 从 .pyc 还原骨架 + 新加 `remove_subtitles_ocr_erase(video_path, output_path, lang)`
  - 抽 5 帧做 OCR 多帧投票得稳定 bbox
  - OCR 限定到视频底部 65-95%（避免水印/UI 误识别）
  - pytesseract `--psm 11` + confidence ≥ 30 过滤
  - bbox 面积 > 40% 帧面积视为噪声丢弃
  - 全片用同一 bbox 做 cv2.inpaint（INPAINT_TELEA，半径 3px）
  - OCR 全失败回退到 fast_remove_subtitles
- `pipeline/engine.py` —— `run()` 加 `remove_subtitles_strategy` 参数；占位分支替换为真实 `remove_subtitles_ocr_erase` 调用；delogo/inpaint/overlay 保留为 backward compat
- `task_queue/manager.py` —— `_run_job()` 把 `job.remove_subtitles_strategy` 透传给 `engine.run()`
- `api/routes.py` —— 3 个 endpoint（create_task / create_batch / create_multi_batch）补传 strategy
- `api/schemas.py` —— 字段默认从 `"delogo"` 改成 `"ocr_erase_redraw"`（与 SDK 默认对齐）

**改了什么（SDK 仓库，本仓）**：
- `OPENCLAW_OPERATOR.md` §0.1 硬 SLA 段：标注 "v0.3 OCR 方案，已端到端打通" + 实测数据

**端到端实测**（95 秒竖屏视频，五菱缤果 S 营销素材）：
| 时间 | 原始锐利文字像素 | OCR+erase 后 | 削减率 |
|---|---:|---:|---:|
| 10s | 18 | 0 | 100% |
| 30s | 24 | 7 | 71% |
| 50s | 42 | 10 | 76% |
| 70s | 20 | 0 | 100% |
| 90s | 1049 | 51 | 95% |
| **总** | **1153** | **68** | **94%** |

（Laplacian + 高亮阈值过滤锐利文字像素）

**部署依赖**：ffenv 需要装 `tesseract` + `pytesseract` + `chi_sim`/`eng`/`tha` 语言包（conda-forge）

**已知限制**：
- OCR 多帧 bbox 缓存策略对字幕位置稳定的视频效果最好；字幕垂直移动场景会有残留
- OCR 单帧 ~10-15s（5 帧抽样 ~1 分钟），占整个视频处理时间的 30%
- ASR 的 large-v3 模型需要联网下载，本地无外网时切到 base 模型（已缓存）

---

## [Unreleased] — 当前工作区

### v0.3.2 — 可交互式配置 + 字幕/TTS 优化

**为什么**：v0.3.1 完成后用户提了三个优化方向：(1) Agent 通过对话问客户偏好（语种 / 音色 / 字号）；(2) TTS 配音更灵动、字幕不遮画面；(3) 输出命名规范化。

**改了什么（SDK 端）**：
- `LocalizerConfig` 新增 4 个 v0.3.2 字段：
  - `tts_voice: str | None`（None = 按目标语言自动选最佳）
  - `subtitle_font_size: int = 22`（横屏；竖屏自动 ×0.7）
  - `subtitle_position: str = "bottom_safe"`（"bottom" / "bottom_safe"）
  - `output_filename_suffix: str = "sub"`（命名后缀）
- `init_for_user()` 扩展：支持上述所有参数；Agent 通过对话采集后可一键设全套偏好
- `save_config()` 修复：剔除 None 字段（TOML 不支持 None）
- `tests/test_config.py` 加 3 个 v0.3.2 测试（基础 / 全字段定制 / 默认值）
- `OPENCLAW_OPERATOR.md` §9 新增「Agent 对话剧本」（伪代码 + 错误处理）

**改了什么（VL 端）**：
- `config/settings.py` 新增 `LOCALE_PRESETS` 表（en/zh/th/ja/es），每种语言预置 voice / font_size / margin_v / max_chars_per_line
- `config/settings.py` 新增 `get_locale_preset(lang)` 函数
- `SubtitleConfig` 新增 `margin_v_horizontal / margin_v_vertical / max_chars_per_line_*/outline_width/back_color`
- `pipeline/tts.py` 新增 `resolve_voice(target_lang, override)` 静态方法
- `pipeline/engine.py` TTS 步骤改用 `TTSEngine.resolve_voice(tgt_lang, ...)`
- `pipeline/textwrap.py`（新文件）：`wrap_subtitle_text()` 按语种智能换行 + `safe_output_filename()` 命名规范 + `estimate_subtitle_duration_ms()` 时长估算
- `pipeline/subtitle.py` `generate_all()` 接 `target_lang` 参数，写入前对 translation/source 智能换行
- `pipeline/muxer.py`：
  - `_get_font_name(target_lang)` 按目标语言查 fc-list（不再硬查中文）
  - 加泰/日/韩字体候选 fallback 链
  - `burn_subtitles` 按视频方向（横/竖屏）选 MarginV
  - 加半透明背景框（BorderStyle=4 + BackColour）

**业务效果**：
- 客户上传视频不指定语种 → Agent 通过对话问清楚
- TTS 配音每种语言用最适合的音色（如泰语用 PremwadeeNeural 而非通用）
- 字幕底部固定 + 半透明黑底 → 在复杂背景上也清晰可读
- 横屏 vs 竖屏自动适配 margin_v，不遮画面
- 输出文件名带时间戳 + 语种 + 策略，可追溯

---

## v0.3 — 推翻 v0.3 WIP：OCR 定位 + 擦除 + 重绘字幕

**为什么**：前一段 WIP 把默认改成双语字幕（保留中文 + 加翻译），方向反了 —— 车企出海营销的目标观众**不读中文**，保留原字幕=视觉噪音。重新对齐：**擦除是默认路径**，新策略用 OCR 定位精确擦除 + 用目标语言重绘，比老的 delogo 黑条方案对画质更友好。

**改了什么**：

### B4 推翻 v0.3 双语方案，重新做"擦除+重绘"
- `LocalizerConfig.remove_subtitles_default: True`（**恢复**）
- `LocalizerConfig.remove_subtitles_strategy_default: "ocr_erase_redraw"`（v0.3 新策略，唯一受支持）
- `LocalizerInput.remove_subtitles` / `remove_subtitles_strategy` 字段**恢复**（之前 WIP 误删）
- 策略白名单从 `("inpaint", "overlay", "auto")` 收窄到 `("ocr_erase_redraw",)` —— `delogo` / `inpaint` / `overlay` / `auto` 全部拒收
- `init_for_user()` 默认 strategy 参数从 `"delogo"` 改为 `"ocr_erase_redraw"`

### 测试同步
- `test_subtitle_clearing_sla.py`：默认策略断言改 `ocr_erase_redraw`；新增 `test_default_remove_subtitles_is_true`（业务硬要求：默认必须擦除）
- `test_localize_batch.py`：`test_remove_subtitles_strategy_in_payload` 等改用 `ocr_erase_redraw`；非法 strategy 测试用例改用 `"delogo"`（确保被拒）
- `test_remove_subtitles_default_true_in_payload` 保留原意（v0.3 默认仍是 True）
- SLA 集成测试改名 `test_ocr_erase_redraw_subtitle_clearing_sla_real`
- 修 ruff 告警：去掉未使用的 `cv2 = pytest.importorskip(...)` 赋值

### 文档同步
- `OPENCLAW_OPERATOR.md` §0.1 硬 SLA 段：默认策略说明改为 ocr_erase_redraw + v0.3 业务理由
- `OPENCLAW_OPERATOR.md` §0 初始化剧本：示例 strategy 改 ocr_erase_redraw
- `OPENCLAW_OPERATOR.md` §3.1 入参表 + 示例 payload：strategy 全部改 ocr_erase_redraw；旧策略标"v0.3 起全部弃用"
- `OPENCLAW_OPERATOR.md` §4 Step 2 伪代码：去掉"按视频格式选 overlay/auto"注释，v0.3 不再需要这种判断

### 业务语义说明
- v0.3 起 `ocr_erase_redraw` 是**唯一受支持**的字幕处理策略
- 老的 `delogo`（drawbox 黑条）/`inpaint`（OpenCV 修复）/ `overlay`（上方覆盖）/ `auto`（逐帧决策）全部不再被 SDK 接受
- 业务理由：车企出海营销的目标观众（东南亚/南美/中东）不读中文，保留原字幕=视觉噪音；必须擦除并替换为目标语言

---

## 2026-07-03 — `3f8a566` feat(P1 retry): 加 localize_retry skill — Agent 不再走两步

**为什么**：之前 P1 提交时跳过了 retry（理由是"让 Agent 走 status→batch 两步更可控"），但那其实是过度工程——多 1 次 MCP 调用 + Agent 自己写兜底（VL 假完成时 status 拿不到 source_video）。Skill 的价值就是封装这些细节。

**改了什么**：
- `src/flowmind/skills/localize_retry.py`（新增）—— 内部 GET /tasks/{id} 拿原参数 + POST /tasks 单条重提
- `tests/test_localize_retry.py`（新增 7 个测试）—— 注册 / happy path / 原 task 不存在 / 原 task 无 source_video / submit 失败分类 / 推理链
- `OPENCLAW_OPERATOR.md`：
  - §2 工具表加 `localize_retry`
  - §3.5 新增 retry 规范
  - §4 Step 2/3/4 重写，反映「自动分批」「自动并发」「retry/download/cancel 三件套处理失败」

---

## 2026-07-03 — `d54810a` docs: 更新 OPENCLAW_OPERATOR.md — 反映 P0/P1 新增（分批/并发/cancel/download）

**为什么**：P0/P1 改了技能行为，文档必须同步，否则 Agent 不知道有自动分批 / 并发 / cancel / download。

**改了什么**：
- §2 工具一览表加 `localize_cancel` / `localize_download`
- §3.3 / §3.4 新增 cancel / download 详细规范
- §3 章节顺延（原 §3.3 inventory_risk → §3.5）

---

## 2026-07-03 — `efed374` feat(P0+P1): 自动分批 + 并发轮询 + cancel/download 三个新 skill

**为什么**：
1. 用户反馈 OpenClaw 接进来跑大批量时本地要自己 `chunk(paths, 100)`，违反「Agent 不绕 MCP」原则
2. `localize_status` 串行查 600+ task_ids 慢到不可用
3. 失败 / 取消 / 取产物三个高频操作无 skill 暴露

**改了什么**：

### P0a 自动分批
- `LocalizerReport` 加 `batch_ids: list[str]` + `batch_count: int`（保留 `batch_id` 兼容旧字段）
- 超过 `max_videos_per_batch` 时按上限 chunk 成多次 POST，合并 `job_ids`
- 单批失败：`_ChunkFailedError` 携带 `.details.successful_batch_ids`，`invoke()` 沿 `__cause__` 链分类
- `skill.py`：`invoke()` 新增 `exc.category` / `exc.details` 透传

### P0b 并发轮询
- `task_ids` 数 ≤ 1 串行（无线程开销）；> 1 → `ThreadPoolExecutor`，max_workers = min(N, `poll_max_concurrency`)
- 性能验证：5 task × 0.05s 从 0.25s 降到 < 0.15s

### P1 cancel + download
- `localize_cancel`：薄包装 `DELETE /tasks/{id}`，4xx → video / 5xx → transient
- `localize_download`：列产物 + VL download URL（**不传二进制**，保留 JSON 信封）；completed 但 outputs 空 → `degraded=true`（VL 假完成信号）
- retry 暂不暴露（VL 无原生 endpoint），后由 `3f8a566` 补上

**测试**：+21 → 全 113 → 后 120 通过。

---

## 2026-07-03 — `aace816` fix: 失败分类 + fail-fast + tts_default 接通，让 Agent 看到真根因

**为什么**：用户反馈"配音没配、字幕没搞好"，实地端到端跑了一遍发现：
1. 根因不在 skill——是 video-localizer 默认 large-v3 模型 + 本机无外网，HF 下载失败 retry 35+ 次后整体 failed
2. 但 skill 只透传裸 error string（"An error happened while trying to locate the files on the Hub..."），Agent 看不出是环境问题，傻等 30 分钟
3. `LocalizerConfig.tts_default` 字段定义了但**从未被读取**（虚假配置契约）
4. `localize_status` stalled 判定把 retrying 也算进去（误判）

**改了什么**：

### B1 失败分类
- `SkillError` 新增 `category: environment / video / transient / unknown`
- `_classify_exception`：按异常类型 + message 关键词归类
- `invoke()` 兜底时填 category，Agent 一眼分流

### B2 fail-fast
- `localize_batch` submit 前先 `GET /health`（默认 2s 超时，`LocalizerConfig.health_timeout` 可配）
- VL 不通立刻抛，被 `invoke()` 归类为 environment/transient，省一次 submit 往返
- 解决：VL 挂时 Agent 拿到假 `ok=true` 的 job_ids → 傻轮询 30 分钟的坑

### B3 tts_default 真接通 + stalled 判定优化
- `LocalizerInput.enable_tts` 默认从 `True` 改成 `None`（用户未传标志）
- skill 体内 `effective_tts = inp.enable_tts if inp.enable_tts is not None else cfg.tts_default`
- `localize_status` stalled 判定：retrying 不算 stalled（VL 自动重试是已知失败模式）

**OPENCLAW_OPERATOR.md** 更新 §3.2 规则表 + §5 错误处理。

**测试**：+22 → 全 93 通过。

---

## 2026-07-03 — `a0c7e44` feat: 接入视频本地化首批技能 + OpenClaw/任意 Agent MCP 接入手册与脚本

**改了什么**：
- `src/flowmind/skills/localize_batch.py`（新增）—— 批量提交视频本地化到 VL，含预检 + 三档成本分级 + 四段式推理链
- `src/flowmind/skills/localize_status.py`（新增）—— 批量查询任务状态，含终态 / 卡住判定 + 规则触发链
- `src/flowmind/config.py`：新增 `LocalizerConfig`
- `src/flowmind/server.py`：MCP tool description 改用技能 docstring
- `OPENCLAW_OPERATOR.md`（新增 313 行）—— 给 OpenClaw 的完整接入手册
- `demo_agent.py` / `simulate_openclaw.py` / `verify_any_agent.py`（新增）—— MCP 客户端脚本
- `uv.toml`（新增）—— 清华 pip 镜像
- `tests/test_localize_batch.py`（23 个）+ `test_localize_status.py`（12 个）—— TDD

**测试**：+35 → 全 71 通过。

---

## 2026-07-02 — `4b116f9` feat: FlowMind Skill SDK 基座（#1）

**改了什么**：SDK 基座第一版，包含契约层 / 配置层 / @skill 装饰器 / invoke / MCP server / manifest / 参考技能 `inventory_risk`。通过 PR #1 合入 main。

---

## 设计文档（参考用）

- `docs/superpowers/specs/flowmind-skill-sdk-design.md` —— 契约先行的设计依据
- `docs/superpowers/plans/flowmind-skill-sdk.md` —— 10 任务 TDD 拆解
## v0.3.2 — 可交互式配置 + TTS 灵动化 + 字幕优化

**为什么**：OpenClaw Agent 通过对话采集用户偏好（语种 / 音色 / 字幕大小），
需要 init_for_user 一键写入 config；视频后端存在字幕擦不干净、烧位置不对齐、
ASR 检测错位等问题需统一优化。

**改了什么**：
- `src/flowmind/config.py` —— `init_for_user()` 新增 `tts_voice` / `subtitle_font_size` / `subtitle_position` / `output_filename_suffix` 字段
- `src/flowmind/contracts.py` —— 新增 `ErrorCode` 枚举（NOT_FOUND / VALIDATION / INTERNAL）
- `src/flowmind/skill.py` —— 三处硬编码字符串替换为 `ErrorCode` 引用
- `src/flowmind/vl_client.py` —— 新模块：VL 后端 HTTP 客户端封装（带 4xx/5xx 错误分类 + health check）
  - **不替换原有 localize_* 技能**（之前尝试全替换破坏 20 个测试），供未来增量采用
- `tests/test_localize_control.py` —— `test_cancel_404_returns_not_found_error`
  → 改回 `test_cancel_404_returns_internal_video_error`（匹配实际 `raise_for_status` 行为）

**验证**：
- 128 passed + 1 skipped
- ruff check: All checks passed!
- 端到端 OpenClaw 调用 `localize_batch` 走完整流程：5:28 出 84s 干净泰文配音视频

**部署前待办**（建议在 demo 前完成）：
- [ ] 5 个 localize_* 技能增量迁移到 VLClient（一次一个，配套改测试）
- [ ] VL 端 ASR 模型 medium→base 切换逻辑（无外网环境用 base）
- [ ] burn_subtitles 截断 bug 已修（muxer 加 -t 输入视频时长）

## v0.3.1 — VL 端 `ocr_erase_redraw` 真接通
