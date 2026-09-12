# Marp Presentation Orchestrator

把教材、教学目标与用户确认的课程计划转化为 Marp 课件。Python 负责运行事实和机械
检查，AI 负责教学语义；不要求 main agent 阅读大量过程文档后逐条操作流程。

**当前工作方式：新任务已经接通写作 → 组装 → 整稿编辑 → 完整门禁 → 五通道审核 →
修订 → 再次完整门禁 → PDF 发布 → PDF/源码/资产直接目录交付。** 运行器不把源码提交等同于交付；缺少原生渲染工具、
审核回执、finding 处置或明确宿主状态时都会停止。当前验收覆盖确定性适配器和失败分支，
尚未在本交付环境验证真实模型与固定 Marp 浏览器的端到端输出质量。

## 0. 怎样开始工作

首次安装：`python scripts/bootstrap.py --with-figures`。Codex 需单独安装并登录；
启动器不会替你登录、付费调用、安装依赖或关闭审批和沙箱。

```bash
./start.sh --check                    # 只做本地环境检查，不调用模型、不改任务
./start.sh                            # 在本项目根目录启动交互 Codex，开始需求/规划
./start.sh --task economics           # 继续已存在任务，固定其 main-planner 模型/强度
./start.sh --task economics -- --no-alt-screen
./start.sh --cli task status economics  # 只查数据库，不启动 Codex
./start.sh --cli toolchain doctor     # 原生 Marp/浏览器检查
```

Windows 对应 `./start.ps1`，`start-safe` 与普通入口使用相同安全设置。
也可先进入项目目录手动开启 Codex；它仍读取根 `AGENTS.md` 和同一数据库。
指定 `--task` 表示恢复任务工作，不是猜测或自动重用某个宿主 conversation ID。

无 task 的会话使用用户自己的 Codex 默认设置，**仅用于选择任务和确认前规划**。
选定后在任务配置中自行修改 planner/author/reviewer，再以 `--task` 重开。
有 task 时从文件和已确认数据库快照交叉验证 runtime，传递 `--model` 与
`model_reasoning_effort`；不允许 CLI 的 model/profile/config 参数再覆盖它。
worker 的实际 runtime 仍由 runner 的真实回执校验，不由启动器保证。

启动先检查 Python 核心模块、Codex 的实际 `--help`、本地 Node/Marp 版本和绘图库。
核心模块/Codex/指定任务错误会直接退出；渲染依赖未就绪会明确告警，但不拦截初始规划。
生产前完整 `toolchain doctor` 仍是必要检查；预检不是浏览器验收。
无终端环境不会偷偷改用非交互模型调用，脚本请用 `--check` 或 `--cli`。

`PYTHON_BIN`、`CODEX_BIN` 都是一条可执行文件路径，不是含参数的 shell 命令。
源码启动优先导入本目录 `src`，可从其他工作目录调用，路径中含空格也受支持。
退出码与终端保留；POSIX 使用 exec 传递中断信号。老的 `start.sh workflow ...`
形式仍兼容，但新文档统一使用 `--cli`，避免误认为它会开启工作会话。

## 1. 完整流程：每一步做什么

| 步骤 | 执行者与工作方式 | 当前实现 |
|---|---|---|
| 需求与课程规划 | 用户和规划 AI 确定听众、先修、按第几节课组织的 brief、核心与补充内容 | 用户入口和校验已实现 |
| 展示、确认配置 | 程序展示三份入口；用户明确确认后保存不可变配置快照 | 已实现 |
| 创建作业 | 从已批准 plan item 生成数据库 job ID、依赖和课次坐标 | 已实现 |
| 容量准入 | 宿主实际 inventory 与用户上限取更严格值；预算作者、五 reviewer、编辑者和恢复余量 | 已实现 |
| 历史反馈回顾 | SQLite 保存用户原话、问题表现、验收期望；每次作者/编辑/reviewer 开工先短回执，随后才派发内容执行 | 已实现 |
| 写作与提交 | runner 注入只读项目主题；接收 Markdown/外部资产，在入库前拒绝作者 CSS/HTML | 已实现 |
| 单元源码门禁 | runner 下次 tick 对新修订运行源码、TeX 和资产边界检查 | 已实现 |
| 整稿组装与语义编辑 | 程序组装，短时编辑作业判断叙事与教学衔接，不设常驻 coordinator | 已实现 |
| 完整机械门禁 | 指定源码修订 → 临时 HTML/DOM → 数学渲染 → PDF 结构和文本边界检查 | 已实现 `artifact inspect --level full` |
| 冻结与专项审核 | 五个不同且独立的 reviewer 阅读同一冻结稿；不做模型型审核协调 | 已实现 |
| 修订与再次门禁 | findings 送给作者，生成新修订；旧稿门禁不能批准新稿 | 已实现 |
| 用户指定返修 | 交付后先只读展开问题形式与相似问题 → 展示精确方案 → 等用户确认 → 仅修改指定稿件 → 重走审核发布 | 已实现 |
| 发布、目录交付与暂停 | 私下保存准确发布修订；自动将 PDF、同名 Markdown 与资产直接放入 deliverables；按 all/pilot/each 继续或暂停 | 已实现 |

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

