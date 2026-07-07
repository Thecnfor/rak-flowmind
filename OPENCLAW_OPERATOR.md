# OpenClaw 操作手册：视频批量本地化技能

> **给 OpenClaw 的接入说明。读完这份文档即可独立调用，无需阅读 flowmind 源码。**

---

## 0.1 硬 SLA：**字幕一定不能残留**

**承诺**：调用 `localize_batch` 后，中文字幕必须 100% 清除，字幕区白像素 < 原视频 1%。

**如何守住（v0.3 OCR 方案，已端到端打通）**：
- 默认策略是 `ocr_erase_redraw`（OCR 定位 bbox → 擦除原中文字幕 → 用目标语言重绘）
- 这是 v0.3 唯一受支持的字幕处理策略；老的 `delogo` / `inpaint` / `overlay` / `auto` 全部弃用
- 业务理由：车企出海营销——目标观众不读中文，保留原字幕 = 视觉噪音，必须擦除并替换为目标语言
- **VL 端实现状态**（v0.3.1 起已落地）：
  - `pipeline/inpainter.py:SubtitleRemover.remove_subtitles_ocr_erase` —— pytesseract + cv2.inpaint
  - 端到端实测：95 秒竖屏视频，5 帧抽样测得**锐利文字像素削减 94%**（1153 → 68）
  - `muxer.burn_subtitles` 接管"重绘"步骤（BorderStyle=4 黄字带框）
- SDK 这边：`LocalizerConfig.remove_subtitles_strategy_default = "ocr_erase_redraw"`，策略白名单只收这一个值
- `tests/test_subtitle_clearing_sla.py` 5 个 P0 测试守住：默认策略、默认值、payload 默认值
- 任何 commit 如果让字幕残留 > 1% 或把默认策略改回老路径，测试挂掉，CI 阻止 merge

**如果你看到字幕残留**：
1. 先用 `pytest tests/test_subtitle_clearing_sla.py -v` 看哪个测试挂
2. 重新跑一次 `localize_batch`（`ocr_erase_redraw` 默认就够）
3. 如果残留明显（> 5% 锐利文字像素），可能是视频字幕位置频繁移动 → 用 `--psm 12` 调整 OCR 或改用单帧 OCR
4. 如果反复出现，可能是 `LocalizerConfig.remove_subtitles_strategy_default` 被改回 `delogo`/`inpaint`/`overlay`/`auto` —— 检查 git log

---

## 0. 首次使用：初始化用户偏好（**必做**）

在 Agent 第一次为某用户调用 `localize_*` skill 之前，**必须**先与用户对话采集偏好，写入 `flowmind.config.toml`。之后 Agent 调用 skill 时只需要传 `video_paths`，其他参数全走 config 默认。

**Agent 第一次收到"翻译视频"类指令时的处理流程**：

1. 检查是否初始化：
   ```python
   from flowmind.config import is_initialized
   if not is_initialized():
       # 进入第 2 步
   ```

2. 与用户对话采集（用户不答则用括号内默认）：
   - **目标语言**？默认 `en`（`th` / `ja` / `ko` / `es` / `fr` / `de` / `ru` 也支持）
   - **源语言**？默认 `zh`
   - **是否配音**？默认 `true`
   - **是否擦除原视频硬烧中文字幕**？默认 `true`（v0.3 起：擦除是默认路径）
   - **字幕处理策略**？默认 `ocr_erase_redraw`（OCR 定位+擦除+重绘，v0.3 唯一支持）

3. 写入配置（一条命令）：
   ```python
   from flowmind.config import init_for_user
   init_for_user(
       target_lang="th",                              # ← 步骤 2 采集到的值
       source_lang="zh",
       enable_tts=True,
       remove_subtitles=True,
       remove_subtitles_strategy="ocr_erase_redraw",
   )
   ```

之后 Agent 直接 `localize_batch({"video_paths": ["/path/to/video.mp4"]})` 即可——**所有策略类参数全走 config 默认**。

