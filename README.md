# Marp Presentation Orchestrator

把教材、教学目标与用户确认的课程计划转化为 Marp 课件。Python 负责运行事实和机械
检查，AI 负责教学语义；不要求 main agent 阅读大量过程文档后逐条操作流程。

**版本 v0.6.15：新任务已经接通写作 → 组装 → 整稿编辑 → 完整门禁 → 五通道审核 →
修订 → 再次完整门禁 → PDF 发布 → PDF/源码配对 ZIP。** 运行器不把源码提交等同于交付；缺少原生渲染工具、
审核回执、finding 处置或明确宿主状态时都会停止。当前验收覆盖确定性适配器和失败分支，
尚未在本交付环境验证真实模型与固定 Marp 浏览器的端到端输出质量。

## 1. 完整流程：每一步做什么

| 步骤 | 执行者与工作方式 | 当前实现 |
|---|---|---|
| 需求与课程规划 | 用户和规划 AI 确定听众、先修、按第几节课组织的 brief、核心与补充内容 | 用户入口和校验已实现 |
| 展示、确认配置 | 程序展示三份入口；用户明确确认后保存不可变配置快照 | 已实现 |
| 创建作业 | 从已批准 plan item 生成数据库 job ID、依赖和课次坐标 | 已实现 |
| 容量准入 | 宿主实际 inventory 与用户上限取更严格值；预算作者、五 reviewer、编辑者和恢复余量 | 已实现 |
| 历史反馈回顾 | SQLite 保存用户原话、问题表现、验收期望；每次作者/编辑/reviewer 开工先短回执，随后才派发内容执行 | 已实现 |
| 写作与提交 | runner 领取作业，发精确 JSON 请求，接实际回执、源码和 usage | 已实现 |
| 单元源码门禁 | runner 下次 tick 对新修订运行源码、TeX 和资产边界检查 | 已实现 |
| 整稿组装与语义编辑 | 程序组装，短时编辑作业判断叙事与教学衔接，不设常驻 coordinator | 已实现 |
| 完整机械门禁 | 指定源码修订 → 临时 HTML/DOM → 数学渲染 → PDF 结构和文本边界检查 | 已实现 `artifact inspect --level full` |
| 冻结与专项审核 | 五个不同且独立的 reviewer 阅读同一冻结稿；不做模型型审核协调 | 已实现 |
| 修订与再次门禁 | findings 送给作者，生成新修订；旧稿门禁不能批准新稿 | 已实现 |
| 用户指定返修 | 交付后先只读展开问题形式与相似问题 → 展示精确方案 → 等用户确认 → 仅修改指定稿件 → 重走审核发布 | 已实现 |
| 发布、打包与暂停 | 仅对合格版本发布 PDF；从发布记录取对应源码，机械生成累计交付 ZIP；按 all/pilot/each 继续或暂停 | 已实现 |

新建任务默认 `workflow: full`。程序只有将对应 PDF 发布记录提交为 committed 后才
标为 delivered；所有 deck 都完成才将任务标为 completed。`workflow: authoring` 是明确的
只写稿模式，永不自动发布。旧 v0.6.8—v0.6.10 配置没有 workflow 字段时按 authoring
兼容，不能悄悄给旧确认追加审核与发布授权；需要完整流程时新建任务或只读导入后确认。

## 2. 职责划分与固定运行配置

main agent 只处理需求、教学范围和不能机械解决的语义问题。runner 管作业身份、
依赖、句柄、容量、输入包、提交、检查、计时和 token。没有模型型 review-coordinator
或 release-coordinator；不要恢复旧管理角色来驱动新入口。

用户在任务确认前编辑 `TASK-RUNTIME-PROFILE.yaml`。默认 planner/author/reviewer
分别为 sol high/medium/low，项目中的具体默认标识延续为 `gpt-5.6-sol`。
用户应自行填宿主实际接受的模型标识。程序不推断当前有哪些模型，不依据难度、预算、
置信度或重试切换 runtime。实际运行回执不匹配时拒收，不接受隐藏 fallback。

作者并发是用户上限；容量不足时可排队、降低实际并发，但不能改模型或推理强度。

## 3. 代码如何组织