教学选择与运行选择分开。新任务 task.yaml 增加 `teaching.audience` 和 `teaching.proof_depth`，
默认面向非数学专业、重动机/计算/直观，proof_depth=minimal。用户在确认前可选 explanatory
（必要短推导）或 rigorous（证明训练）。规范术语、准确含义和必要条件始终要有，不意味着
所有正确证明都必须上屏。这两个字段是备课信息，不能原样变为学生“先修/目标”页。
旧确认没有 teaching 字段时不填默认、不修改确认快照；继续读取原任务和最新明确反馈。
`task present` 显示 teaching_context 及有限的 teaching_conflicts 提示（包含位置与原文），
帮助发现“minimal”与“保留全部证明”等冲突。提示不是完整语义冲突判定器，也不是新门禁；
规划者须在确认前实际解决意见冲突，不能由技术升级暗中改写教学授权。

## 3. 代码如何组织

```text
src/mpres/
  startup.py                   只读启动检查、task planner runtime、交互终端与 Codex 进程
  cli.py                       默认新入口；显式 legacy 才加载旧入口
  control/
    cli.py                     参数解析和结构化输出，不包含语义判断
    schema.sql                 关系、外键、唯一约束和不可变配置
    migrate_*.sql              旧 schema 的原子增量迁移
    store.py                   短事务、查询、一致性数据库备份
    service.py                 确认、作业、绑定、提交、usage 和状态
    runner.py                  实际宿主证据、池准入、领取、输入包、JSON 适配器
    quality.py                 源码/full gate、修订绑定、并发幂等、失败与恢复
    recovery.py                有界只读重试策略和明确的工具错误分类
    audience.py                同一 reviewer 的学生阅读、制作口吻检查及最终汇总
    workflow.py                固定整稿状态机、组装、审核证明、finding 处置、发布
    repairs.py                 问题展开、方案版本/确认、指定返修、历史发布与目标目录视图
    feedback.py                用户反馈版本、开工回执、结果证据和旧审核失效检查
    teaching_feedback.json     本项目用户明确指出的四项教学质量底线，自动进入任务数据库
    delivery.py                按已提交 release 配对 PDF/源码/资产，直接目录、校验与恢复
    theme.css                  唯一权威全局主题；由代码维护，author/editor 均不得改
    semantic.py                四个语义 schema、教学设置与学习价值标准；每类作业注入对应指南
    schemas/                   plan、author-result、review-result、diagnosis-result
    files.py                   安全相对路径、只读快照、可写副本
    migration.py               旧任务只读导入
  geometry.py                  同一数学定义求解、验算、绘图及资产/生成脚本一致性检查
  source_policy.py             全项目 Markdown 子集、主题所有权、统一渲染参数；无任务豁免
  marp_source.py               Marp 解析、内容 lint；compact 不要求旧过程记录
  html_layout.py              临时 HTML + DOM 几何检查；canonical ID 优先
  math_inspection.py          TeX 结构与渲染节点检查，不证明数学正确性
  pdf_inspection.py           页数、字体、文本、边界和异常字符检查
  rendering.py, toolchain.py  复用固定 Marp 命令和版本校验
  runtime_profile.py          固定配置解析
  legacy_cli.py, ...          旧任务兼容实现，不得向新任务另建状态

templates/compact/            三份用户配置模板
.agents/skills/               仅六个语义 skills；旧管理 skills 已删除
scripts/                     显式安装、静态验证；启动器启动交互 Codex 或显式转发 CLI
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
  deliverables/
    p01/
      p01.pdf                   当前已发布 PDF（Git 忽略）
      p01.md                    同版源稿，直接阅读／版本控制
      theme.css                 同版项目主题
      assets/                   图片、绘图脚本与数据
    p02/                        后续已交付课件；未交付不生成
  .mpres/
    task.sqlite3                唯一运行事实源
    artifacts/<revision>/       已提交或导入的只读源码与资产
    work/<attempt>/             本次输入快照和可写 output
    gates/<gate-id>/             完整检查生成的 PDF
    releases/<presentation>/    不可变的各次发布 PDF；用户通常只读 deliverables
    delivery-staging/            目录发布暂存／中断恢复，不入 Git
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
teaching:
  audience: 非数学专业学生，重视问题动机、计算和直观理解
  proof_depth: minimal  # minimal / explanatory / rigorous；确认前由用户选择
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

适配器必须真实实现五种请求：

* `brief`：与内容作业使用同一固定 runtime、同一 session，先返回 receipt、runtime、usage 和
  readback（每项 id/version/approach）。此时没有可写内容目录；全部回执接受后才派发 `run`。
  不支持此操作的旧宿主需适配，不能自动跳过。
* `capabilities`：返回 handle_limit、handles、supports_close、supports_reset、
  usage_reporting 和 receipt；它们来自宿主，不是复述 task.yaml。
* `create`：输入 request_id、slot_id、runtime；返回实际 handle、model、
  reasoning_effort、receipt。相同请求应幂等。
* `audience_step`：在 audience 首次审核中分段完成学生阅读和制作口吻检查，回传精确页范围、引用、findings 与真实 usage；见下文分步协议。
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

### 默认主题：用户提供的 Gaia／lead 风格，项目全局固定

权威文件为 `src/mpres/control/theme.css`；`themes/mathist-academic.css` 是相同字节的
兼容副本。Markdown 注册名继续为 `mathist-academic`，避免把已有 task 的主题名改成
另一份配置。渲染命令显式指定项目主题，作者不能在 frontmatter 加 `style` 或选择别的主题。

外观以用户提供的 `1-1.md` 主题为准：Arial／Microsoft YaHei 优先，缺少时回退
Noto Sans CJK SC；正文 **24px／1.6** 行高；h1／h2／h3 为 **36／30／26px**；
白底、蓝灰标题、h2 蓝色下划线、红色粗体强调。页面整体采用 Gaia `lead` 风格居中，
列表和表格单元格保留适合顺序阅读的对齐。由 CSS 全局实现，不要求作者逐页加 class。

项目主题是**自包含的兼容实现，不直接导入 Gaia 在线字体**；没有字体下载、远程样式
或背景依赖。外观不应依赖教师电脑能否联网。字体只按系统可用字体回退，源码包不附带字体文件。

为修复真实 v7 第10页和“标题＋单图”的通用问题，主题还明确规定：

- 表格使用折叠的 **2px 实线边框**，单元格上下 **10px**、左右 **16px** 留白，浅蓝表头；
  不依靠浏览器默认间距把相邻公式分开，也不整体缩小表格字体。
- 16:9 页面固定 1280×720，border-box 计量，padding 为上48、左右64、下52px。
  标题／段落／列表有明确 margin；页码定位相对本页，不相对整份网页。
- 外部图片上限 460px／100% 宽，保留纵横比；纯图片段落没有行内基线造成的空白行。
  图片规则只选择 `img`，**不选择 MathJax 的 SVG**。过满正文仍会溢出并被拒绝，不自动缩字。

用户给出的 `.columns`、`.center`、`.small`、`.warning`、`.success`、`.formula`、
`.quote-large`、`.quote-middle` 规则保留在全局 CSS，作为项目组件的兼容样式。
**保留 CSS 类不等于开放正文 HTML 或任意 `_class`**；正常作者仍只用受限 Markdown
和 `core/support` 机器标记，不得用这些类绕过固定布局。

#### 旧稿、新稿与主题升级

旧 artifact／旧 PDF 不会被覆盖。新作者工作区由 runner 安装当前主题；新提交只能省略
主题文件或提供精确项目副本。旧主题不会被“当作作者自定义 CSS”自动改写进原 artifact。
创建新的编辑 attempt 时从旧 Markdown 与资产接续，主题由 runner 提供。

本版 source policy 从3升至4，因此旧成功 gate 不能批准新主题；新修订必须重新检查。
**这不是完整旧任务兼容升级**：v7 本地补丁、图示 renderer v2/v3、review-first 返修和
已有作业的全面迁移仍待后续 v0.7.x。不要把本版主题升级当成整个 p01 已完成返修。

#### 如何验证主题

源码检查：`mpres source check <source-directory>`。完整原生主题回归：

```bash
python scripts/verify_theme.py --output /path/to/new-theme-evidence
```

该脚本使用实际固定 Marp 4.5.0、Chromium 和 MathJax，以五页受限 Markdown 样稿测试
真实 v7 公式表格、标题＋计算图＋图注、多行矩阵、普通表格、列表与代码。输出只在指定的
新目录，不读写任务。缺少 Marp 时明确失败，不使用假的 PDF 或自动调整主题通过。
它不是模型视觉 reviewer，也不为作者修复增加审核轮次。



作者只交 `presentation.md` 和实际引用的外部资产；`theme.css` 由 runner 预置只读副本。
省略 theme 时程序在新快照内补齐，不改作者原稿；带入主题时必须与项目版本逐字节相同。
任意其它 CSS/SCSS、raw HTML、页面样式或自动 Marp 配置文件都会在**接受修订之前**被拒绝。
不是把违规片段默默删除，也不是渲染失败后再请作者改主题。

### 全项目表达约束

全局主题位于 `src/mpres/control/theme.css`，字体、字号、页边距、图示边界属于代码。
`core/support` 是仅有的语义页面类型，不开放额外 class。内容过满就删冗余、拆推导、
拆宽表、分离题目和答案或新增页；不缩字、挪公式、拼主题或把正文做成图片。
主题确有缺陷应在项目维护版本修正，不在课件任务中按页面修补。

本项目采用受限 CommonMark + 表格 + 数学子集。CommonMark 自身允许 HTML，本项目
故意不允许：HTML block、inline HTML、内嵌 SVG、div/span/style/img/br 均禁止。
外部 SVG/PNG 等可用标准 Markdown 图片引用；图片 alt 不得使用 Marp 的大小、背景、
滤镜指令。数学中的尺寸、CSS 注入、宏定义指令也禁止；标准数学字体、矩阵、定界符
和常规数学间距不受影响。可见教学内容不能混入制作回执。

机器元数据只接受如下封闭注释，代码围栏或反引号中的 HTML 示例属于教学字面量：

````markdown
---
marp: true
theme: mathist-academic
paginate: true
size: "16:9"
math: mathjax
---
<!-- slide-id: p01-l01-s01 -->
<!-- _class: core -->
# 两条直线的公共解

$A\mathbf{x}=\mathbf{b}$ 的解需要同时满足两行方程。

![两条直线及其计算得到的交点](assets/l01/intersection.svg)

---

<!-- slide-id: p01-l01-s02 -->
<!-- _class: support -->
# 代回原方程检查

把求出的点分别代入两个方程。
````

分页使用顶层 Markdown 分隔线；代码围栏中的 `---` 不会拆页。标题与公式需要具体含义。
frontmatter 只接受上述固定布局值，以及 title/description/author/keywords/lang 描述元数据。
不提供 task.yaml 或 runtime profile 开关来放宽这些全项目规则。

### 计算式几何图：数学数据 → 验算 → 资产

数学图的点位属于工具计算，不属于 author 的像素布局。`geometry.py` 提供三个
小型、固定样式的生成器：`lines`（两直线，含垂直／平行／重合）、`projection`
（向量到过原点直线的投影）、`transform`（二维矩阵与一至四个向量）。
它们用有理数计算，曲线、标记和数值标签共用结果；投影验算正交残差。
Matplotlib 在一个数据坐标系中绘图，并采用等比例坐标，不能通过 spec 传 CSS、
像素点或预写的“正确答案”。

```bash
# 首次安装时启用绘图依赖；不在任务运行中隐式安装。
python scripts/bootstrap.py --with-figures
mpres figure build examples/computed-figures/intersection.plot.json
mpres figure check path/to/output
mpres source check path/to/output
```

数学输入例如 `{"version":1,"kind":"lines","lines":[[1,1,2],[1,-1,0]]}`，
表示 `x+y=2` 与 `x-y=0`。生成同名 `.svg` 和重建入口 `.py`。将三者一起放进
`assets/<unit-id>/`，以普通 Markdown 图片引用 SVG。它们都是可复现的内容资产，
不是需要 agent 维护的过程文档；直接交付目录保留整个源码快照，因此三者一起交付。

源码提交和 gate 重算 `.plot.json` 并比较规范化 SVG（不使用额外文件 checksum，
不执行作者脚本）。改了数据未重新出图、手工挪动标记、缺少重建入口都会失败。
图示工具不证明教学概念选得正确，也不把任意外部 SVG／照片冒称为验算通过；
未支持的图种仍需有明确数学来源与作者工具验算，首次语义审核保持不变。
切换 Matplotlib 版本造成生成差异时，重新运行配套脚本，而不是放宽规约。

### 检查怎样运行

```bash
mpres source check path/to/output                  # 无需任务、模型或 Marp 即可检查表达契约
mpres --root . artifact inspect economics REVISION_ID --level source
mpres --root . artifact inspect economics REVISION_ID --level full
mpres --root . artifact gates economics REVISION_ID
```

`source check` 以 Markdown token 区分代码、数学、图片和 HTML，而不是把小于号或字面
HTML 示例一律判错；它不等于完整 source gate。后者另查 stable ID、core/support、密度、
TeX 拼写/嵌套环境、图像路径和资产边界。full 再执行固定 Marp、HTML/DOM、数学节点和
PDF 结构检查。实际渲染忽略工作目录 Marp 配置，关闭作者 raw HTML，并强制使用项目
theme、尺寸和 mathjax。渲染器内部产生 HTML/MathJax SVG 不受作者 HTML 禁令影响。

同一稿各 lesson 的主题不再合并；只复制内容资产，并安装一份项目主题。
DOM 页面与数学报告按页序、页数对应 canonical slide ID，避免数字 DOM ID 隐藏真实页号。
正确嵌套的 aligned/bmatrix 使用栈式匹配，不再把 begin/end 列表顺序不同误判为错。
这些检查不证明数学结论正确，也不依赖视觉模型纠正 PDF。首次五通道语义审核保留；
审后由作者自修并通过机械门禁，本版本没有增加 reviewer 验收修复的轮次。

检查和模型调用在 SQLite 写事务外运行。报告绑定源码修订和 source-policy version；旧版
通过记录不能批准新规约的发布，要重新检查。更换稿件生成新修订，不覆盖旧源稿。
要明确重跑工具可加 `--retry`，保留旧结果。仍在 running 的检查不重复领取；确认原进程
已经停止后使用：

```bash
mpres --root . artifact interrupt-gate economics GATE_ID --reason "已核实原检查进程停止"
mpres --root . artifact inspect economics REVISION_ID --level full --retry
```

已有历史 PDF 和旧 ZIP 不会自动重写。旧任务若含自定义主题、HTML 或单页样式，继续
编辑/发布时会被明确拦截；需由作者保留教学内容、改为受支持的 Markdown/外部图，再
形成新修订。不能通过 legacy 入口或复制旧 gate 绕过规则。既有配置/runtime 不会被覆盖；schema 6→7 仅增加分步阅读表。

### 正常错误怎样自动恢复，什么时候才停

`runner` 不从报错文字猜测用户授权，不增设恢复模型。处理按已知事实分流：

| 情况 | 运行器的动作 |
|---|---|
| 本地浏览器确认为 TargetClosed，或检查子进程超时 | 同一不可变源码重新跑检查；不创建作者、不消耗修稿额度 |
| Marp/依赖缺失、未知检查器异常 | 明确标记环境故障；不命令作者改正确的数学去迎合检查器 |
| 内容已确实执行并回传 receipt/runtime/usage，但结果 schema 或源码契约失败 | 原 attempt 记为 failed，保留用量；同一 job 开新 attempt，给固定配置作者原稿和精确错误 |
| 普通源码/full gate 报告真实内容问题 | 沿既有作者自修链处理，仍使用既有有限修稿预算 |
| host inventory 缺失或过期 | bridge 返回只读 capabilities 请求；command 自动刷新真实观测 |
| 新 inventory 与已知 live handles 矛盾 | 要求对账，不擅自认为旧句柄已关闭 |
| create/run/brief 的回执丢失、runtime 不符、缺少承诺的 usage | 保留不确定状态，不能盲目重发外部执行或伪造完成 |
| 语义范围、权限、反馈仍未解决或预算耗尽 | 明确待决；不改 runtime、不放宽主题/HTML/门禁规则 |

同一 `task.yaml` 可在确认前设定：

```yaml
max_attempts: 2
recovery:
  transient_tool_retries: 2
  host_observation_retries: 2
