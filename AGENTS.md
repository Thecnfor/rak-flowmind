# AGENTS.md —— Claude Code / AI Agent 开发指南

> 给**使用 Claude Code（或类似 AI 编程助手）参与本仓库开发**的协作者看。
> 这份文档假设你熟悉 Claude Code 但不熟悉本项目代码结构。
> 与 `CLAUDE.md`（项目不变量 + 架构）互补；本文专注**开发工作流**。

## 30 秒上手

```bash
make install         # 装依赖
make test            # 跑 71 个测试（必须全绿）
make demo            # 跑 3 个技能 demo（看实际输出）
make help            # 看所有可用命令
```

如果遇到任何概念不清楚，先看本文件对应章节，再问。

## 仓库速览

```
src/flowmind/
├── contracts.py       # 对外契约（SkillResult / ReasoningChain / ...）── 改这里 = 改对外 API
├── rules.py           # 规则求值器（四段式链的「触发规则/数据证据」自动产出）
├── config.py          # FlowmindConfig + 各技能 Config ── 新技能的可调参数都加这里
├── skill.py           # @skill 装饰器 + invoke() 入口 ── 融合点
├── manifest.py        # build_manifest() ── Agent 视角的能力清单
├── server.py          # FastMCP v1 薄壳 ── 把 _REGISTRY 暴露成 MCP tool
└── skills/
    ├── __init__.py    # import 各技能触发 @skill 注册（加新技能就追加一行）
    ├── inventory_risk.py         # 参考：纯确定性
    ├── marketing_image_gen.py    # 参考：确定性 mock 后端
    └── feishu_kb_search.py       # 参考：BM25+TF-IDF，引入外部依赖
tests/                 # 71 个测试，每个技能一个文件
examples/              # 3 个可跑 demo + MCP 配置模板（无需 MCP 客户端）
docs/                  # 设计文档 / 集成指南 / 技能开发配方
Makefile               # dev 命令入口
scripts/setup.sh       # 一键 setup（依赖 + 测试 + demo + 配置）
```

## 典型任务与工作流

### 任务 1：修一个 bug

1. `make test` 重现失败（如果有现成测试覆盖）
2. 否则在 `tests/<skill>_test.py` 加一个失败用例（TDD 红）
3. 修源码 → 测试转绿
4. `make check`（lint + test）再 commit
5. 提交格式 `<type>: <中文描述>`，type ∈ `feat/fix/docs/refactor/test/chore`

### 任务 2：加一个新技能

**最小路径**（详细配方见 `docs/skill-authoring-guide.md`）：

1. 在 `src/flowmind/skills/<name>.py` 写 `@skill` 函数，遵循**现有技能模板**（优先复制 `inventory_risk.py` —— 最简）
2. 在 `src/flowmind/skills/__init__.py` 末尾追加 `from flowmind.skills import <name>  # noqa: F401`
3. 若有可调参数：在 `src/flowmind/config.py` 加一个 `XxxConfig` 类 + 纳入 `FlowmindConfig`
4. 在 `tests/test_<name>.py` 写测试，**优先通过 `invoke("<id>", args)` 端到端断言**（不要直接调函数）
5. 在 `examples/<name>_demo.py` 加 demo（沿用三段式：happy / 默认 / 错误）
6. `make check` 全绿 → commit

**铁律**：
- ❌ 不改 `server.py` / `contracts.py` / `manifest.py` / `skill.py`（除非改对外契约）
- ❌ 不留 `# TODO` 给下游开发者（可调项走 config + 通用默认）
- ❌ 不吞异常（任何失败必须走 `SkillResult(ok=False, error=...)` 或 `degraded=True`）

### 任务 3：理解一段陌生代码

1. 用 `LSP` 工具查定义（goToDefinition / hover）
2. 看 `CLAUDE.md`「架构」段对每个文件的角色说明
3. 看 `tests/test_<file>.py` —— 测试是行为的最佳文档
4. 跑 `make demo` 或 `examples/*_demo.py` 看实际输出

### 任务 4：升级某个依赖

```bash
uv add <pkg>~=<new-version>    # 改 pyproject.toml + uv.lock + 重装
make test                       # 验证不破坏
make lint                       # 验证类型/风格
```

**不要手改 `pyproject.toml` 加依赖后忘了 `uv sync` 重新锁 uv.lock**。我刚在合并 PR #2 时踩过 —— `git status` 永远检一下 lock 文件是不是脏。

### 任务 5：合并一个 PR（maintainer 视角）