```text
src/mpres/
  cli.py                       默认新入口；显式 legacy 才加载旧入口
  control/
    cli.py                     参数解析和结构化输出，不包含语义判断
    schema.sql                 关系、外键、唯一约束和不可变配置
    migrate_*.sql              旧 schema 的原子增量迁移
    store.py                   短事务、查询、一致性数据库备份
    service.py                 确认、作业、绑定、提交、usage 和状态
    runner.py                  实际宿主证据、池准入、领取、输入包、JSON 适配器
    quality.py                 源码/full gate、修订绑定、并发幂等、失败与恢复
    workflow.py                固定整稿状态机、组装、审核证明、finding 处置、发布
    repairs.py                 问题展开、方案版本/确认、指定返修、历史发布与专用 ZIP
    feedback.py                用户反馈版本、开工回执、结果证据和旧审核失效检查
    teaching_feedback.json     本项目用户明确指出的三项教学质量底线，自动进入任务数据库
    delivery.py                按已提交 release 配对 PDF/源码，累计 ZIP、校验与独立重试
    theme.css                  实际课件样式；写作输出预置同一份 theme
    semantic.py                四个语义 schema 的真实验证；每类作业只注入对应语义指南
    schemas/                   plan、author-result、review-result、diagnosis-result
    files.py                   安全相对路径、只读快照、可写副本
    migration.py               旧任务只读导入
  marp_source.py               Marp 解析、内容 lint；compact 不要求旧过程记录
  html_layout.py              临时 HTML + DOM 几何检查；canonical ID 优先
  math_inspection.py          TeX 结构与渲染节点检查，不证明数学正确性
  pdf_inspection.py           页数、字体、文本、边界和异常字符检查
  rendering.py, toolchain.py  复用固定 Marp 命令和版本校验
  runtime_profile.py          固定配置解析
  legacy_cli.py, ...          旧任务兼容实现，不得向新任务另建状态

templates/compact/            三份用户配置模板
.agents/skills/               仅六个语义 skills；旧管理 skills 已删除
scripts/                     显式安装、静态验证；启动器只调用 compact CLI
tests/compact/               新控制面、适配器与门禁测试
tests/                       原有回归测试保留
```

数据关系是 config → plan item → job → attempt → artifact → gate/check。
Session 与 attempt 关联；usage、finding、decision、event 也在 SQLite 中。
`gate_runs` 引用 artifact ID 和级别，每次明确重查有单调 sequence；报告为数据库数据，
不是作者必须填写的 YAML。decks 保存每稿当前阶段和候选/冻结修订；releases 保存
prepared/committed 最新发布记录；release_versions 保留每个历史版本及其准确源码和门禁。
repair_cases/repair_targets/repair_jobs 保存原话、方案版本、用户确认和指定目标关系。保留旧模块是为了复用经过测试的技术能力和读取旧任务，
不是维护两个可写状态系统。

## 4. 用户看到的任务目录

```text
tasks/<slug>/
  TASK.md                       教学任务和用户确认边界
  task.yaml                     计划与非模型参数
  TASK-RUNTIME-PROFILE.yaml      用户自行选择的固定 runtime
  sources/                      获准教材文本和数据
  content/                      人工或作者编辑的实际内容
  deliverables/                 已审核并经门禁的 PDF，以及 <slug>-delivery.zip
  .mpres/
    task.sqlite3                唯一运行事实源
    artifacts/<revision>/       已提交或导入的只读源码与资产
    work/<attempt>/             本次输入快照和可写 output
    gates/<gate-id>/            完整检查生成的 PDF；不是正式交付
```

不生成 assignment 三联单、THREAD-REGISTRY.yaml、STAGE-ARTIFACT.md 或 SELF-CHECK.md。
状态用命令查询，需要人工归档时才重定向输出。只读权限是防误写措施，不是同一系统
用户之间的安全沙箱。请在独立工作账户或容器内运行外部作者与渲染器。

## 5. 安装、创建、确认

需要 Python 3.11+；完整检查需要固定版本的 Marp CLI、Node.js 和浏览器。

```bash
python -m venv .venv
. .venv/bin/activate                 # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
npm install
mpres --help
mpres --root . task init economics --title "面向经济学的线性代数"
```

