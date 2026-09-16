# Marp Presentation Orchestrator

将用户确认的教学计划转化为可维护的 Marp 课件。**AI 负责教学判断；Python runner 负责作业、检查和发布；SQLite 是运行事实的唯一真源。**
不是让 main 读完一堆过程文档再决定下一条命令，也不是把“生成 Markdown”当作“完成交付”。

**v0.9.7 重建版**：以核验的 v0.9.6 增量实现成本归属、等待观测和有界滚动调度。
[发布与基线说明](docs/RELEASE-v0.9.7.md) · [升级及旧任务返修](docs/UPGRADE-v0.9.7.md)。

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
生产派发仍经过确认与状态门。修改 TASK 后使用下方的 policy-present／policy-confirm；沿用不等于批准下一批。

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
精确批次支持既有课件及其确认的子稿；先由 planner 决定学习边界，再通过 plan 接口保存分配。批次不按页码自动拆稿。

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
| `src/mpres/cli.py`、`startup.py` | compact 默认入口、旧入口退役提示、交互启动 |
| `control/service.py`、`store.py`、`schema.sql`、`migrate_*.sql` | 确认/绑定/提交与短事务，schema 11 |
| `control/runner.py`、`input_packet.py`、`audience.py` | 宿主请求、容量、必读/按需输入、分步阅读 |
| `control/semantic.py`、`guidance.py`、`schemas/`、`feedback.py` | 语义指南、四类结果、真实反馈版本与回执 |
| `control/workflow.py`、`repairs.py`、`delivery.py` | 整稿链、两种返修、历史版本与公开配对目录 |
| `control/policy.py`、`batches.py` | 明确授权的有效值与精确批次；不猜教学拆分 |
| `control/host_journal.py` | 已派发请求与原始回执的关联、拒收状态和无模型重接收 |
| `control/quality.py`、`recovery.py`、`files.py` | 修订门禁、安全恢复与工作副本 |
| `source_policy.py`、`geometry.py`、`rendering.py`、检查模块 | 表达约束、计算图、固定原生渲染与结构检查 |
| `src/mpres/control/task_context.py` | 真实会话的 TASK 首次提供、复用、变更差异及回执记录 |
| `.agents/skills/` | 十个独立语义技能：五个内容角色与五个审核通道；不包含维护样例 |
| `templates/compact/` | 仅三份当前配置模板；[模板导航](templates/README.md) |
| Git 历史、`docs/legacy/` | legacy 模板已删除；历史说明不注入新任务 |
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
旧发布、原图、usage 和既有回执保留；技术迁移不追认旧审核采用新指令。
新任务只加载当前三个模板；历史文件制任务另走只读 `task import-legacy`。
DB 备份不包含资产，不是完整任务导出。schema 8/9/10 增量升级到11时增加宿主请求／回执、授权索引、精确批次和交付分配关系；不导入或修改旧宿主日志，不凭历史 attempt 猜测原始回执。

测试通过证明协议、约束、状态和恢复分支，不证明真实模型教学质量。真实宿主接线、
固定 Marp 原生 PDF、字体和操作系统行为仍须在部署环境验收。不得以替身通过宣传原生通过。
[验证口径](docs/VALIDATION.md) · [安全边界](docs/SECURITY.md) · [文档维护与盘点](docs/DOCUMENTATION-INVENTORY.md)

## 10. 回执接收和局部恢复

外部调用与结果接受分开：`host_requests` 在派发标记的同一短事务中保存准确请求，
`host_responses` 在语义校验前保存真实响应。原始响应不是通过证明；runtime、usage、
页面证据和结果结构仍必须验证。回执冲突不能覆盖，未收到响应不能以重发来猜执行状态。

```bash
mpres --root . runner outstanding economics
mpres --root . runner replay economics REQUEST_ID
mpres --root . runner resume-input economics ATTEMPT_ID
```

`replay` 只重接收数据库已有的准确响应，没有模型调用，也不修改 reviewer 结论。
适合修复确定性接收器 bug 后再验证；仍不符合证据要求的响应仍拒收。新传输如果返回不同
内容，不会替换旧回执；本版尚不提供人工改 JSON 的规范化授权接口。

