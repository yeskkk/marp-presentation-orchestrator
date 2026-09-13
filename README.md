# Marp Presentation Orchestrator

将用户确认的教学计划转化为可维护的 Marp 课件。**AI 负责教学判断；Python runner 负责作业、检查和发布；SQLite 是运行事实的唯一真源。**
不是让 main 读完一堆过程文档再决定下一条命令，也不是把“生成 Markdown”当作“完成交付”。

## 1. 先选择正在做的事

| 目的 | 使用路径 | 不要混入的流程 |
|---|---|---|
| 新建课程 | 规划 → 确认 → 写作 → 组装/编辑 → 门禁 → 五通道审核 → 作者修订 → 交付 | 不先建立返修 case，不生成六阶段文档 |
| 继续已有任务 | 查询数据库与真实宿主状态 → runner 继续 | 不重新初始化、不重写原稿、不凭聊天记忆猜状态 |
| 返修已发布课件 | 问题展开 → 用户确认 → `review-first` 或 `edit-first` → 交付并恢复暂停 | 不把初始投诉当成批准全部方案，不自动启动未选课件 |
| 修复工具/提交错误 | 根据已知错误走有界恢复或对账 | 不开启语义复审循环，不伪造完成，不增加配置豁免 |
| 导入文件制旧任务 | 只读导入 → 补齐计划并确认 → 重新验收 | 不能继承旧 gate 成功或把旧 handle 当成活会话 |

流程详情在 [WORKFLOWS.md](docs/WORKFLOWS.md)。通常只需阅读当前这一行的流程，
不要同时执行新建、返修和迁移三套步骤。

## 2. 怎样开始

```bash
python scripts/bootstrap.py --with-figures
./start.sh --check
./start.sh                         # 交互 Codex：选择任务或确认前规划
./start.sh --task economics        # 每次本地询问是否修改 TASK；采用已确认 planner runtime
./start.sh --cli task status economics
./start.sh --cli toolchain doctor
```

Codex 需在部署机器单独安装和登录。启动器保留终端、退出码、中断信号、审批和沙箱；
不会替用户登录、关闭安全策略或在任务运行中临时安装依赖。也可进入本目录手动启动 Codex，
使用同一份 [AGENTS.md](AGENTS.md)。Windows 入口为 `start.ps1`/`start.cmd`。
`--task` 选择项目任务，不默认执行续跑，也不猜测某个 Codex conversation ID。

Python 3.11+；原生完整门禁需要项目固定的 Marp CLI、Node.js、浏览器和相应依赖。
`--check` 能开始规划不等于原生渲染就绪；`toolchain doctor` 会真实检查，不用替身冒充成功。
[安装、日常命令和恢复](docs/OPERATIONS.md) · [宿主适配器协议](docs/HOST-PROTOCOL.md)


### 2.0 每次交互启动先选择，不以空输入默许续跑

选择任务后，启动器本地询问 `[1] 修改/先规划任务要求 [2] 不修改，进入会话 [3] 退出`。
没有 `--task` 时可先选择现有任务或新建；没有任务时进入规划，不伪造 TASK。
每次进程启动重新询问，不复用上次答案；EOF、中断或取消不启动模型。
`--check`、`--cli` 和直接 `mpres` 查询不询问，也不要求终端。

修改分支允许磁盘 TASK/设置处于未确认或语法待修状态，但采用数据库中的**原已确认模型与强度**。
启动器本身不改数据库、不覆盖文件、不提交新授权；没有 confirmed runtime 的草案不能凭空猜一个。
“不修改”分支仍要求磁盘输入与确认快照一致，遇到差异明确停止，不能悄悄接受。
本地选择随启动提示传给 main，不再重复问一次；手动进入 Codex 时 main 承担这一询问。
它只确定本次对话方向，不恢复/取消已经在外部运行的作业，也不批准新批次、权限、预算或 TASK 变更。
生产派发仍经过原有确认与状态门。旧任务政策修订和精确 p02/p03 批次迁移尚未在本阶段实现。

