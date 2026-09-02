# Marp Presentation Orchestrator v0.6.3

这是一个面向 **Codex CLI + Marp** 的课程课件与学术报告生产框架。v0.6.3 以已交付的 v0.6.2 为基线，只修复 current＋next 关键路径流水线；任务级固定运行配置、token 可观测性以及机械 review/release 控制面均保持不变。

正式耐久产物始终是：

```text
canonical Marp Markdown
        ↓
@marp-team/marp-cli 4.5.0
        ↓
PDF
```

浏览器 HTML 仅用于 author/release 的机械布局检查，检查后立即删除；它不进入 reviewer bundle 或 deliverables。

## v0.6.3 增量：修复 current＋next 流水线

- 当前课件进入 `review_requested`、`reviewing`、`author_revision` 或 `release_ready` 后，下一份课件的 authoring lane 不再被关闭。
- `all` 模式在当前课件冻结进入审核时自动激活并延迟创建最早的下一 authoring 课件；仍然最多只有一个 next lane。
- `each`、首次 `pilot` 暂停以及显式的 next-WIP 零限制继续禁止提前启动下一份课件。
- 自动重平衡与 `mpres production activate` 共享同一状态判定，避免再次出现策略与命令行为分叉。


## 1. v0.6.1 增量

- 新建任务级 `TASK-RUNTIME-PROFILE.yaml`，默认 planner/author/reviewer 分别为 `sol high`、`sol medium`、`sol low`。
- 允许用户在确认前进行更细角色、review 通道或 presentation 配置；确认后全程只读。
- 删除项目级 Codex 与 agent 配置中的具体 model/effort 选择。
- token collector 成为 production 初始化硬门。
- 缺失 token 值保持 `null`，汇总增加 known subtotal、unknown count 和 coverage，绝不把 unavailable 显示成零。

## 1.1 v0.6.0 的主要变化

- 增加四种 production profile，不再让成熟课件迁移重复走绿地六阶段。
- `legacy_migration` 固定使用三阶段，但仍默认每节课分配一名固定 lesson author。
- planner 可审批一份 batch plan，由程序展开各 unit assignment；这种 assignment 仍算 planner 编写。
- 只有顶层 `TASK.md` 必须由主 planner（main agent）亲自撰写或修订，其余 planner 工作均可委派给 delegated planner。
- unit workspace 延迟创建，调度只维护“当前课件＋至多一个下一课件”的关键路径窗口。
- reviewer 只在整份 deck 冻结后创建；review 聚合与 release 均由无模型运行时的 Python control-plane job 完成。
- lesson author handoff 后即可关闭；五通道审核后由一个 deck revision author 修订整份课件。
- 五名 reviewer 仍分别完整阅读整份冻结课件，不采用抽样或只看改动页。
- Marp CLI 精确锁定为 4.5.0，并在 production 前运行三页 smoke test。
- 确认是 workflow-engine 技术 bug 后仍禁止任务内热修；必须进入 task policy amendment，并把引擎重构视为独立工作。
- `UNIT-DELTA.yaml`、`INTERACTION-RECORD.yaml`、context packets 等成为 canonical records，减少重复证据文档。

## 2. 模型与 planner 委派政策

每个任务在初始化时生成：

```text
tasks/<slug>/TASK-RUNTIME-PROFILE.yaml
```

默认值是 planner `gpt-5.6-sol/high`、author `gpt-5.6-sol/medium`、reviewer `gpt-5.6-sol/low`。用户可以在确认 `TASK.md` 前按具体角色、review 通道或 presentation 修改；agent 不得自行选择，也不得在任务运行时动态升级、降级、替换或重写。`mpres task present` 展示其规范化内容，`mpres task confirm` 把完整配置存入 canonical task state；不增加除 `TASK.md` 以外的 hash。

`MODEL-POLICY.yaml` 只描述项目支持的配置模式，不再保存具体任务的运行时选择；`.codex/config.toml` 和各 agent TOML 也不再写死 model/effort。

主 planner 独占的工作只有：