```

两项 recovery 值接受 0..3，省略时各按 2；没有新配置文件。
`max_attempts` 限制同一 job 的总内容执行次数，源码契约拒绝也消耗次数；原有单元修正
与整稿 gate 修正预算同时保留。工具重试另计，已经失败的 durable gate 行使下一次
`tick` 不能重新获得一份自动预算；并发运行器也不能倍增重试。0 表示不自动重试。
重试不会删除旧失败记录或变更已确认配置。

已完成的错误源码保存在原 attempt 工作区，下一次派发只复制相关正文/资产并说明
精确契约错误。不是自动删除违规片段，更不是执行作者提交的脚本。修正生成新 attempt、
需要新的真实回执和 usage，并再次通过正常门禁；不会新增 reviewer 验修轮次。
目前这一自动重交路径只适用于作者类结果 schema 和源码契约，语义争议、越权路径、
错误审核证据与第三方协议异常不会被当成可无限重试的普通格式错误。

如果先前因环境问题阻断完整检查，安装工具后 `workflow retry-checks` 现在也可在发现
真实内容问题时恢复到原检查阶段，由既有作者修正链接手，而非再次要求用户决定。
它不把失败 gate 改为通过，只关闭与本次恢复的原 phase/reason 精确对应的一条决策。

### pilot 与容量预留

pilot 首次反馈之前，只预算首个目标稿件的 runtime 池；each 只预算当前稿件。
已确认返修优先使用本次选定目标；all 或 pilot 已获用户继续确认后，才考虑其余任务。
任何已经创建的池与真实句柄仍占容量，不能因为范围缩小就从计数中抹去。
每个当前稿件的五名 reviewer、编辑者与恢复余量仍提前预留，实际作者并发只在用户上限
内调整。容量不足不触发模型降档、假关闭或跳过审核。

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
8. 每次 advance/tick 在已提交发布之后同步配对目录。只使用 committed releases；
   不扫描工作草稿、不运行模型或重新渲染。delivery_package.format 为 directory，
   entries 给出每稿现有 PDF 与 Markdown 路径；只有 ready 时才附给用户。

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

### audience reviewer 如何分步试读

首次五通道审核不变，仍用同一个 audience 会话、同一固定 runtime，逐段覆盖整个冻结稿：

1. **学生阅读**：每段最多12页/48KB正文，判断学生正解决什么、具体获得什么、哪里需要
   猜测变量/条件/图形关系；不同时承担其他四个通道。没有正面评价数量要求。
2. **学习价值与制作口吻**（协议 phase 名仍为 production_language）：对每段问“删去后，
   当前数学学习具体损失什么”。不是只查是否自夸。先修/时长/核心字段、孤立引文、
   TXT 行数、方法口号、凭空制造的误会都应主动质疑。
3. **历史反馈对照与汇总**：结合前序具体问题给最终 findings，不能无声丢掉已提出的问题。

程序使用 Markdown 解析器提出 `attention_candidates`：跳过代码/数学字面量，只标记常见
待判断片段，不按关键词删改或判错。这些不是穷尽清单；模型还要判断未命中的无价值内容。
有候选的第二步须返回 `attention_checks`，逐项写 keep/remove/rewrite/move_to_notes、
删除造成的具体学习损失及理由；需删改的项必须指向本步 findings 数组中对应页的 finding。
“不是自夸/属于教学内容/可以避免误解”不能单独充当保留理由。必要假设、模拟数据披露和
事实出处可以保留，但要说清它怎样影响当前模型或判断，不能用抽象标签保护任何一句话。

这些判断和中间 usage 仍入 SQLite 的 audience_steps，没有新增表、独立 reviewer 或过程
Markdown。只增加已有 review-result schema 的可选子结构；新请求在有候选时明确要求它。
宿主适配器按 packet.result_schema 生成/转发结果；operation 仍是 audience_step，无新工具名。
程序能检查是否答题、是否有原文和是否形成可修订 finding，不能证明模型判断一定正确。
它不会自动为作者删字，也没有增加修订后的 reviewer 验收。

每个新试读 attempt 在 events 中固定 `audience.contract` version=2；旧版已经派发的步骤
没有这个事件时按原协议接收，不用新字段追溯拒收真实旧回执。旧 completed 记录也不会被
补造成已经做过新检查。最新反馈仍会使旧审核不再自动满足新的发布条件，需要新审核路径。
开工前已回顾历史反馈，所以这不是认知盲测或真实学生实验；隔离的是作者自证，不是假装
会话忘记已知内容。

### 直接交付目录：不再要求解压才能看源码

```text
tasks/<slug>/deliverables/
  p01/
    p01.pdf
    p01.md
    theme.css
    assets/
  p02/
    p02.pdf
    p02.md
    theme.css
    assets/