### 2.1 任务上下文只建立一次

启动后先确定用户要新建、修改还是继续，不自动开工。main 和手动角色在任务与当前方向
确定后，开始实质工作前完整读一次 TASK.md；不能以角色指南代替用户意图。
已读的同一会话直接复用，只应用后续明确变更，不因换 job、纠错、分段试读重复全文阅读。

runner 将精确确认文本放入首个语义请求的 `task_context`，阅读顺序为任务→角色指导→
本次工作与反馈→内容。正常有历史反馈时是已有 brief，没有反馈时是已有 run 或首个
audience_step；不新增一次模型调用。TASK 不放进按需附件、不截断，全文计入既有预算。
成功的真实回执会记下本 session 的上下文接收记录；以后只传 `reuse` 提示，不重发全文。
这是对宿主执行协议的记录，不是证明模型理解了任务，也不是让模型写另一份“已阅读”报告。

runner 重启不会清空记录。新真实会话需要自己读一次；旧版在途请求不追溯造阅读记录，
其下一次新请求建立上下文。`apply_delta` 仅针对已有正式配置版本变更；它不提供新授权
或跳过确认的入口。会话上下文真的丢失时应如实对账，不能伪称记得；当前 runner 不自动 reset。

## 3. 完整生产流程及每一步的边界

| 步骤 | 输入与处理 | 产出／交接 |
|---|---|---|
| 规划 | main 根据受众、教材摘录、历史反馈安排课次；解决证明深度等冲突 | `TASK.md` 总边界、`task.yaml` 每课 brief；不是学生页文案 |
| 确认 | 程序展示三份入口，用户明确确认 | 数据库不可变配置快照；只有用户选择 runtime |
| 准入和领取 | runner 查询真实容量，保留五 reviewer/编辑/恢复余量，按依赖领取 job | 精确 attempt 与 session；并发只是上限 |
| 开工回顾 | 首次请求提供 TASK 全文；已有会话复用。`brief` 携带本次反馈，readback 后才发 `run` | 回执与 usage 入库；不向学生展示回顾声明 |
| 单课写作 | 本课 brief、必读资料、固定主题；只写 Markdown 与资产 | 新 artifact，经源码门禁；失败回到有界内容修正 |
| 组装与整稿编辑 | 程序拼接合格课次；短时 editor 处理衔接、符号、案例与叙述 | 整稿候选；没有常驻 author-coordinator |
| full gate／冻结 | 指定修订执行源码、图示、HTML/DOM、数学和 PDF 结构检查 | 冻结证据；旧稿成功不批准新稿 |
| 五通道审核 | 五个不同且独立的 reviewer 阅读同一冻结稿；audience 分步试读 | 本轮 findings，不能据机械通过宣称数学正确 |
| 作者自修 | 原候选＋本轮 findings；作者复算、改稿、逐项处置 | 新稿再跑机械门禁；不增加 reviewer 验修轮次 |
| 发布 | 程序核对发布依据，提交准确 PDF 修订，再物化配对目录 | PDF、同名 Markdown、主题和资产；按 all/pilot/each 暂停 |

`workflow: full` 是新任务默认；`authoring` 只写稿。旧确认中缺少 workflow 字段的任务
仍按只写稿处理，不能通过版本升级暗中授予发布权限。
常规无 finding 可直接发布；**review-first 返修即使无 finding 也需作者提交新修订**，
不能把历史发布记录冒充新版本验收。

## 4. 教学判断与职责

数学准确、规范术语、必要条件是底线；不等于要求每个学生学习形式证明。
`teaching.proof_depth` 由用户选择 minimal/explanatory/rigorous。少证明也要说清含义、
说明条件、算对例子；不能把“定义”机械替成“知道”而不解释数学。

学生页只保留对当前理解有作用的内容。**学习损失删除反事实：删去这句后，学生具体失去什么？**
先修清单、时长/核心标签、内部 TXT 行号、无用途新闻、方法口号与“本页已符合要求”
不因为带教学词汇就应保留。真实条件、必要模拟数据披露及事实出处不能误删。
现实资料应参与变量、单位、模型、计算或解释；几何表达必须与公式中的对象对应。