> **为什么必须**：避免每次调用 skill 都让 Agent 临时决定 enable_tts / remove_subtitles_strategy 这种细节。用户的偏好应该**固化在用户配置文件里**，不是 Agent 临时判断。

---

## 1. 接入位置

- **项目路径**：`/home/linzi/rak-flowmind`
- **MCP 入口命令**：`uv --directory /home/linzi/rak-flowmind run flowmind-mcp`
- **传输**：stdio（spawn 子进程，通过 stdin/stdout JSON-RPC 通信）
- **运行要求**：本机已装 `uv`；首次接入会自动从清华 pip 镜像拉依赖（约 30 秒）

### MCP 客户端配置（直接粘到 OpenClaw 配置）

```json
{
  "mcpServers": {
    "flowmind": {
      "command": "uv",
      "args": ["--directory", "/home/linzi/rak-flowmind", "run", "flowmind-mcp"],
      "env": {}
    }
  }
}
```

---

## 2. 可用工具一览

调用 `tools/list` 会得到以下工具。每个工具的 `description` 字段已经写明何时调它，**决策依据就是 description，不靠记忆**。

| 工具 ID | 何时调它 |
|---|---|
| `inventory_risk` | 拿到一批 SKU 的库存与销量数据，要判断哪些该补货、哪些积压 |
| `localize_batch` | 拿到一组视频文件路径（本地路径或 URL），要把它们一次性提交到 video-localizer 做字幕翻译 + 可选 TTS。**自动分批**：超过 `max_videos_per_batch` 时 skill 内部拆多次提交，Agent 无需关心 |
| `localize_status` | 已经提交过一批任务（`localize_batch` 返回了 `job_ids`），要知道每个任务现在是 queued / running / completed / failed，**以及有没有卡住**。**并发轮询**：N > 1 时线程池并发查，配置 `poll_max_concurrency` |
| `localize_cancel` | 取消一个 queued / running 的任务（DELETE） |
| `localize_download` | 拿到一个 completed 任务的产物清单（每个文件的 local_path + VL download URL），按 URL 自行 GET 取文件 |
| `localize_retry` | 重提一个失败 / 取消的任务（拿原参数 → 单条重提，返回新 task_id）。一次调用，不用自己拿 source_video |

> **不要**直接调 video-localizer 的 HTTP API（绕开 MCP 会丢四段式推理链与 trace_id）。

---

## 3. 工具详细规范

### 3.1 `localize_batch` —— 批量提交视频本地化

**何时调**：用户给了 N 个视频文件路径，要批量做语言转换。

**入参（极简）**：Agent 只需要传 `video_paths`，其他全走 config 默认（参见 §0 首次使用）。

```json
{
  "inp": {
    "video_paths": ["/path/to/video1.mp4", "/path/to/video2.mp4"]
  }
}
```

**完整入参**（需要覆盖默认值时显式传）：

```json
{
  "inp": {
    "video_paths": ["/path/to/video1.mp4", "/path/to/video2.mp4"],
    "target_lang": "th",
    "source_lang": "zh",
    "enable_tts": true,
    "remove_subtitles": true,
    "remove_subtitles_strategy": "ocr_erase_redraw",
    "chat_id": "oc_xxx"
  }
}
```

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `video_paths` | **是** | — | 视频文件路径或 http(s) URL 列表，至少 1 条；扩展名必须是 `.mp4` |
| `target_lang` | 否 | `cfg.target_lang_default`（init 时设） | 目标语言代码；支持 `en` / `th` / `ja` / `ko` / `es` / `fr` / `de` / `ru` |
| `source_lang` | 否 | `cfg.source_lang_default` | 源语言代码 |
| `enable_tts` | 否 | `cfg.tts_default`（默认 `true`） | 是否生成 TTS 配音 |
| `chat_id` | 否 | `null` | 飞书通知会话 ID；填了的话任务完成时会回调 |
| `remove_subtitles` | 否 | `cfg.remove_subtitles_default`（默认 `true`） | 是否擦除硬烧中文字幕 |
| `remove_subtitles_strategy` | 否 | `cfg.remove_subtitles_strategy_default`（默认 `ocr_erase_redraw`） | 字幕处理策略：v0.3 起**只支持** `ocr_erase_redraw`（OCR 定位+擦除+重绘）；`delogo` / `inpaint` / `overlay` / `auto` 全部弃用 |