1. `gh pr view <N>` 看改动 + CI
2. `gh pr view <N> --json files` 看共享文件（`config.py` / `skills/__init__.py`）冲突风险
3. `gh pr diff <N>` 看实际改动
4. **没有 CI 的项目**（本仓库当前）：本地 `git fetch origin pull/<N>/head:pr-<N>` → 切到分支跑 `make check` → 本地合并（`git merge --no-ff`）→ 推送
5. 共享文件冲突：保留**双方新增**，import 按字母序

## 调试技巧

### 失败信号 → 检查方向

| 信号 | 看哪里 |
|---|---|
| `ok=False, error.code=NOT_FOUND` | `invoke()` 入口 / `_REGISTRY` / 是否漏注册 |
| `ok=False, error.code=VALIDATION` | 技能入参 BaseModel 的 Field 约束 |
| `ok=False, error.code=INTERNAL` | 技能函数内部异常 → 看 traceback（`error.details`） |
| `degraded=True` | 技能自己判定降级（非失败）→ 看 `degradation_reason` |
| MCP 工具列表没出现 | `_make_tool` 的 `__annotations__` 注入没生效 / server 启动失败 |
| 入参 schema 多一层 `inp` | FastMCP v1 的固有行为，升 v2 可去 |

### 单步追踪

```bash
# 跑单个测试 + 详细输出
make test-one T=tests/test_inventory_risk.py::test_xxx

# 加断点（任意测试文件）
import pdb; pdb.set_trace()

# 看真实 trace_id 是否贯穿
uv run python -c "
import flowmind.skills
from flowmind.skill import invoke
r = invoke('inventory_risk', {'items': [{'sku':'A','on_hand':10,'unit_cost':1,'sales_30d':1}]})
print(r.trace.trace_id, r.error, r.metrics.latency_ms)
"
```

### MCP 端到端调试

```bash
# 起一个 stdio MCP server，前台跑
make mcp-launch

# 另开终端，用 MCP 客户端连
uv run python /tmp/probe_mcp.py    # 见 agent-integration.md 里的 probe 脚本
```

## 千万别做（Anti-patterns）

| 行为 | 为什么错 |
|---|---|
| 在 `server.py` 加新 tool 注册代码 | 违反"加技能不动 server"不变量 |
| 修改 `SkillResult` 信封字段 | 对外契约变更，所有 Agent 都要适配 |
| 写代码 TODO 留给用户 | 违反"不留 TODO 给下游"约定；可调项走 config |
| 在技能函数里 `try/except: pass` | 违反"错误永不静默"铁律 |
| 测试不通过 `invoke()` 端到端断言 | 跳过 envelope 层等于跳过了 trace/latency/error 处理 |
| 跳过 `make lint` 直接 commit | ruff 检查会卡 PR |
| 把 `flowmind.config.toml` 提交进 git | 它是 gitignored 的用户私有配置 |

## 提交前 Checklist

- [ ] `make check`（lint + test）全绿
- [ ] 若是新技能：测试用 `invoke("<id>", args)`、demo 三段式齐备
- [ ] 提交信息 `<type>: <中文描述>`
- [ ] 若改了 `pyproject.toml`：确认 `uv.lock` 已同步并一起提交
- [ ] 若改了 `config.py` / `skills/__init__.py`：留意 merge conflict hotspot

## 给 Claude Code 的额外提示

- **优先用 LSP** 查定义 / 重构（rename / go-to-impl / find-refs），比 grep 准
- **改架构前先读 `CLAUDE.md`** 「关键约定」段 —— 那里有不变量
- **大改动进 plan mode** 让用户先看方案再下手
- **改完跑 `make demo`** —— 三个 demo 跑通 = 三个技能都没被破坏（最快冒烟测试）
- **`@skill` 重复 id** 会抛 `ValueError`，加新技能前 `grep -r "id=\"" src/flowmind/skills/`

## 🤖 第一次拿到这个项目（FRESH AGENT）

如果你刚被用户部署到这个 repo（用户给了 GitHub 链接或 zip）：

**不要立刻跑命令**。**先读 README.md 顶部的 `🤖 如果你是一个 AI Agent 第一次读到这个文件` 段** —— 那里有完整的部署协议（4 步：自我介绍 → 对话采集 → 执行 → 验证 → 交付）。

简版：
1. 用一句话告诉用户你要做什么
2. 通过对话问 4 件事（Agent 平台 / 项目类型 / 是否 init config / 是否装 MCP）
3. 用 `flowmind.interactive.run_interactive_init(ask_fn=...)` 让 SDK 自己引导用户回答 9 个偏好问题
4. 跑 `uv sync --extra dev` + `pytest` + `examples/*_demo.py` 验证
5. 给用户交付摘要（哪些工具可用、下一步怎么走）