```

不自动生成累计 ZIP 或 repair ZIP；同名 PDF/Markdown 来自同一条 committed 发布记录。
内部 presentation.md 不改名，较新的工作草稿不混入；图示、数据与可复现脚本保持相对路径。
新发布的历史 PDF 存在 `.mpres/releases/<presentation>/rNNN/<presentation>.pdf`，
`.mpres/artifacts` 保留准确源码修订。公开目录是可重建视图，不是数据库之外的第二真源。

all/pilot/each 的已交付部分都得到配对目录。没有 committed
发布时不生成目录，prepared PDF 不公开。后续返修成功才将该稿公开目录更新到新版本；
未选中的稿件不动。旧任务根目录已有的 PDF、ZIP 保留，不擅自删除，也不再更新 ZIP。

```bash
# 为已有 SQLite 任务补出源码和资产，或核对现有目录；不调用模型/渲染器。
mpres --root . workflow materialize economics
mpres --root . workflow status economics
mpres --root . task status economics
# 旧 workflow bundle 是兼容别名，现在同样只生成目录，不压缩。
```

`delivery_package` 保留字段名以兼容宿主，但 `format` 已为 `directory`，`path` 指向
`deliverables`。宿主应使用 `entries[].pdf`、`entries[].markdown` 展示实际文件，不能
假定 path 是一个 ZIP。状态 ready 表示视图已完成；复制失败时 runner 返回 blocked，
即使数据库的 PDF 已 committed/completed。修复磁盘／路径问题后 materialize 即可，
不重做写作、审核或渲染。

目录先在 `.mpres/delivery-staging` 完整复制并按字节验证，再核对最新发布集合、
按稿替换完整目录。同一稿不会把 PDF 与另一个修订的源码混在一起；不同稿不是一个
跨目录原子事务。进程在两次 rename 之间中断时保留 previous 目录，重跑会收敛；
数据库与文件系统不是同一个事务。目录缺失可重建；同名位置有用户手改内容、额外文件或
符号链接时拒绝覆盖。先保留/移走个人改稿，再生成发布视图；不会擅自删掉这些编辑。

`.gitignore` 不忽略 deliverables，也不使用全局 `*.zip`。PDF 和交付目录中的 ZIP
被忽略，Markdown、CSS、SVG/PNG、绘图脚本和数据可进 Git；已被跟踪的二进制文件
仍需用户决定是否取消跟踪。显式 legacy 旧入口没有被改造成新控制面。

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

交互与机械入口分开：`./start.sh` 进入 Codex；`./start.sh --cli runner run economics`
只运行控制命令。Windows 使用 `start.cmd` 或 `start.ps1`。启动器不自动安装、不开日志
daemon、不注入旧长提示、不禁用宿主 approvals/sandbox；任务历史仍由 SQLite 保存。
Linux 的本发布测试实际启动 shell/PTY 并验证 Codex 协议替身的参数、终端、退出码和信号。
没有真实 Codex 登录/模型调用，Windows 未作原生执行；两者都不能被替身结果冒充。

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

除术语、近期实际案例、几何直观三项原反馈外，项目现在增加 `student-learning-value`：
计划字段不自动上屏、证明强度不由“规范数学”推导、删除无学习损失的陈述、来源服务数学
而不是服务验收。作为新的版本化 feedback ID 写入旧任务也不覆盖已有规则或运行配置。
已派发 attempt 的反馈快照保持不变；新作业回顾新要求。不得伪造旧审核已经采用新标准。


聊天上下文不是质量要求的真源。`feedback_rules` 以版本保存用户原话、期望、可能表现、
验收准则和适用课件；`attempt_briefings` 保存本次作业实际收到和回顾的版本。默认内置用户
已经明确提出的四类问题：规范术语、近几年实际生活/经济场景、明示几何直观，以及学生学习价值与制作口吻。
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
  → 新版本 PDF + 对应 Markdown/资产目录；历史修订保留
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

# 独立补出本次选定目标的目录，不重新写作/渲染：
mpres --root . repair materialize economics <case-id>
# 用户不批准时可取消未确认方案（有在途诊断时须先核对回执）：
mpres --root . repair cancel economics <case-id> --by "用户" --note "此次不返修"
```