**返回**（`content[0].text` 的 JSON）：

```json
{
  "ok": true,
  "data": {
    "batch_id": "894bd8a8",
    "job_ids": ["520da203", "5e7e2e08"],
    "total": 2,
    "submitted_count": 2,
    "rejected_count": 0,
    "cost_band": "低",
    "tts_recommended": true,
    "batch_size_warning": false,
    "remove_subtitles": true,
    "remove_subtitles_strategy": "ocr_erase_redraw"
  },
  "reasoning": [{"conclusion": "批量提交 2 个视频（拒绝 0 个），成本档位「低」，开 TTS。", ...}]
}
```

**关键字段**：
- `data.job_ids` —— **必须保存**，后续轮询全靠它
- `data.batch_size_warning: true` —— 超过单批上限（默认 100），考虑拆分提交
- `data.rejected_paths` —— 预检拒收的视频路径，看是否要单独处理

**可能的失败**：
- `error.code == "VALIDATION"` —— 入参问题（空列表、不支持的语言、非 .mp4 扩展名）
- `error.code == "INTERNAL"` —— video-localizer 不通或服务异常；先重试一次，仍失败则通知用户

---

### 3.2 `localize_status` —— 批量查询任务状态

**何时调**：已经调过 `localize_batch`、拿到 `job_ids`，要跟进进度。

**入参**：