先编辑三份入口。`task.yaml` 的每课 brief 必须是教学语义，不是操作指令：

```yaml
presentations:
  - id: p01
    title: 向量与经济数量
    units:
      - id: l01
        title: 坐标和单位
        brief: 从商品数量解释坐标，说明单位，安排一个例题和一个诊断问题。
        sources: [sources/chapter-1.txt]
```

provider 模式、容量和命令需来自实际环境，不应猜测。`handle_limit: null` 表示未知，
不是无限容量。`quality` 仅允许 browser 与 timeout_seconds；不提供跳过 full gate
或注入“成功报告”的任务配置。

```bash
mpres --root . task present economics
# 用户看到准确内容并明确确认后：
mpres --root . task confirm economics --by user
mpres --root . task materialize economics
mpres --root . task jobs economics
```

确认后修改三份入口会阻止后续运行。数据库快照不会自动追随文件。只有顶层 TASK.md
使用既有确认摘要；源码、配置快照和发布包不新增 hash。

## 6. 作业怎样执行

### command 模式

用户配置一个 JSON-stdio 宿主适配器 argv。`runner run` 前台循环查询能力、准入、
派发、接收，无需 main 每二十分钟读日志决定下一条命令。

```bash
mpres --root . runner run economics --cycles 100 --interval 1
```

适配器必须真实实现四种请求：

* `brief`：与内容作业使用同一固定 runtime、同一 session，先返回 receipt、runtime、usage 和
  readback（每项 id/version/approach）。此时没有可写内容目录；全部回执接受后才派发 `run`。
  不支持此操作的旧宿主需适配，不能自动跳过。
* `capabilities`：返回 handle_limit、handles、supports_close、supports_reset、
  usage_reporting 和 receipt；它们来自宿主，不是复述 task.yaml。
* `create`：输入 request_id、slot_id、runtime；返回实际 handle、model、
  reasoning_effort、receipt。相同请求应幂等。
* `run`：输入 attempt_id、session_id、runtime、packet；返回实际 runtime、receipt、
  result、usage，以及作者才有的 source_dir。source_dir 必须位于本次 output 下。

usage 是 `{call_id, counters}` 数组；counters 包含 input_tokens、cached_input_tokens、
output_tokens、reasoning_tokens、total_tokens。缺失字段写 null，不得伪装零。

### bridge 模式

宿主只能从模型工具启动会话时，runner 返回精确请求，main 只转发，不重新规划：

```bash
mpres --root . runner host economics --report actual-host.json
mpres --root . runner tick economics
mpres --root . runner accept economics --request exact-request.json --response actual-response.json
mpres --root . runner outstanding economics
```

可用 `-` 从标准输入读取，传输 JSON 不是流程真源。bridge 仍有转发回合，不宣传为
零模型控制成本。宿主适配器不是模型技能；仓库不假定未公开 API 存在。

## 7. 源码、检查和失败怎样流转

作者提交目录至少包含 presentation.md 和 theme.css，以及实际使用的 assets。
每页保留稳定 `slide-id`，class 为 core/support；源码头使用：

```yaml
---
marp: true
theme: mathist-academic
paginate: true
size: "16:9"
math: mathjax
---
```

`theme.css` 声明 `/* @theme mathist-academic */`。教材、题目、答案、条件与先修的
质量仍需要 AI 语义审阅；机械 gate 不会证明数学结论或教学效果。

```bash
mpres --root . artifact inspect economics REVISION_ID --level source
mpres --root . artifact inspect economics REVISION_ID --level full
mpres --root . artifact gates economics REVISION_ID
```

source 检查 frontmatter、canonical ID、core/support、密度、图像路径、常见 TeX
控制词错误、数学环境、CSS/SVG 资源边界。full 先做相同检查，再验证固定 Marp 版本，
运行临时 HTML/DOM 和数学节点检查，生成 PDF 并核验页数、文字边界、替换字符等。
临时源码可写，检查后的 PDF 只读，报告在库中；没有截图、OCR 或模型视觉步骤。

同修订同级别重复检查默认返回已有记录；更换源码必须生成新修订。要明确重跑机械
工具可加 `--retry`，保留旧记录。仍在 running 的检查不会被重跑；确认其进程已经停止后：