每个确认的问题变体和相似问题都需要 repair_checks：addressed、not_found 或 needs_decision，
加说明与实际页 ID。仅修举例页却漏掉同类问题、漏项回执、编造页码，会被拦截或交给独立
reviewer。无法判断/缺少来源的内容必须停在语义待决，不把空泛改写当成解决。

### 新旧交付版本与直接目录

`release_versions` 保存历史 PDF、源码、gate 和 case；`releases` 指向各稿最新正式版本。
公开的 `deliverables/p01/p01.pdf` 与 `p01.md` 成对更新。旧 PDF 与原稿修订不覆盖，
旧任务中根目录已存在的 PDF/ZIP 也不自动移动或删除。只有正式发布成功后才替换公开目录。

`repair status` 返回所选稿件的同一目录视图，不制造另一份 repair ZIP。更早 case 已被
后来的返修取代时显示 superseded 和历史 PDF/source 路径，绝不能把老稿覆盖回当前目录。
一个 case 内有多稿时，每稿发布互相独立；整个 case completed 后恢复原任务暂停状态。
在 pilot/each 暂停时返修，完成后不会顺便启动下一稿。

### 边界与部署

本入口服务 compact SQLite 的已交付任务。只有 legacy 目录或一个外来 presentation.md
而没有 compact 发布记录时，不会伪造其已审核状态；应先按原迁移/验收流程导入。
宿主仍负责真正的模型调用、检索与沙箱：项目只提供契约和提交门禁，不声称实现 OS 级隔离。
用户授权由宿主转发，--by 是审计归因，不是认证凭证。没有真实确认，main 不得自动执行 confirm。
规范术语、现实案例与几何直观的质量不能由字符串或 JSON 验证器证明；必须由 reviewer 实质判断。