十个语义 skills 分别承担规划、写作、编辑、诊断、资源设计，以及五个对等的独立审核职责：
[数学与领域](.agents/skills/domain-accuracy-review/SKILL.md)、
[教学设计](.agents/skills/pedagogy-review/SKILL.md)、
[学生视角](.agents/skills/audience-review/SKILL.md)、
[语言](.agents/skills/language-review/SKILL.md)、
[信息布局](.agents/skills/layout-review/SKILL.md)。
每个 reviewer 有自己的完整判断方法、证据范围和结束边界，不再从单个 channels 文件取一段提醒。
**.codex/agents 不拆分**：仍使用 specialist-reviewer 定义及 reviewer runtime family，
由已分配 channel 选一个 skill，不修改固定模型与强度的配置结构。

所有角色先依据已建立的任务上下文，再读自己的方法。runner 只注入共同教学边界、一个角色
和当前模式；不会将另四个通道、旧事故示例或维护资料一起加载。
audience 首段取得完整学生试读 skill，后续段只取得当前焦点，最后只综合已有结果；
仍是一个会话，不增加首次五通道审核之后的验修角色。
[角色导航](.agents/skills/README.md) · [语义结果协议](docs/SEMANTIC-RESULTS.md)

规划、写作、编辑和共享原则也已通用化：具体旧题目和事故保留在源码维护测试中，
不作为运行任务必须阅读的方法库。工具能力与执行限制继续由代码和技术契约负责，
不塞进共同教学原则，也不以关键词或篇幅 lint 代替人工审读。

main 处理需求、明确反馈、确认边界、语义争议；健康巡检、容量和登记不需要它重新判断。
author 修内容，不改全局 CSS；reviewer 只提交问题，不代作者改稿；宿主负责真实执行证据，
不能由语义 JSON 的 `summary` 来证明模型调用、门禁或发布成功。

## 5. 配置、内容与运行事实分开放

```text
tasks/<slug>/
  TASK.md                        # 总教学边界与用户确认
  task.yaml                      # 课次计划、教学选择、执行上限
  TASK-RUNTIME-PROFILE.yaml       # 用户固定模型与推理强度
  sources/                       # 已获准教材文本/数据
  content/                       # 实际内容，不是过程表单
  deliverables/p01/
    p01.pdf                      # 当前正式 PDF，Git 忽略
    p01.md                       # 同修订源码，Git 可跟踪
    theme.css
    WARNINGS.md                  # 本次发布的未处理警告，供用户而非学生阅读
    WARNINGS.json                # 同一记录的机器可读视图
    assets/                      # 图片、绘图数据与可复现入口
  .mpres/
    task.sqlite3                 # 唯一运行事实源
    artifacts/                   # 不可变内容修订
    work/<attempt>/              # 有界输入与作者可写副本
    gates/                       # 检查证据
    releases/                    # 历史 PDF
    delivery-staging/            # 可恢复的目录发布暂存
```

不默认生成 assignment 三联单、SELF-CHECK 或 STAGE-ARTIFACT。PDF commit 与公开目录
物化是两个步骤；只有 `delivery_package.state=ready` 才附给用户 PDF 和 Markdown。
自动 ZIP 已取消，`bundle` 仅为目录物化命令的兼容别名。
已存在用户改稿/额外文件时不覆盖；失败后可单独 `workflow materialize`，不重跑模型。
`.gitignore` 跟踪交付 Markdown/资产，排除 PDF/ZIP；已被跟踪的二进制需用户决定取消跟踪。

## 6. 固定表达工具与机械门禁

唯一主题在 `src/mpres/control/theme.css`，兼容副本 `themes/mathist-academic.css` 相同字节。
采用用户 Gaia/lead 风格：正文24px、行高1.6，标题36/30/26px；白底、表格2px边框和明确留白。
**正文适应版式**：删空话、拆推导、拆宽表、分离题目答案，不缩字、不为单页改 CSS。
兼容 CSS 类的存在不等于授权作者使用 HTML/class。