`resume-input` 只释放当前 attempt 的“下一未派发步骤”的输入阻断。TASK/权限/预算不变；
已接受的阅读段、findings、brief 与 usage 不变。根因未解决时下一次编译仍阻断。
它不重置作业尝试预算，不重启模型，不处理已经派发／执行未知的步骤。

命令模式在执行结果已可信返回但语义拒收时返回 `response_rejected`，而不是标记整个执行
未知；缺少可信 runtime/usage 或丢失回执仍须对账。bridge 模式使用相同接收与重放入口。
原生 bridge 的增量证据投影、并行路由和双期限见下节；单独新增业务回执不构成宿主验证。

## 11. 有效授权与选定课件续做

初始配置不覆盖。程序以 `policy_values` 索引引用三类明确授权事件：TASK正文修订、容量上限、
输入预算。历史 `task.text_amended`、`capacity.authorized`、`context_budget.authorized` 自动按
类型和配置归属导入；不从普通 feedback 文本推断许可，不扩大某个 job 的额外重试授权。
不明配置归属、无确认来源或类型错误的事件会报告问题，不静默采用。主任务库仍是唯一真源。

```bash
mpres --root . task policy-show economics
# 修改 TASK.md 后展示精确文本差异；下面两项只在用户确实要求时填写
mpres --root . task policy-present economics --handle-limit 16 --context-budget-bytes 1048576
# 真正展示并得到用户确认后，使用返回的 presentation_id
mpres --root . task policy-confirm economics --presentation-id 123 --by user

# 选择已确认内容范围；父范围通过数据库映射展开，不按前缀匹配，不把pilot改成all
mpres --root . batch present economics --presentation p02 --presentation p03
# 向用户展示返回范围、页数估计和当前基线，再登记真实确认
mpres --root . batch confirm economics BATCH_ID --by user
mpres --root . runner run economics
mpres --root . batch status economics
```

TASK修订需暂停且无在途作业；纯容量/预算变更还允许在所有在途 attempt 都是本地未派发
输入阻断的安全位置确认。不能编辑 runtime 或计划字段绕过此入口。当前 `task.yaml` 保留初始
确认字节；`policy-show` 显示实际生效限制及来源。旧配置、jobs、发布和usage不因政策索引被重写。
已读会话只收到已确认 TASK 差异，旧在途请求仍按实际收到的旧版本验证。

批次确认同时约束 runner 准入、直接 job bind、当前+next 窗口和发布后的暂停。选定课件全部
交付后强制暂停，不启动未选择课件；已发布p01不能作为生产批次再次选择，应走repair。
确认前如果政策或目标状态变化，需要重新展示，而不是套用陈旧授权。批次不会更改原delivery
配置，也不会删除原队列。估计>100的选择会被拒；未知估计明确warning，不假装已规划完成。

这是“选定已确认范围”的生产控制。p02-01/p02-02 等分配关系由下面的 plan 接口
另行呈现和确认；系统不会自行决定教学切点，也不会承诺未重新验收的旧长稿自动合格。
真实模型和部署环境仍需联调；本版本提供正式适配器，不冒称供应商端已验收。

## 原生 Codex bridge：执行、证据与恢复

`mpres bridge run SLUG` 是已确认任务的前台适配器入口，不是启动时跳过 TASK 修改询问的捷径。
先通过 start.sh 选择本次任务方向、确认范围并完成环境/登录准备，再运行它；不自动登录、
不安装 Codex，不覆盖审批或沙箱，不更换模型。它调用 `codex app-server` 的默认 stdio。

```bash
# 离线：只读取已有日志并增量更新旁路索引，不调用模型
mpres --root . bridge index economics
mpres --root . bridge status economics
# 在线：执行 runner 已经事务性准入的准确请求
mpres --root . bridge run economics --cycles 100
# 只对账既有请求，不重新 start 模型 turn
mpres --root . bridge reconcile economics REQUEST_ID
```