```text
write_or_revise top-level TASK.md
```

以下工作均可交给其它 planner：production profile 选择、batch plan、assignment 审批、policy audit、监督、异常诊断和 amendment 准备。planner 的语义责任不会因为委派而消失。

### Batch assignment

planner 可写一份：

```text
tasks/<slug>/planning/BATCH-ASSIGNMENT-PLAN.yaml
```

批准后，程序把共同约束和 unit-specific delta 展开为每个 unit 的 executable assignment，并记录：

```yaml
written_by: planner-via-approved-batch
semantic_owner: planner
```

程序只能机械展开已批准语义，不能补写新的教学要求或削弱约束。每个 unit 仍只有一份 assignment；禁止 stage-specific assignment。

## 3. Production profiles

| mode | stage profile | 用途 |
|---|---|---|
| `greenfield_full` | 课程六阶段或完整报告阶段 | 难度较高、从零创作 |
| `greenfield_compact` | 紧凑四阶段 | 普通从零创作 |
| `legacy_migration` | 三阶段 migration profile | 已有成熟课件迁移 |
| `targeted_revision` | 两阶段 revision profile | 有界局部修改 |

### Migration profile

`legacy_migration` 完全跳过绿地六阶段：

1. `m01_baseline_audit`：建立旧课件基线和 canonical `UNIT-DELTA.yaml`；
2. `m02_delta_design_patch`：保留合格内容，只实现必要差量；
3. `m03_integration_semantic_check`：检查连续性、数学、认知入口、时长、互动题、编号和 Marp 集成。

迁移任务仍默认一节课一个固定 lesson author。author 完成 context packet 和 durable handoff 后即可关闭，不必保留到 review 结束。

## 4. 关键路径与延迟初始化

v0.6.0 的调度顺序是：

```text
完成当前 review / revision / release
        ↓
完成当前 presentation
        ↓
启动下一个 ready presentation
        ↓
只准备更远期元数据，不启动 model worker
```

约束包括：

- unit 初始为 `uninitialized`；只有 batch plan 已批准且 unit 入队时才创建 workspace；
- 同时最多一份 presentation 处于 review/revision/release；
- 当前课件之外，最多允许一个下一课件 active authoring；
- 冻结前不生成 reviewer assignment 或 reviewer workspace；
- review 聚合前不生成 deck revision author；
- `release_ready` 前不注册 mechanical release job；
- 禁止 prospective hold thread；
- `delivery_mode: all` 只表示不逐份等待用户，不表示可以提前展开全部工作。

## 5. 角色图

```text
main/delegated planner
        ↓ approved batch semantics
author coordinator
        ↓
fixed lesson authors (one per unit)
        ↓ durable unit handoffs + context packets
integrated frozen deck
        ↓
five isolated full-deck reviewers
        ↓ atomic aggregation
one deck revision author
        ↓ complete response + revised deck
Python mechanical release job
        ↓
Marp source + PDF
```

### Author coordinator

负责 deck map、当前关键路径监督、lesson 集成、author gates、`AUTHOR-CONTEXT-PACKET.yaml` 和 freeze。冻结交接后可关闭，不负责 post-review revision。

### Lesson author

负责一个固定 content unit，在一份 assignment 和一个连续 thread 下完成 profile-selected stages。handoff 后可关闭；review 后不会重新唤醒。

### Reviewers

五个通道：

- `language`
- `domain_accuracy`
- `layout`
- `pedagogy`
- `audience`

五名 reviewer 都完整阅读同一份冻结 deck，互相隔离，只做这一轮审核。reviewer 不查看后续修订。

### Deck revision author

读取完整冻结稿、五通道 findings、`REVIEW-PLAN.yaml`、`AUTHOR-CONTEXT-PACKET.yaml` 和 `REVISION-ROUTING.yaml`，统一修订整份 deck。所有 finding 都路由给它，而不是返回原 lesson authors。

### Mechanical release job

只在 `release_ready` 后启动，执行机械门、构建和打包；不判断 finding 是否在语义上“修好”，不改教学内容。