```bash
mpres --root . artifact interrupt-gate economics GATE_ID --reason "已核实原检查进程停止"
mpres --root . artifact inspect economics REVISION_ID --level full --retry
```

检查和模型调用均在 SQLite 写事务外运行。程序不假称数据库能回滚外部调用。
创建／执行回执丢失会保留不确定状态和占用；同请求对账前不盲目重试，不虚构 close。

## 8. 整稿流程怎样自动推进

`runner tick/run` 调用 `Workflow.advance()`。all 模式在共享、预留了下游资源的固定池内
最多推进 current + next；pilot 首稿、each 每稿的用户暂停前都不启动下一稿。

1. 每课新修订先做 source gate。内容错误生成一个有界、短时 edit 作业，直接提供失败
   检查和可写源码副本；达到 max_attempts 后停止，不无限修稿。
2. 全部课次合格后机械组装。按课程顺序连接页面；相同 theme/资产逐字节一致时共用，
   冲突时停止，不猜测应当保留哪份。每课资产使用 assets/<unit-id>/，避免同名覆盖。
3. 对组装稿启动一次短时整稿编辑作业。AI 只处理衔接、术语含义和教学叙事，不收文件、
   写状态或常驻轮询。每次编辑直接得到可写副本，不必重抄整套源码。
4. 完整原生 gate 通过后冻结。五个通道分别用五个不同、独立的 reviewer 读同一份
   source/PDF；队列身份、容量、scope 和回执由程序管理。代码不把机械检查当作数学证明。
5. 无 finding 则直接进入发布准备。有 finding 则交一个 revise 作业；每条 finding 必须
   有 addressed 或 needs_decision 及解释。needs_decision 会停止；程序不自作主张否决 reviewer。
6. 修订稿必须保留冻结 slide ID，再跑完整 gate。门禁修复也受次数上限约束。每条处置
   与最终候选修订关联；旧稿的处置/门禁不能批准新稿。沿用一轮五通道审核，修订后不
   自动添加新 reviewer 轮次；扩大教学范围或删除冻结页面需要新任务/新审核。
7. 发布前再次验证五个审核回执、独立性、finding 和精确候选 gate。PDF 先暂存，最终
   路径独占创建，prepared → committed；中断后同字节才能收敛，永不静默覆盖旧交付。
8. 每次 advance/tick 在已提交发布之后同步交付 ZIP。压缩只使用 committed releases；
   不扫描工作草稿，不运行新模型或重新渲染，返回的 delivery_package.path 是应交给用户的压缩包。

```bash
mpres --root . workflow status economics
mpres --root . workflow advance economics
# pilot/each 已交付后，用户明确反馈并允许继续：
mpres --root . workflow continue economics --by user --note "按既定计划继续"
```

程序不因为定时器到期唤醒 main；main 只处理明确的配置确认、用户反馈、未解决语义
问题或异常恢复。遇到环境修复而不是模型错误，可以机械重跑：

```bash
mpres --root . workflow retry-checks economics --presentation p01 --note "已修复渲染环境"
mpres --root . workflow retry-publish economics --presentation p01 --note "已核实原发布进程停止"
mpres --root . workflow recover-assembly economics --job-id JOB_ID --note "已核实原组装进程停止"
```

这些接口不改变 runtime、内容或 finding。仍在运行的 gate 先使用 interrupt-gate 明确
记录停止核验；AI attempt 回执不明时继续沿用同请求对账，不假称失败后重试。
语义争议不会被 retry-checks 绕过；本版尚未提供原任务内任意语义变更/重新确认流程，
这类变更需新建或导入新任务后确认。

### 交付压缩包：PDF 与对应的 Markdown 同名

每次完成一份或多份交付后，runner 自动生成或更新：

```text
tasks/<slug>/deliverables/<slug>-delivery.zip
```

例如 `economics` 任务已经交付两份课件，解压后的目录如下：

```text
economics-delivery/
  p01/
    p01.pdf
    p01.md
    theme.css
    assets/                     # 该已发布修订中的资源；有则保留
  p02/
    p02.pdf
    p02.md
    theme.css
    assets/
```