主业务库仍决定请求是否已接受。`.mpres/codex-bridge.sqlite3` 保留原始协议证据及准确
请求/响应；旧 accepted 标记不是另一套业务状态。`.mpres/codex-index.sqlite3` 是可重建投影：
RPC身份、线程运行设置、turn终态/最终结果/累计用量，以及已处理wire游标。每次只查询主键
游标之后的有限批次，原始流式文本不再全量复制进索引。索引丢失可重建，但不得删除原始
journal。归档恢复或源文件替换时，使用新的索引文件，不把旧游标硬套到另一份日志。

一个stdout读取者分发所有响应；RPC按id匹配，通知按(threadId, turnId)定位。多个被runner
准入的线程可并行，同一线程不并行执行两个turn。线程池/容量/作者独立性继续由业务库
控制。不存在进程级“当前请求”来猜通知归属，也不把一个线程的token计给另一个。

库存读取用thread/loaded/list；仅对缺失的已登记身份使用不带turn历史的thread/read。
不会为每次库存探测resume全部线程、扫描全对话找usage。供应商没有提供可查询全局硬上限
时，报告明确的“已确认适配器本地上限”，不宣称探测到了全局容量，也不释放无close证明的
句柄。无真实累计用量基线的旧线程不能推断为0。

超时分两类：provider_timeout_seconds仍是已确认的单turn总墙钟上限；可在确认前设置
provider_idle_timeout_seconds作为无有效进展期限，省略则等于总上限。文本/工具输出增量、
真实完成项或增长的用量可以刷新idle，普通heartbeat不可以；总预算不会被刷新，旧任务的
1200秒不会被悄悄延长。超时/断线仅报告待对账，不盲目重发或假装中断已经完成。
明确interrupted/failed的turn不能冒充成功；续作范围/预算仍需既有控制授权。

已保存completed与usage、但响应接收丢失时，可以直接重建真实回执；必要时显式reconcile
查询指定thread历史。缺少终态或用量等证据仍阻断，不能从作者文字推断程序完成。
本版本没有对旧临时补丁进行整体移植；不提供任意人工改回执再假装原结果的接口。

测试区分真实本地JSON-RPC子进程、确定性语义/渲染替身、真实归档增量索引与真正模型调用。
前面三种不等于真实Codex登录、供应商服务、教材质量或Marp PDF的端到端验收。
协议依据：OpenAI Codex App Server官方文档（https://developers.openai.com/codex/app-server）。

## 规划内容范围与交付稿的映射

一章、一组课次和一个 PDF 不再必须同名。`control/planning.py` 管理确认后的有序
课次分配；`delivery_parts` 保存父范围与实际子稿，`plan_item_origins` 保存课次与原稿
来源，`plan_changes` 保存精确的展示/确认依据。原 configs、plan_items、jobs 和发布记录
不被覆盖。现有 schema 8/9/10 会通过短事务升级到 11，无须清空旧任务。

新任务在确认前直接在 task.yaml 规划合适的课件。已有暂停任务需要拆分尚未组装的范围时：

```bash
mpres --root . plan show linear-algebra-v7
mpres --root . plan present linear-algebra-v7 --proposal /path/to/proposed-partition.json
# 展示返回的实际范围、资料复用与估计，取得真实确认后：
mpres --root . plan confirm linear-algebra-v7 PLAN_CHANGE_ID --by "用户明确确认分配"
mpres --root . batch present linear-algebra-v7 --presentation p02 --presentation p03
# 查看展开后的准确子稿，确认后才开始生产：
mpres --root . batch confirm linear-algebra-v7 BATCH_ID --by "用户确认仅完成本批"
mpres --root . bridge run linear-algebra-v7 --cycles 200
```

下面是接口说明用的输入，课次切点和页数必须由实际教学规划决定，不能直接复制作为
用户任务的已确认方案；不要求在任务目录再维护一份过程文档：

```json
{"parents":[{"presentation":"p02","parts":[
  {"id":"p02-01","title":"第一组学习目标","estimated_pages":80,"units":["l07","l08","l09"]},
  {"id":"p02-02","title":"第二组学习目标","estimated_pages":80,"units":["l10","l11"]}
]}]}
```