## 6. Canonical records

v0.6.0 避免多份可编辑文档重复表达同一事实：

| 文件 | 唯一职责 |
|---|---|
| `PRODUCTION-PROFILE.yaml` | 模式、stage graph、review scope |
| `BATCH-ASSIGNMENT-PLAN.yaml` | planner 批次语义 |
| `PRESENTATION-WORK-PLAN.yaml` | 关键路径与 launch window |
| `UNIT-DELTA.yaml` | keep/modify/move/delete/add 决策 |
| `UNIT-CONTEXT-PACKET.yaml` | 单元作者的紧凑上下文 |
| `INTERACTION-RECORD.yaml` | 唯一可编辑的 MCQ/互动记录 |
| `AUTHOR-CONTEXT-PACKET.yaml` | 审后整稿修订上下文 |
| `REVIEW-PLAN.yaml` | 冻结稿与五通道完整阅读范围 |
| `REVISION-ROUTING.yaml` | finding 的确定性定位 |
| `TOOLCHAIN-LOCK.yaml` | 精确工具版本 |
| `ENGINE-INCIDENT.yaml` | 技术缺陷与 amendment 要求 |
| `MILESTONE-CHECKPOINT.json` | 稀疏里程碑状态 |

旧格式报告如 MCQ audit 或 interaction manifest 只能由 canonical record 机械生成，不可作为另一份独立真源。

## 7. 课程规则

课程以顺序编号的“第几节课”为 content unit，不按教材章节直接拆分。每个 unit 使用两个不同字段：

- `global_meeting_number`：全课程课次；
- `deck_local_ordinal`：该 deck 内的顺序。

每节课必须包含 2–3 组诊断性选择题 prompt/answer，分别放在不同概念转折处；报告免除该配额。名义时长定义自然停止点，默认可准备约 1.5 倍材料，把延伸例题置于 core path 之后。

## 8. 来源、资产与视觉边界

worker 只能读取：

```text
tasks/<slug>/downloads/text/
```

原 PDF 位于 restricted area，只允许系统 ingestion；worker 不得打开、解析、渲染、转换、OCR、截图或交给视觉模型。抽取文本不足时应记录 source gap、改用其它批准文本/网页、缩小表述或升级范围问题。

截图、PDF contact sheet 和模型视觉审核全部禁止。GeoGebra 只能使用已验证 `geogebra.org/m/...` 的普通超链接。Python 作图默认关闭，只有任务明确批准时才启用。

## 9. 工具链锁定与 smoke test

根目录 `TOOLCHAIN-LOCK.yaml` 要求：

```yaml
marp:
  package: "@marp-team/marp-cli"
  version: "4.5.0"
  install_policy: exact_pinned_version
```

正式 production 前必须运行三页 smoke test，验证：

- 实际 Marp 版本；
- Marp 4.5 的 slide DOM；
- 数学、字体和图片 readiness；
- HTML slide count；
- PDF 构建和页数；
- `global_meeting_number` / `deck_local_ordinal` schema。

HTML inspector 使用显式 slide-ready 条件，不等待可能长期不结束的 `networkidle`。匹配不到 slide 时快速失败；渲染 timeout 随 deck 页数调整。

## 10. Author/release 机械门

增量 authoring 检查只处理变化内容；freeze 和 release 运行完整门：

1. Marp source lint；
2. asset 与 GeoGebra 验证；
3. terminology、semantic objects、课次编号和 continuity；
4. principal-teaching-move density；
5. math source inventory 与 disposable-HTML renderer probe；
6. HTML overflow/out-of-bounds；
7. PDF build；
8. PDF 页数、几何与文本层检查。

临时 HTML 必须删除。reviewer 不重复机械 overflow 检查。项目没有 `MATH-PDF-EVIDENCE`；数学正确性由 domain reviewer 判断。

## 11. Workflow-engine incident

技术 bug 不因“纯技术”而获得任务内热修权限：