每个 PDF 与 Markdown 使用同一 presentation ID（与交付 PDF 文件名一致）。
内部仍使用 `presentation.md`；只有 ZIP 条目改名，**不移动、改名或重写 canonical source**。
程序从 `releases.artifact_id` 取这份 PDF 对应的源码修订，不取较新的工作草稿。
同一源码快照内的主题、图片和其他资源保留相对路径；各课件分目录，避免同名资源互相覆盖。
ZIP 中的源码为普通可编辑文件，不继承内部快照的只读权限。压缩包不是完整任务备份，
不加入任务数据库、线程记录、检查日志、输入教材或其他任务工作目录。

`all` 持续更新同一个累计包；`pilot/each` 在反馈暂停前也会生成，只包含当时已交付的课件。
后续交付继续更新同一路径，不散落一批时间戳压缩包。无交付或只有 prepared 发布时不生成 ZIP。
宿主向用户展示交付时，应附上 `delivery_package.state=ready` 对应的 `path`，而不只列单份 PDF；
项目命令提供本地路径，不代替宿主向外部聊天/云盘上传文件的接口。

已交付的 SQLite 新控制面任务也可以补打包或重新验证：

```bash
mpres --root . workflow bundle economics
mpres --root . workflow status economics
mpres --root . task status economics
```

`workflow bundle` 校验已有 ZIP 的条目及内容；未变化时不重写、不重复记账。
正常 tick 使用现有事件和 ZIP 文件元数据判断是否需要更新，避免每次轮询解压所有内容。
打包先在 `.mpres/delivery-staging` 暂存并校验，再用短数据库事务核对 release 集合、原子替换 ZIP。
压缩或校验失败保留上一个完整 ZIP，runner 返回 blocked 和打包错误；不会撤销已提交 PDF，
也不会为了重试 ZIP 而重新调用 author、reviewer 或渲染器。修好文件权限、磁盘空间等问题后，
重跑 `workflow bundle` 或 runner 即可。`task.status=completed` 仍指 PDF 发布完成，
是否已完成压缩交付另看 `delivery_package.state`。缺失源码、缺失/被改写的正式 PDF、
不安全路径或重名条目均拒绝打包，不跳过缺失的配对文件后冒充成功。

`.gitignore` 使用 `**/deliverables/*-delivery.zip` 屏蔽这些生成包；暂存目录由已有 `.mpres/`
规则屏蔽。不使用全局 `*.zip`，不会屏蔽项目源码发行包或用户主动版本控制的教材 ZIP。
Git 已经跟踪过的文件仍需手动取消跟踪，ignore 规则不会自动删除历史记录。
本功能不更改任务确认配置、runtime 或数据库 schema，也不增加 skill、模板或过程文档。
显式 `legacy` 旧引擎尚未接入自动 ZIP；上述命令面向有 `.mpres/task.sqlite3` 的新控制面任务。

## 9. 状态、成本和迁移

```bash
mpres --root . task status economics
mpres --root . task metrics economics
mpres --root . job show economics JOB_ID
mpres --root . task backup-db economics /safe/path/task.sqlite3
mpres --root . task import-legacy /old/task/path --slug economics-imported
```

metrics 按 attempt/作业/课次归因；gross、cached、fresh 分开，字段覆盖和 attempt
覆盖分开。没有全生命周期证据时不标成 100%；没有价格依据时不推算金额。
`backup-db` 只备份一致的数据库，不包含资产，不等于完整可搬运任务包。

旧任务导入不修改旧目录，不导入句柄为可用，不继承旧 gate 成功，不伪造 handoff。
旧内容标为未验收；计划信息不足则需补 brief 并确认。schema 1/2/3/4/5 打开时短事务升级为 6，
不修改已确认 runtime。quality 缺省采用 auto/1800，旧确认快照仍原样保存。缺少 workflow 字段的旧任务继续只写稿。

## 10. 验证与已知边界

```bash
PYTHONPATH=src python -m pytest tests/compact
python scripts/validate_project.py
```

测试适配器仅是明确标识的确定性 fixture，不是真实模型。完整 gate 的自动化测试
既覆盖“工具缺失必须失败”，也用注入的测试函数验证事务和分支；测试替身不属于任务
配置。部署机器仍须安装固定渲染器并实际完成自己的 toolchain 验收。