分配必须完整、有序、无重复，不能删除原课次、添加未授权课次或改 runtime。每份估计
1–100页；单一课次本身太长需要先做语义拆解，不在第100页机械切文件。不拆分而只补
估计时可以让唯一 part 保持父稿 id，并列出全部课次。尚未确认的方案可用 `plan cancel`
取消；已确认分配不自动改写。暂停且尚未组装时，可再次呈现并确认估计/标题调整，或将仅记录估计的范围拆分；旧确认完整保留。已在编辑/审核的稿件、已发布 p01、活动批次或活动返修
不能套用这个规划入口。切点错误或教学范围改变仍需新的明确规划，不暗中重排。

已发布稿可用独立的 `plan split-published-present / split-published-confirm /
split-published-run` 入口，按明确确认的整课边界无损拆分。proposal 使用上述结构，页数必须
等于实际分配页数。程序固定父发布稿及全部素材，核对页面完整、有序、不改正文；若有练习索引，
只分配对应条目且题目与答案不能分属两稿。每个子稿分别通过当前原生 full gate 后才一并登记
派生发布，保留原发布记录、来源映射和 runtime。该路径不调用模型，也不宣称发生新的语义审核；
内容改写与新教学要求验收必须随后走 repair。失败检查不产生部分子稿发布，重跑复用已留存证据。

选择父范围时，batch 按数据库关系展开所有实际子稿，而不是匹配文件名前缀；父子范围
重叠选择会报错。原父稿作业仍保留作历史，但不可再绑定；只派发当前子稿，选定范围
全部交付后暂停，p04 不会因分成更多 PDF 自动开始。Workflow 状态单独显示被替代范围。

子稿继承原 presentation 的已确认 runtime 及反馈范围。原作者/审核参与历史也向子稿
继承，不能换一个 id 后让原作者自审。旧 accepted/import 内容只作为新作者工作副本的
起点（兼容 section.md）；会重新提供当前主题并再算已声明数学图。它不是通过新门禁的
证据，也不改原 SVG、Markdown、PDF 或旧 gate。必读资料沿课次关系保留；同一真实
会话不因此重读完整 TASK。

运行中121–130页仍只记 warning，超过130页为error；最终新交付不超过120页。
每份公开目录继续包含 PDF、同名 Markdown、资源和 WARNINGS.md/JSON。没有自动ZIP，
没有新增审核者验修轮次，没有为确认后的任务自动切换模型。

## 当前验证边界

程序的增量桥接和分配关系都有真实归档回放/迁移检查；端到端队列测试的模型和完整
PDF渲染仍是明确标识的替身，不代表实际模型教学质量或部署机器原生 Marp 已通过。
真实服务必须完成 Codex 登录、固定工具链检查、准确 runtime/usage 回执；权限请求
不会自动同意。未知执行先对账，不允许因需要继续而假设已关闭或重复启动。

## 本阶段更新：v0.9.3

- v0.8.9：按 RPC/thread/turn 的增量桥接，原始证据不重扫、已登记独立请求可并发。
- v0.9.3：确认的交付分配、来源与runtime继承、父范围批次展开、完整范围交付后暂停。
- 两阶段分别打包；v0.9.3 包含前一阶段代码。旧教学配置与三个用户入口不被迁移覆盖。

## v0.9 使用入口

累计源码包与逐版验证记录见 `docs/releases/`。升级旧任务及三个既有课件返修见
[升级手册](docs/UPGRADE-v0.9.md)；不要覆盖原任务目录或把旧审核追溯当成按新规则通过。
[练习与内容合同](docs/CONTENT-CONTRACT.md)、[存储维护](docs/STORAGE-MAINTENANCE.md)、
[计量与交接](docs/COST-AND-SUPERVISION.md)、[启动权限](docs/STARTUP-PERMISSIONS.md)
分别服务对应流程，不一起塞进所有 worker 输入。
新增 runtime-operations 仅 main 按需读取，十个教学语义角色与五个审核通道不变。

默认 `pytest` 运行当前 `tests/compact` 流程。历史流程测试不再作为当前生产验收入口；旧任务的导入、发布拆分和源格式迁移仍在当前回归中覆盖。