```json
{
  "inp": {
    "task_ids": ["520da203", "5e7e2e08"],
    "stall_threshold_seconds": 600
  }
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `task_ids` | 是 | 要查询的 task_id 列表（就是 `localize_batch` 返回的 `job_ids`） |
| `stall_threshold_seconds` | 否 | 运行中超此秒数视为卡住；不填走默认 600s |

**返回**：

```json
{
  "ok": true,
  "data": {
    "tasks": [
      {
        "task_id": "520da203",
        "status": "completed",
        "output_dir": "/output/520da203",
        "duration_seconds": 85.0,
        "is_terminal": true,
        "is_stalled": false
      },
      {
        "task_id": "5e7e2e08",
        "status": "failed",
        "error": "No module named 'whisperx'",
        "is_terminal": true
      }
    ],
    "completed": 1,
    "failed": 1,
    "running": 0,
    "queued": 0,
    "stalled": 0,
    "all_terminal": true
  },
  "reasoning": [{"triggered_rules": [{"rule_id": "STAL-04", "name": "全部终态"}], ...}]
}
```

**关键字段**：
- `data.all_terminal` —— 是否全部进入终态；是 → 停止轮询
- `data.stalled > 0` —— 有任务卡住，需要查 worker 日志或重提
- `tasks[i].status` —— `queued` / `running` / `retrying` / `completed` / `failed` / `cancelled` / `not_found`
- `tasks[i].error` —— 仅 failed 任务有值，是 video-localizer 抛的原始错误

**触发哪些规则 → 怎么决策**：

| 规则 | 触发条件 | 你应当采取的行动 |
|---|---|---|
| `STAL-01` 运行卡住 | 有任务 running 超 threshold（retrying **不计入**，VL 在自动重试是已知失败模式） | 继续轮询一轮；若仍卡住，建议查 worker |
| `STAL-02` 存在失败 | failed > 0 | 看 `tasks[i].error`；若是依赖缺失（`whisperx` 等）通知运维；若是文件问题单独重提 |
| `STAL-03` 存在重试中 | retrying > 0 | 正常情况，继续轮询 |
| `STAL-04` 全部终态 | `all_terminal == true` | 停止轮询，汇总报告 |

---

### 3.3 `localize_cancel` —— 取消任务

**何时调**：用户明确要求取消某个任务，或发现任务跑错（比如跑成了泰语但用户要英语）。

**入参**：
```json
{ "inp": { "task_id": "520da203" } }
```

**返回**：
```json
{
  "ok": true,
  "data": {
    "task_id": "520da203",
    "cancelled": true,
    "message": "Task 520da203 cancelled"
  }
}
```

**可能的失败**：
- `error.code == "INTERNAL"`，`category == "video"` —— 任务不存在（404）或已结束（400 "Cannot cancel task (not found or already finished)"）。已结束的任务不必取消。

---

### 3.4 `localize_download` —— 获取任务产物清单与下载链接

**何时调**：任务状态是 `completed`，需要拿到配音视频 / 字幕文件。

**入参**：
```json
{ "inp": { "task_id": "520da203" } }
```

**返回**：
```json
{
  "ok": true,
  "data": {
    "task_id": "520da203",
    "status": "completed",
    "files": [
      {
        "filename": "output_dub_raw.mp4",
        "local_path": "/tmp/vl_output/520da203/output_dub_raw.mp4",
        "url": "http://localhost:8000/api/v1/tasks/520da203/download?file=output_dub_raw.mp4"
      },
      {
        "filename": "trans.srt",
        "local_path": "/tmp/vl_output/520da203/trans.srt",
        "url": "http://localhost:8000/api/v1/tasks/520da203/download?file=trans.srt"
      }
    ],
    "degraded": false
  }
}
```

**关键字段**：
- `data.files[i].url` —— 按此 URL 用你自己的 HTTP 工具 GET 拉文件（MCP 不传二进制，避免破坏 JSON 信封）
- `data.degraded == true` —— VL 报 completed 但 `files` 为空。**这是「假完成」信号**（通常是输入视频没语音 → ASR 无内容）。让用户知道配音/字幕产物实际不存在。

**可能的失败**：
- `error.code == "INTERNAL"`，`category == "video"` —— 任务未完成（status 不是 completed）。等终态再调。
- 任务不存在（404）→ `category == "video"`。

---

### 3.5 `localize_retry` —— 重提失败任务

**何时调**：用户想重新跑一个失败 / 取消的任务（不绕开 MCP）。

**入参**：
```json
{ "inp": { "task_id": "520da203" } }
```

**返回**：
```json
{
  "ok": true,
  "data": {
    "original_task_id": "520da203",
    "new_task_id": "a8ec66af",
    "original_status": "failed",
    "source_video": "/path/to/video.mp4",
    "target_lang": "th",
    "enable_tts": true,
    "remove_subtitles": true
  }
}
```

**关键字段**：
- `data.new_task_id` —— **必须保存**，加入下一轮轮询
- `data.source_video` 等参数沿用原 task，不用 Agent 拿

**可能的失败**：
- `error.code == "INTERNAL"`，`category == "video"`
  - 任务不存在（404）
  - 任务状态是 completed 但没 `source_video`（VL 假完成场景）—— 此时**不能重提**，让用户换视频或检查 VL
- `category == "transient"` —— VL 5xx，可重试
- `category == "environment"` —— VL 连接失败，先修 VL

---

### 3.6 `inventory_risk` —— 库存风险分析（参考技能）

业务侧已上线技能的范本，与视频本地化无直接关系；只在用户问库存风险时调。

---

## 3.7 调试经验：VL 的 `task_id` vs `job_id`

历史版本 VL 在内部对 `task_id`（pipeline 跑完后填）和 `job_id`（提交时的主键）保留两套；外部查询时按哪个来用是个坑。**v0.2 起 VL 的 `find_job` 同时支持两 ID 查询**（`897fb87` commit 起），所以 `localize_status` / `localize_download` / `localize_cancel` / `localize_retry` 拿到任何一个 ID 都能命中。

调试建议：
- `localize_batch` 返回的 `data.job_ids[]` 是「主键」，拿来用最稳
- `localize_status` 返回的 `tasks[i].task_id` 跟 `tasks[i].job_id` 在 v0.2+ 应该是同一个值（pipeline 完成后 `task_id = job_id` 兜底）；如果看到两者不同，说明用的是 v0.2 之前的 VL，需要升级
- 如果 `localize_download` 报 `error.category == "video"`（任务不存在），先看是不是 VL 重启过——VL 内存队列不持久化，重启后旧 task_id 不存在；解决方案：让用户重新提交

业务侧已上线技能的范本，与视频本地化无直接关系；只在用户问库存风险时调。

---

## 4. 业务场景剧本：飞书送来一批视频

> 用户在飞书发了 600-700 个中文视频切片，要本地化到泰语/英语（可选 TTS）。
> 你（OpenClaw）的工作流：

### Step 1：解析输入

从飞书事件取出视频路径列表（可能含本地路径或 URL）。

### Step 2：提交（自动分批，无需手动 chunk）

`localize_batch` 内部按 `max_videos_per_batch`（默认 100）自动 chunk，600+ 条一次调用搞定。返回的 `data.batch_count` 告诉你拆了几批，`data.batch_ids` 是所有批号，`data.job_ids` 是合并后的所有任务 ID。

```python
# 伪代码，仅示意
result = call_tool("localize_batch", {"inp": {
    "video_paths": all_video_paths,   # 600+ 条直接传
    "target_lang": "th",
    "source_lang": "zh",
    # enable_tts 留空走 config.tts_default（默认 True）
    "remove_subtitles": True,
    # v0.3：策略固定 ocr_erase_redraw（OCR 定位+擦除+重绘）；不用按视频格式再选
    "remove_subtitles_strategy": "ocr_erase_redraw",
}})
if result.ok:
    log(f"拆 {result.data.batch_count} 批，合并 {len(result.data.job_ids)} 个 job_id")
    all_job_ids = result.data.job_ids