旧管理 skills 和常驻 author-coordinator 配置已经删除。旧模板、Python 兼容模块仍保留，
但只服务显式 legacy；新任务不生成它们，也不把它们编入模型输入。它们的进一步删除需
先完成旧任务迁移验收，不能仅为减少文件数而破坏导入和技术模块。

已安装环境下可直接运行 `./start.sh runner run economics`；Windows 使用
`start.cmd runner run economics`。无参数显示 CLI 帮助。启动器不自动安装、不启动日志
daemon、不调用 Codex、不注入旧长提示，也不禁用宿主的 approvals/sandbox。安装须先
显式执行 `python scripts/bootstrap.py`；`mpres toolchain doctor` 检查真实渲染环境。
Windows 脚本在本发布环境仅作文本/参数路径审查，未在 Windows 原生执行。

## 11. 六个语义 skills 怎样使用

| Skill | AI 需要作出的判断 |
|---|---|
| course-planning | 受众、先修、按课次组织的计划、核心/补充和材料边界 |
| marp-writing | 直觉、条件、例题、诊断题、学生语言与 Marp 内容表达 |
| deck-editing | 跨课语义衔接、术语、finding 驱动的最小修订 |
| specialist-review | 五个独立通道各自对完整冻结稿作语义判断 |
| problem-diagnosis | 给定问题证据的根因假设、影响范围与不确定性 |
| resource-design | 图示/资源的教学价值、表达方式与出处 |

原来的 26 个 skills 已从自动发现目录移除，重新写成以上六类；没有把它们合并成
一本更大的流程手册。作业身份、容量、绑定、gate、日志、token、发布不属于这些 skills。
每次 write/edit/revise/review 作业由 runner 注入一份相应指南，不要求 AI 自行选择和
阅读所有技能。规划、诊断、资源设计是语义能力，不意味着每个任务都会启动全部角色。
完整生产链自动调度写作、整稿编辑、五通道审核和修订；repair open 后另外安排只读问题展开。

schema 是真正执行的边界，不只是说明文件。计划在确认前验证；结果在冻结源码或
登记 finding 之前验证。`author-result` 允许 summary、可选 teaching_notes/open_questions，
修订另有每条 finding 的 resolutions。review-result 要求 message/slide_ids/severity，
诊断结果要求 hypotheses/confidence/affected_slide_ids/recommended_action。未知流程字段
如 gate_passed、capacity_released 不被接受；程序不会相信 AI 自报机械状态。

模型包只包含本作业 brief/课程概要、真实源稿/资产、必要 finding、对应指南/schema。
机械报告只摘取失败、警告和页数，不重复塞入每页全文和每个 PDF 字符 span；完整报告
仍在数据库内可查。二进制附件体积另记 attachment_bytes，不冒充文本 token 估计。
这减少了强制重复输入，但不承诺未经真实模型任务对比验证的 token 节约比例。

## 12. 历史反馈怎样避免丢失

聊天上下文不是质量要求的真源。`feedback_rules` 以版本保存用户原话、期望、可能表现、
验收准则和适用课件；`attempt_briefings` 保存本次作业实际收到和回顾的版本。默认内置用户
已经明确提出的三类问题：规范术语、近几年实际生活/经济场景、明示几何直观。
新任务自动写入数据库，task present 会展示当前历史反馈；旧 compact 任务在下一次绑定/读取反馈时补入，不生成过程文档。

每个 write/edit/revise/review（以及后续诊断）执行如下小循环：

```text
领取作业 → brief：原话+期望+问题表现 → 短 readback：本次如何应用/检查
         → run：再次携带相同历史反馈 + 本次源码/资料
         → feedback_checks：逐项处置 + 真实 slide ID/原文证据
         → 独立审核和机械门禁 → 交付
```

没有 readback 不能启动内容执行。重复完全相同的回执幂等，不能事后补造或改写；
新来源版本不覆盖旧反馈。正常新增反馈适用于随后领取的作业；在途作业维持收到的快照。
但若已审稿的反馈版本已过时，发布检查拒绝沿用旧审核，需新审核/返修，不能静默降低要求。