受限 Markdown＋表格＋数学；禁止 raw HTML、内嵌 SVG、自定义 CSS、局部尺寸和 TeX 布局绕过。
外部图片用标准引用，图与图注各占段。机器注释只接受 slide-id 与 core/support。
语法、绘图命令、正反例及门禁差异见 [CONTENT-CONTRACT.md](docs/CONTENT-CONTRACT.md)。

数学图由 `.plot.json` 中的方程/向量/矩阵计算，点线标记共用数据，不能分别手填像素。
`geometry.py` 支持 lines/projection/transform；版本1/2/3按各图种允许范围验证。
新作者副本可重生成旧图示，不执行归档 Python；已有草稿不自动覆盖。
计算一致不证明概念和例题选择正确；机械检查也不代替首次语义审核。

### 6.1 页数、分级和交付警告

规划的 `estimated_pages` 是预计最终页数，包含封面、例题、答案和附录：预计不超过100页，
不是要求写满100页。显式超限的计划可以保存和展示，但确认前要按学习目标拆分，不按教材章强行合并。
旧计划缺少估计时返回 unknown/warning，不能虚构为零或改写已确认计划。

| 检查时点 | 通过／warning／error |
|---|---|
| 预计规模 | <=100；>100需先拆分 |
| 运行中的稿件 | <=120正常；121–130 warning；>130 error |
| 新的正式交付 | <=120；>120 error，不能用草稿 warning 作为发布许可 |

所有底层 mechanical errors/warnings 在 compact 门禁入口归一化；每条保留代码、严重性、消息及已有页坐标。
检查执行失败/未完成与内容 warning 分开。完成的 warning-only 检查不阻塞，明确错误和未知工具失败不会降级。
一份已经正式发布的旧修订不追溯套用新页数规则；这不是对某个名字（例如p01）的永久豁免。

每份新交付目录包含 `WARNINGS.md` 和 `WARNINGS.json`，同时提供未处理 warning 数量、当前 artifact/gate 和具体项目。
即使为零也提供记录。仅统计当前发布门禁的机械警告，不混入已被新稿替代的旧失败，不把语义 findings 当作机械 warning。
旧门禁没有这份数据时显示 `legacy_not_recorded`/null，不冒称零；旧发布目录不自动加新文件。
报告不进学生 Markdown，不要求模型编写或用户逐条豁免。交付状态的每个 entry 含 `warning_report`，宿主应一并告知用户。

本阶段实现了早期页数检查和发布保护；语义拆分仍由planner完成，不会自动在第100页切断。
精确批次与旧任务计划重分配尚未加入，不能把当前版当成完整的p02/p03自动续做方案。

## 7. 已发布稿件的定向返修

```bash
mpres --root . repair open economics --presentation p01 \
  --mode review-first --allow-slide-changes \
  --report "排查没有学习价值的制作自述，允许删去无用页、合并重复内容。" --by user
mpres --root . runner run economics
mpres --root . repair present economics CASE_ID
# 向用户展示确切方案并得到真实同意后：
mpres --root . repair confirm economics CASE_ID --version 1 --by user
mpres --root . runner run economics
```

模式与删页权限必须在展示方案中确认。review-first 看原发布证据，不先重写原稿；
edit-first 是另一条兼容路径，不要把两者拼成多一轮流程。旧稿可作为审核证据，
但作者新稿必须通过当前规约。保留页维持 ID，消失原页用累计 `slide_changes` 解释删/并。
返修后恢复原 pilot/each 暂停，不顺手启动 p02。详细范围与停止条件见工作流手册。

### 审核数据与汇总