else:
    # 中途失败：error.details.successful_batch_ids 列出已成功的批
    log(f"提交失败：{result.error.message}")
    if result.error.details:
        log(f"已成功批：{result.error.details['successful_batch_ids']}")
```

### Step 3：轮询（自动并发）

`localize_status` 内部按 `poll_max_concurrency`（默认 8）线程池并发查，无需 Agent 并发。每 10-30 秒一轮：

```python
while not all_terminal:
    sleep(15)
    result = call_tool("localize_status", {"inp": {"task_ids": all_job_ids}})
    if result.ok:
        all_terminal = result.data.all_terminal
        if result.data.stalled > 0:
            notify_user(f"⚠️ {result.data.stalled} 个任务卡住")
        if result.data.failed > 0:
            log_failures(result.data.tasks)
```

### Step 4：失败处理（重提 / 取产物 / 取消）

```python
for task in result.data.tasks:
    if task.status == "failed":
        # 先看 error 字段判断根因：
        #   error 含 "No module named" / "whisperx" → 环境问题，通知运维，**不要**重提
        #   error 是单条视频本身 → 用 localize_retry 一键重提
        if is_env_error(task.error):
            notify_ops(f"video-localizer 缺依赖: {task.error}")
        else:
            retry_result = call_tool("localize_retry", {"inp": {"task_id": task.task_id}})
            if retry_result.ok:
                all_job_ids.append(retry_result.data.new_task_id)  # 加入轮询

# 取产物（completed 任务）：
for task in result.data.tasks:
    if task.status == "completed":
        dl = call_tool("localize_download", {"inp": {"task_id": task.task_id}})
        if dl.ok:
            for f in dl.data.files:
                if f.filename.endswith(".mp4"):
                    # 按 url 自己 GET 取视频文件
                    download_via_http(f.url, save_to=...)
        elif dl.data.degraded:  # 即便 result.ok，degraded=True 表示 VL 假完成
            log(f"⚠️ {task.task_id} 报 completed 但无产物（VL 假完成，可能是视频无语音）")