“satisfied”必须有实际存在的页内摘录；“issue”由 reviewer 同时写入可路由 finding。
作者尚有 issue 不得冻结/发布。不适用允许给出具体理由，防止每页强塞故事和几何图。
代码验证回顾顺序、条目完整性、出处对应与版本，并不能证明模型真正理解或保证数学质量；
独立 reviewer 必须实质检查，不可把格式通过等同内容正确。

近期例子优先最近三年（按包内 as_of_date），必须把场景—变量/单位—数学模型—现实解释接起来。
作者可在批准主题内使用宿主提供的检索工具寻找可核验公共来源，并标注事件日期/出处。
没有检索工具或资料不足时报告证据缺口；不能编造新闻、统计或出处。教学模拟数字必须明确标注。
几何直观要实际体现在标注图示或可操作的构造与公式对应中，不是仅写“可用几何解释”。

```bash
mpres --root . feedback list economics
mpres --root . feedback list economics --history
# --rule 接受 JSON 文件或 -（标准输入）；它只是输入，不是运行时过程文档。
mpres --root . feedback record economics --rule - --by "用户明确提出的反馈"
mpres --root . feedback inherit next-course --from-task tasks/economics --by "用户同意沿用"
# 手工 bridge 调试：正常 runner 会自动完成此握手。
mpres --root . job briefing economics <attempt-id>
mpres --root . job acknowledge economics <attempt-id> --readback - --receipt <真实回执>
```

一条自定义反馈使用 id/report/expectation/possible_forms/acceptance/presentations/enabled。
同一 id 的修订追加版本；停用也必须有明确用户授权与 attribution，agent 不得自行停用。
从其它任务沿用通过 inherit 显式导入，不依赖某次会话是否记得；定向 scope 必须属于新任务。
确认配置与 runtime 不改变。`--by` 是审计归因，不是身份认证；宿主必须只转发真实用户授权。

readback 会增加一次很短的模型调用；其 token 单独计入同一 attempt，绝不假装零成本。
原来的 6 个语义 skills 和 4 个语义结果 schema 数量不变，新增的是其中的语义要求与数据库门禁。

## 13. 用户指出一类问题后怎样返修一份或一批课件

这是与正常课程生产共用运行器的返修模式，不是 agent 自行决定“重写全部”。它在已交付
任务完成后，或 pilot/each 的交付暂停处启动；不覆盖正在运行的写作/审核。目标必须明确
列为一份或多份已 committed 的课件。原任务的 runtime 始终不变。

```text
用户指出问题 + 指定 p01 / p03
  → repair open：保存原话，锁定各稿当前已交付源码/PDF 版本
  → runner：只读诊断作业，积极展开问题变体、相似问题、识别方法与修法
  → repair present：展示精确方案版本、目标、非目标、验收条件和资料缺口
  → 等待用户回复；初始投诉不是对 AI 展开方案的授权
  → repair confirm：只确认刚展示的那个版本及其准确目标
  → 作者逐份修订 → 完整门禁 → 五名独立 reviewer → 必要修订 → 再次门禁
  → 新版本 PDF + 对应 Markdown/资产 ZIP，原版不被覆盖
```

### 先展开、再确认，而不是只把问题换一种说法

diagnosis-result 的 expansion 要包含问题本质、至少一种实际发生形式、相邻/相似问题、
各项识别方法与修正方向、非目标、验收准则、资料需求。例如“术语随意”不只查字面名称，
还应考虑定义被比喻取代、同义乱用、符号漂移、适用条件缺失等可能形式。
这些是需要 AI 结合用户问题作出的语义分析，不由关键词脚本决定。

为避免确认之前就花费大量成本逐稿改写，展开阶段仅只读一份代表性目标稿件，返回实际
检查过的稿件/源码 ID。未检查的目标不能声称已经发现缺陷；possible 与 observed 明确区分，
observed 必须引用已经看到的页 ID。用户确认后，作者和 reviewer 才逐份全稿排查整个问题族。

方案被补充或改写后，版本递增，之前的展示失效；必须重新呈现、重新确认。目标的已交付
版本在此期间发生变化也会拒绝使用旧方案。确认以规范化快照比较，不新增 hash。
用户确认会把这项问题及验收条件写成该批目标的持久反馈，后续作者和 reviewer 也会再次读到。