每个问题在 findings 表保存一份规范内容，其他反馈/返修要求通过 ID 引用。
学生试读的已接受分段结果仍是历史执行证据；最终汇总由程序合并，模型不再逐字抄写全部问题。
模型只新增发现、总结跨段关系或给出 `finding_refs`。精确重复只保留一条，近似问题不做自动语义合并。
原始模型结果作为事件证据保留；新 attempt 的内部结果保存问题 ID，不另维护一份问题正文。
旧已接受结果不改写。不存在的引用、跨作业引用仍拒绝；数学判断和严重度由reviewer负责，程序不补造。

## 8. 代码和文档各在哪里

| 位置 | 职责 |
|---|---|
| `src/mpres/cli.py`、`startup.py` | compact 默认入口、显式 legacy 分支、交互启动 |
| `control/service.py`、`store.py`、`schema.sql`、`migrate_*.sql` | 确认/绑定/提交与短事务，schema 8 |
| `control/runner.py`、`input_packet.py`、`audience.py` | 宿主请求、容量、必读/按需输入、分步阅读 |
| `control/semantic.py`、`guidance.py`、`schemas/`、`feedback.py` | 语义指南、四类结果、真实反馈版本与回执 |
| `control/workflow.py`、`repairs.py`、`delivery.py` | 整稿链、两种返修、历史版本与公开配对目录 |
| `control/quality.py`、`recovery.py`、`files.py` | 修订门禁、安全恢复与工作副本 |
| `source_policy.py`、`geometry.py`、`rendering.py`、检查模块 | 表达约束、计算图、固定原生渲染与结构检查 |
| `src/mpres/control/task_context.py` | 真实会话的 TASK 首次提供、复用、变更差异及回执记录 |
| `.agents/skills/` | 十个独立语义技能：五个内容角色与五个审核通道；不包含维护样例 |
| `templates/compact/` | 仅三份当前配置模板；[模板导航](templates/README.md) |
| `compat/legacy/templates/`、`docs/legacy/` | 显式旧入口兼容材料，不注入新任务 |
| `docs/` | 分流程工作手册、操作/宿主/内容契约、验证与维护说明 |
| `tests/compact/`、`tests/` | 新控制面与保留的旧回归；`tests/fixtures/semantic/` 只供源码维护 |

数据关系：config → plan item → job → attempt → artifact → gate/check。
Session 关联 attempt，usage/finding/decision/event 存库。检查、绘图、模型调用在写事务外，
SQLite 不替外部动作提供原子性。声明“已关闭”不能释放没有真实证明的句柄。

## 9. 状态、升级与验收边界

```bash
mpres --root . task status economics
mpres --root . task metrics economics
mpres --root . runner outstanding economics
mpres --root . task backup-db economics /safe/path/task.sqlite3
```

配置/教学授权/runtime 不会因打开旧任务被暗中改写。数据库增量迁移只做技术结构变化；
本轮文档整顿不升级 schema。旧发布、原图、usage 和既有回执保留，不追认旧审核采用新指令。
新任务只加载当前三个模板；历史文件制任务另走只读 `task import-legacy`。
DB 备份不包含资产，不是完整任务导出。

测试通过证明协议、约束、状态和恢复分支，不证明真实模型教学质量。真实宿主接线、
固定 Marp 原生 PDF、字体和操作系统行为仍须在部署环境验收。不得以替身通过宣传原生通过。
[验证口径](docs/VALIDATION.md) · [安全边界](docs/SECURITY.md) · [文档维护与盘点](docs/DOCUMENTATION-INVENTORY.md)

## 本阶段更新：v0.8.6

在 v0.8.5 基础上加入每次交互启动的本地 TASK 修改选择，并开放安全的修改入口：已编辑的
文件不妨碍进入修订对话，模型始终使用已确认配置。保留一次会话级 TASK 上下文，不新增
worker 回执或模型调用。页数分级、直接交付警告和问题引用归一化继续生效。

尚未合并真实 Codex bridge 的事件增量查询、超时/步骤恢复，也未实现 p02/p03 的精确批次与
自动规划分稿。当前估计超限会要求 planner 先拆分，不声称程序会自行决定教学切点。