# 取消还在跑的（用户主动放弃或跑错语言）：
if user_cancel_requested:
    for tid in still_running_task_ids:
        call_tool("localize_cancel", {"inp": {"task_id": tid}})
```

### Step 5：出业务报告

完成后给用户的最终报告里至少含：

```
批量本地化完成：
- 总提交：600
- 成功：N（X%）
- 失败：M（列出 task_id 与原因）
- 平均时长：Y 秒
- 产物目录：每个 completed 任务的 output_dir
```

---

## 5. 错误处理总则

所有工具返回都有结构化 `SkillResult` 信封：

- `ok == true` → 业务成功，读 `data`
- `ok == false` → 业务失败，读 `error.code` 与 `error.category`
  - `VALIDATION` —— 入参错了，修参数重试（`category="unknown"`）
  - `INTERNAL` —— 服务挂了或代码崩了；按 `category` 分流：
    - `category="environment"` —— **修环境**（HF/DNS/连接失败）。**不要重试**，先修 VL 配置（开外网 / 换本地模型 / 改 PATH）。
    - `category="video"` —— **修入参**（视频不存在 / 格式不支持）。
    - `category="transient"` —— **可重试一次**（5xx 抖动），`retriable=true`。
    - `category="unknown"` —— 看 `message`，多半是 VL bug，通知运维。
  - `NOT_FOUND` —— 调错工具名了，看 `tools/list`（`category="unknown"`）

`localize_batch` 提交前会先探 `/health`（fail-fast）：VL 整个挂掉时立刻返回 `INTERNAL+environment`，**不会**返回假 `ok=true`，省你白白拿 `job_ids` 后才发现跑不动。

**`trace_id` 必须贯穿**同一次业务调用的所有步骤。调下一个工具时不需要手动传 `trace_id`（MCP server 端会自动关联），但如果你要在自己的日志里串起来，可以从每次返回的 `trace.trace_id` 字段读出来。

---

## 6. 不要做的事

- ❌ 不要直接 `requests.post("http://localhost:8000/api/v1/batch", ...)` —— 绕开 MCP 会丢掉推理链与 trace_id
- ❌ 不要修改 `flowmind.config.toml` 里的支持语言列表 —— 改完只对你自己生效，其他用户连不上
- ❌ 不要把 `localize_batch` 当成同步调用 —— 提交完立即返回 `job_ids`，要轮询要看 `localize_status`
- ❌ 不要无限轮询 —— `all_terminal == true` 就停；或设个最大轮询时间（如 30 分钟）兜底

---

## 7. 验证接入是否成功

跑一次最小烟雾测试（仅需 1 个真实视频文件）：

```
1. tools/list → 应返回 3 个工具（inventory_risk / localize_batch / localize_status）
2. tools/call localize_batch → 用一个真实 .mp4 文件路径入参
3. 检查返回的 data.batch_id 和 job_ids 非空、ok=true
4. tools/call localize_status → 用刚拿到的 job_id
5. 检查返回的 data.tasks[0].task_id 与你传入的一致
```

五步全过 = 接入成功，可以跑业务流。

---

## 8. 关键路径速查

| 用途 | 路径 |
|---|---|
| 项目根 | `/home/linzi/rak-flowmind` |
| MCP 入口命令 | `uv --directory /home/linzi/rak-flowmind run flowmind-mcp` |
| 三个技能源文件 | `src/flowmind/skills/{inventory_risk,localize_batch,localize_status}.py` |
| video-localizer 服务 | `http://localhost:8000`（OpenClaw 同机部署时） |
| video-localizer 源码 | `/home/linzi/.openclaw/workspace/Dev区/video-localizer` |

---

**这份文档就是 OpenClaw 与 flowmind 对接的完整契约。改任何工具的入参/出参，请同步更新本文档。**
---

## 9. v0.3.2 Agent 对话剧本（可交互式配置）

**业务场景**：客户给龙虾发视频，但**没说要翻译成什么语言 / 配不配 TTS / 字幕多大**——这些**必须问**。

### 9.1 Agent 完整对话流（伪代码）