## 从已发布稿件开始：review-first 返修

新稿仍按前文的写作—组装—整稿编辑—首次五通道审核—作者修订—机械门禁—发布运行。
需要修订已交付课件时，返修有两种顺序：默认 edit-first 保持旧任务语义；显式
review-first 先审核原正式稿，再交由作者处理。模式和结构调整权限进入精确确认快照。

```bash
mpres --root . repair open linear-algebra-v7 --presentation p01 \
  --mode review-first --allow-slide-changes \
  --report "清理制作自述、孤立引文及重复内容；允许删页和合并。" --by "用户提出"
mpres --root . runner run linear-algebra-v7
mpres --root . repair present linear-algebra-v7 <case-id>
# 只有取得用户对已展示范围的真实确认后执行：
mpres --root . repair confirm linear-algebra-v7 <case-id> --version 1 --by "用户明确确认"
mpres --root . runner run linear-algebra-v7
```

open 只授权问题展开；present 展示模式、目标修订、非目标、验收条件和删页权限。
confirm 后，review-first 从匹配的历史发布记录读取原 Markdown、PDF，不创建前置
editor，不重写六课。旧主题的历史发布证据不等于当前规约下的 gate 通过；缺少匹配
发布记录、源码或 PDF 就阻止操作。五个独立通道的结果只按本轮归集，旧 findings
与旧反馈快照不混入新一轮。