### 示例命令

```bash
# 1. 用户选择一份或多份已交付课件；这里只授权读取并展开问题，不授权改稿。
mpres --root . repair open economics \
  --report "规范术语被随意的说法替代，请展开排查范围。" \
  --presentation p01 --presentation p03 --by "用户提出"

# 2. 自动执行只读展开；停止在 awaiting_confirmation。
mpres --root . runner run economics
mpres --root . repair present economics <case-id>

# 3. 把展开结果给用户看。用户补充时可用 amend 接收完整修改后的 expansion JSON；
#    --proposal - 从标准输入读取，不需要持久维护方案文件。
mpres --root . repair amend economics <case-id> --proposal - --by "根据用户反馈调整方案"
mpres --root . repair present economics <case-id>

# 4. 只有用户明确确认这一版之后才能执行：
mpres --root . repair confirm economics <case-id> --version 2 --by "用户明确确认"
mpres --root . runner run economics
mpres --root . repair status economics

# 独立补打包，不重新写作/渲染：
mpres --root . repair bundle economics <case-id>
# 用户不批准时可取消未确认方案（有在途诊断时须先核对回执）：
mpres --root . repair cancel economics <case-id> --by "用户" --note "此次不返修"
```

每个确认的问题变体和相似问题都需要 repair_checks：addressed、not_found 或 needs_decision，
加说明与实际页 ID。仅修举例页却漏掉同类问题、漏项回执、编造页码，会被拦截或交给独立
reviewer。无法判断/缺少来源的内容必须停在语义待决，不把空泛改写当成解决。

### 新旧交付版本与打包

原 `deliverables/p01.pdf` 和只读源码修订保持原样。首次返修生成 `p01-r002.pdf`，再次返修
生成 `p01-r003.pdf`。releases 指向最新 committed 版本，release_versions 保留全历史。
只有新发布提交后才切换当前版本；发布失败保留旧 PDF 和旧交付记录，可沿用
`workflow retry-publish` 恢复，不必重新调用模型。

正常累计 `<任务名>-delivery.zip` 更新为各稿最新版本。返修完成还自动生成
`<任务名>-repair-<标识>.zip`，只包含此次指定稿件；包内仍为 `p01/p01.pdf`、`p01/p01.md`
及该源码版本的主题/资产，同名配对。`repair status` 返回 ready 的实际 ZIP 路径；宿主只附
已存在且 ready 的压缩包。打包失败可单独 repair bundle 重试，不能拿未交付稿冒充结果。
两类 ZIP 都有精确 `.gitignore` 规则，不屏蔽项目源码发行包。

批量返修仅执行指定目标，不启动未选择的后续课件；在 pilot/each 的暂停处返修，完成后
恢复原暂停，继续下一稿仍要独立的用户反馈。数据全部入 SQLite，不新增一堆过程 Markdown。

### 边界与部署

本入口服务 compact SQLite 的已交付任务。只有 legacy 目录或一个外来 presentation.md
而没有 compact 发布记录时，不会伪造其已审核状态；应先按原迁移/验收流程导入。
宿主仍负责真正的模型调用、检索与沙箱：项目只提供契约和提交门禁，不声称实现 OS 级隔离。
用户授权由宿主转发，--by 是审计归因，不是认证凭证。没有真实确认，main 不得自动执行 confirm。
规范术语、现实案例与几何直观的质量不能由字符串或 JSON 验证器证明；必须由 reviewer 实质判断。

## 最近阶段

v0.6.14 加入历史用户反馈的持久化、开工短回执和页内证据检查；v0.6.15 加入先展开再确认
的单稿/批量返修，重走独立审核、保留历史交付、自动配对 ZIP。schema 为 6，仍是 6 个语义
skills、4 类语义结果 schema、3 份用户配置入口。模型与推理强度没有改变。
测试覆盖真实 SQLite、源码快照、文件和 ZIP；模型与 full-render 部分使用明确标识的替身，
不把协议测试当成真实数学教学质量或原生 Marp 浏览器的端到端验收。