```
[客户上传视频到飞书]
  ↓
龙虾: "🎬 收到视频，已识别为 95 秒中文视频。开始处理前需要确认几个选项："
  ↓
┌─────────────────────────────────────────────────────┐
│  1. 目标语言？                                        │
│     • 🇺🇸 英语（默认）                              │
│     • 🇹🇭 泰语（东南亚重点市场）                     │
│     • 🇯🇵 日语                                        │
│     • 🇰🇷 韩语                                        │
│     • 🇪🇸 西语 / 🇫🇷 法语 / 🇩🇪 德语 / 🇷🇺 俄语       │
└─────────────────────────────────────────────────────┘
[客户选] "泰语"
  ↓
┌─────────────────────────────────────────────────────┐
│  2. 是否生成配音？(TTS)                              │
│     • ✅ 是（推荐：海外观众更易接受）                 │
│     • ❌ 否（只换字幕，保留原声）                     │
└─────────────────────────────────────────────────────┘
[客户选] "是"
  ↓
┌─────────────────────────────────────────────────────┐
│  3. 配音音色偏好？                                    │
│     • 👩 默认（按语种自动选最佳女声）                │
│     • 👨 男声（更正式）                              │
└─────────────────────────────────────────────────────┘
[客户选] "默认"
  ↓
┌─────────────────────────────────────────────────────┐
│  4. 字幕大小？（横屏视频默认 22 号；竖屏自动缩）     │
│     • 小（18号，简洁）                                │
│     • 中（22号，默认）                               │
│     • 大（28号，易读）                                │
└─────────────────────────────────────────────────────┘
[客户选] "中"
  ↓
龙虾: "✅ 配置确认：中文 → 泰语，带泰语女声配音，标准字幕。"
        "预计 5-10 分钟处理，产物会发回此对话。"
  ↓
[Agent 调用 init_for_user(target_lang='th', enable_tts=True, tts_voice=None,
                          subtitle_font_size=22)]
  ↓
[Agent 调用 invoke('localize_batch', {video_paths: [...], target_lang: 'th', enable_tts: True})]
  ↓
[产物回传]
```

### 9.2 不需要询问的"通用默认"（直接用 SDK 默认）

| 字段 | 默认 | 何时可以省问 |
|---|---|---|
| `source_lang` | `zh` | 用户没说源语言时**必须问**（避免猜错） |
| `remove_subtitles` | `true` | 通用最佳实践，可省问 |
| `remove_subtitles_strategy` | `ocr_erase_redraw` | v0.3.2 唯一受支持策略，可省问 |
| `subtitle_position` | `bottom_safe` | 防遮画面最佳实践，可省问 |
| `chat_id` | `null` | 客户主动提供才填 |

### 9.3 SDK 端 init_for_user（v0.3.2 完整签名）

```python
from flowmind.config import init_for_user

# 客户只选了"泰语 + 配音" → 其它走默认
init_for_user(target_lang="th", enable_tts=True)

# 客户还选了"男声 + 字幕大"
init_for_user(
    target_lang="th",
    enable_tts=True,
    tts_voice="th-TH-NiwatNeural",   # 男声
    subtitle_font_size=28,           # 大字幕
)
```

**写完之后**：所有后续 `invoke("localize_batch", ...)` 调用都自动应用这套偏好，**不用每次传**。

### 9.4 Agent 错误处理剧本

| 情况 | Agent 怎么回应 |
|---|---|
| `error.code = VALIDATION`（语言不支持）| "该语种暂不支持，已为您列出可用语种。" |
| `error.code = INTERNAL` + `category=environment` | "video-localizer 服务暂未启动，请联系管理员。" |
| `error.code = INTERNAL` + `category=video` | "视频文件有问题，请重新上传或换格式。" |
| `error.code = INTERNAL` + `category=transient` | "服务繁忙，10 秒后自动重试。" |
| Job 卡在 queued/running > 10 分钟 | "处理时间较长，请耐心等待。需要取消请回复「取消」。" |