审核后一定交给作者形成新修订，即使 findings 为空，也不能把旧稿直接冒充新版交付。
作者新稿须通过当前主题/源码/渲染门禁；不增加作者修复后的 reviewer 验收。
完成后更新配对 PDF/MD/资产目录，恢复原 pilot/each 暂停状态，不顺带启动 p02。

### 删除、合并和稳定页标识

allow-slide-changes 默认关闭；它必须在用户确认的返修范围中启用。
获准后 author-result 可带 slide_changes，每个消失原页给出 slide_id、action
(delete/merge)、target_slide_id（delete 为 null）和具体 reason。保留页面继续
使用原 ID，合并目标须是保留的原页；不得通过全稿更名冒充从原稿修订。
每次机械修正的映射仍累计对照最初原稿，不丢弃前面已经删去的页。
程序检查授权、真实页标识与映射完整性，不宣称自动判定教学删改的质量。

### 代码与迁移

control/repairs.py 管理确认、历史发布证据与结构改动；workflow.py 通过
presentation/frozen revision/review round 查询本轮 findings 并推进流程；runner.py
注入一致的范围与证据；feedback.py 只检查本轮反馈快照。
SQLite schema 8 在 repair_cases 增加 mode、allow_slide_changes 两列，不增加管理表或
过程文档。旧任务首次打开自动增量升级，配置、runtime、usage、旧发布文件不变。
已在运行的旧返修继续 edit-first/不可删页。尚未确认的旧方案可重新 present 后确认，
不隐含取得新权限。DB 备份仍使用 SQLite backup，不复制正在运行的单个文件来猜快照。