```text
record ENGINE-INCIDENT.yaml
        ↓
propose workflow_engine_technical_fix amendment
        ↓
main agent revises TASK.md
        ↓
present and reconfirm TASK.md
        ↓
engine refactoring handled as separate work
```

禁止一边修改 workflow engine、补测试，一边让原课件任务继续运行。

## 12. 安装

需要 Python 3.11+、Node.js 18+、Chromium/Playwright，以及可用的 PDF 文本工具。推荐在隔离的 VM 或容器中运行。

```bash
python scripts/bootstrap.py
```

这个命令会创建 `.venv`、安装 Python 包、安装精确 Marp 4.5.0、准备 Playwright 浏览器并运行 doctor。可用参数见：

```bash
python scripts/bootstrap.py --help
```

生产前再次检查：

```bash
.venv/bin/mpres doctor --strict
.venv/bin/mpres toolchain smoke
```

Windows 对应可执行文件在 `.venv\Scripts\`。

## 13. 启动方式

安全模式：

```bash
./start-safe.sh
```

无 sandbox/approval 的模式只应在外部隔离环境中使用：

```bash
./start.sh
```

PowerShell 使用 `start-safe.ps1` 或 `start.ps1`。

## 14. 常用 CLI

```bash
# 创建并确认任务
mpres task init --title "..." --kind course --stop-mode all \
  --sessions 8 --minutes 90 --production-mode legacy_migration
mpres task present <slug>
mpres task confirm <slug>

# 工具链
mpres toolchain status
mpres toolchain smoke

# 初始化 presentation/unit 元数据
mpres production init <slug> \
  --presentation 'p01::矩阵与线性变换' \
  --unit 'p01::u01::第 1 节课'

# planner 批次计划
mpres assignment batch-status <slug>
mpres assignment batch-approve <slug> --planner-actor delegated-planner

# 延迟展开并进入关键路径
mpres production queue-unit <slug> --presentation p01 --unit u01
mpres production critical-path <slug>

# 阶段、审核与发布状态
mpres stage --help
mpres review --help
mpres maintenance --help

# 技术故障
mpres engine incident <slug> --id marp-dom-regression \
  --symptom "..." --blocked-operation "..." \
  --reproduction "step 1" --reproduction "step 2"
```

具体参数以 `mpres <command> --help` 为准。

## 15. 日志、线程与 token

所有角色通过常驻 Python daemon 写入唯一日志：

```text
tasks/<slug>/logs/project.jsonl
```

控制平面自动记录 routine transition；模型只记录语义决策、阻塞、handoff、policy change 和 delivery。token 只在 workflow milestone 收集精确计数，不用模型定期轮询。

lesson author 完成 handoff 后应关闭或释放 thread；不要为了可能出现的 review finding 长期占位。

## 16. 验证与开发

```bash
export PYTHONPATH=src
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m compileall -q src scripts tests
python -m pytest -q
python scripts/validate_project.py --skip-tests
```

安装 dev 依赖后还可运行：

```bash
python -m ruff check .
```

发布前应清理 `.venv`、`node_modules`、`.mpres`、测试缓存、`__pycache__` 和任务运行数据。源码包不生成 archive checksum，因为项目政策只允许顶层 `TASK.md` 使用确认 digest。

## 17. 有意不实现的功能

- reviewer 对修订稿进行第二轮复核；
- 截图或模型视觉审核；
- worker 访问原 PDF；
- persistent HTML deliverable；
- 非 `TASK.md` 哈希；
- stage-specific assignment；
- speculative reviewer/release worker；
- lesson author 在 review 后重新打开；
- 任务内 workflow-engine hot patch；
- 由 mechanical release job 作内容判断。

## v0.6.2 mechanical review and release control

`review-coordinator` and `release-coordinator` are no longer model roles. Their Codex agent configurations and assignment templates have been removed. Freeze registers `control-plane/review-aggregation/<presentation>/job.yaml`; after five validated reviewer receipts, Python generates the aggregate and job receipt. Revision completion registers `control-plane/release/<presentation>/job.yaml`; release rendering, inspection, packaging, and receipt generation run without a model thread.