## 输入编译：完整正文与按需资源

runner.packet 调用 control/input_packet.py，把模型输入分为两层：
input_files 是必须完整阅读的文字（包含整份稿件和数学 .plot.json），resource_manifest
是可按需取用的图片、PDF、项目主题、生成脚本与本课已批准的教材摘录。不能截断正文，
不能因为资源列在清单里就声称看过它，也不能自动把所有 SVG XML/教材全文塞回初始 prompt。
图示相关判断仍需读取相关图片/数据，来源相关判断需核对相应摘录；读取不可用时报告证据缺口。

单课作者仍收到指定教材作为必读文本。整稿编辑、审核、修订和诊断会继承该课件在已
确认计划中的教材依赖，按课件/配置去重，并创建只读输入快照；不会继承其他课件的资料。
输入路径限于任务内的普通文件，拒绝软链接、越界、丢失材料和在派发后变更的参考快照。
生成脚本是可读资源，不获得隐含执行许可。控制面不会为通过预算而修改已确认配置。

宿主适配器应遵守 input_policy：先读完 input_files，通过工具按需要取得资源；
不要沿用“把所有 path 都转换成全文”的旧封装。后续工具读取照实记录 usage。
context_bytes 只表示初始必读输入估计，attachment_bytes 表示资源体积，不是已省下的 token。
audience_step 使用同一规则，但正文仍是原来的有界逐段 slides，不加入整份 PDF。

## 旧图示进入新作者工作副本

新 editor/revise attempt 首次准备输出时，`control/files.py::prepare_edit_source` 将
presentation.md 和 assets 复制到暂存目录，按 `.plot.json` 重新计算、生成并检验 SVG，
补入当前只读主题，再整体发布为该 attempt 的 output。提交仍执行完整源码及图示检查。
已存在且非空的 output（包括作者尚未提交的修改）不会自动刷新；本功能不覆盖进行中的草稿。
如旧草稿的图来自另一个绘图库/字体环境，应由作者在自己的工作副本对对应 `.plot.json`
运行 `mpres figure build`，不能复制历史 SVG 回去或删除数据来躲过校验。

接受项目已实际使用的输入版本 1、2、3：v1 为原有三类数学图；v2 从同一数学定义计算
直线截距并标注；v3 只用于直线图，改善横轴截距标签分离。版本不是允许作者注入样式的开关。
方程、向量、矩阵和版本外的字段仍被拒绝；未知版本不自动降级。版本2/3也必须有配对数据和
可复现入口。程序绝不执行归档中的作者 Python，而调用项目生成器。

原发布图、源码、PDF 与原 gate 不修改。不同 Matplotlib 或字体环境造成的 SVG 差异，
通过在新工作副本重新生成解决，不通过忽略几何/文字/颜色差异来“认证”旧图。历史 review-first
仍看原发布证据；作者新稿和新图才进入当前机械验收。没有增加模型调用、reviewer 或过程模板。

本版仍未内置并验证所有本地 Codex bridge 补丁。真实模型返修与固定 Marp 端到端验收
需在实际宿主完成；这些功能测试不能声称已经改善原 p01 的教学质量。


对 v7 的实际七个数学图已在独立工作副本完成真实 Matplotlib 重生成和核验。
该稿还残留九处旧的 `h:...` 图片尺寸指令；准备报告将这些原文位置交给作者修正，
不会重新开放局部版式、静默删正文，或假称整个旧稿已经通过新源码规约。

## 实施与验收边界

已接通原稿先审、授权删页合并、完整正文/按需资源，以及旧数学图在新工作副本中的重生成。
真实 v7 的本地 bridge、实际执行回执和故障恢复仍需在宿主联调。本版没有实际调用模型
修订 p01，没有重新生成原 p01 PDF。新工作副本不是已验收交付，作者必须修正现存源码
规约问题，新稿必须通过完整门禁；旧证据始终保留。

宿主与完整渲染回归使用明确标记的测试适配器。Matplotlib 数学图重生成采用真实工具。
真实模型质量和固定 Marp 生产链仍需部署环境验收，不把资源清单编译成功或 SVG 生成成功
当成完成整份返修。程序不执行源稿携带的 .py，不因此关闭沙箱或动态调整模型。

旧 legacy maintenance 只把独立作者工作副本恢复为可写，原发布证据保持只读。
启动器 PTY 测试替身先安装信号处理器再报告 ready；生产启动器的信号要求未放宽。

## 最近阶段

v0.7.5：受控支持数学图版本1/2/3，在新作者副本生成并检查；保留进行中草稿和原发布证据。
v0.7.4：完整正文必读，资源按需，整稿继承已批准教材依赖；不增加预算或管理文档。
v0.7.3：先审原发布稿，允许确认范围内删页/合并，按本轮审核隔离 findings。
v0.7.2：学生注意力标准；v0.7.1：直接目录交付；v0.7.0：默认主题。
保持六个语义 skills、四类语义结果 schema、三份用户配置入口和 SQLite schema 8。
