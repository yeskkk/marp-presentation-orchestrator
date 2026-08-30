# Marp Presentation Orchestrator v0.3.0

这是一个面向 **Codex CLI + Marp** 的课程与报告课件生产框架。它把用户确认、planner 亲自编写 assignment、分阶段并行 authoring、一次五通道全稿审核、作者自行修改以及 PDF-only 发布组织成一个可审计的状态机。

## 1. 核心原则

正式产物链只有：

```text
canonical Marp Markdown
        ↓
@marp-team/marp-cli
        ↓
PDF
```

项目不使用 Quarto、Jupyter presentation、Reveal.js、Beamer 或持久 HTML。Marp CLI 内部可以调用兼容浏览器打印 PDF，但工作目录和交付目录只保留 Markdown、结构化记录和 PDF。

固定规则：

1. 每份课件只做 **一次**完整的五通道审核；
2. 审核后作者必须逐项回应 finding、修改、自查并重建，但 reviewer 不再复核；
3. finding 不使用 `resolved` 一类状态，release coordinator 不判断“改得够不够好”；
4. 每个课程 content unit 必须有 **2—3 道**真正具有诊断作用的选择题及紧邻答案页；学术报告免除数量要求；
5. planner 亲自编写并批准每一个精确 assignment；coordinator 只能提出 assignment request；
6. worker 默认使用 `gpt-5.6-sol`，推理强度 `high`；极难的研究级内容才按 TASK.md 提高到 `max`；
7. worker 只能读取 `downloads/text/` 中的抽取文本，禁止打开、解析、转换、OCR、截图或引用原 PDF；
8. 禁止用截图、PDF 栅格页、contact sheet 或模型视觉审核课件；
9. Python 生成图形默认关闭，必须由 TASK.md 和逐资产决策同时批准；
10. GeoGebra 只允许搜索 `geogebra.org` 站内的具体公开 material，并以普通 Markdown 超链接引用，禁止嵌入、截图、预览图、二维码或下载副本；
11. Marp CLI 版本不固定。bootstrap 安装当时可用版本，doctor 以实际 PDF probe 判断是否可用；
12. 只有每个任务顶层的 `TASK.md` 使用用户确认哈希，其他文件、产物与压缩包都不生成哈希。

## 2. 角色

```text
planner
  ├── author-coordinator × presentation
  │     └── lesson-author × content unit
  ├── review-coordinator × presentation
  │     └── specialist-reviewer × 5 channels
  └── release-coordinator × presentation
```

- **planner**：采访用户、写 TASK.md、亲自写每份 assignment、批准 assignment contract、处理政策变更和 presentation 级监督；不写逐页内容。
- **author-coordinator**：建立整份 deck 的教学地图、术语、语义对象、例题和资产决策；监督分阶段 lesson authors；整合 canonical `presentation.md`；审核后自行完成修改流程。
- **lesson-author**：只处理一个课次或报告内容单元。
- **specialist-reviewer**：只审核一个通道，只看冻结的完整候选稿，不看其他通道 finding，也不看未来的作者回应。
- **review-coordinator**：并行启动五个 reviewer，验证报告齐全并汇总 finding；不改作者源。
- **release-coordinator**：只验证作者修改流程和机械构建条件是否齐全，生成最终 PDF 并发布；不做内容判断。

不再使用 `worker1`、`worker2` 等编号角色名称。

## 3. 首次问询

没有现有任务时，planner 一次性询问：

1. 课程或报告题目；
2. 目标听众、先修知识、薄弱点和预期收获；
3. 总体逻辑大纲；
4. 演讲策略；
5. 参考资料；
6. 交付模式：`pilot`、`each` 或 `all`；
7. 是否明确允许某些 Python-generated assets，默认否。

课程还需询问课次与每次名义时长。时长只校准材料总量，不机械决定内容边界。

在生成 TASK.md 前必须提醒用户：一次五通道审核、审核后不复核、课程每节 2—3 道选择题、禁止截图与原 PDF、worker 默认 sol/high、PDF-only、Python 图形默认禁用。

## 4. TASK.md 确认门

```bash
mpres task init ...
# planner 完成 tasks/<slug>/TASK.md
mpres task present <slug>
# 用户明确确认当前版本
mpres task confirm <slug>
mpres task gate <slug>
```

`TASK.md` 是唯一使用哈希的文件。生产初始化后 TASK.md 冻结。误改可执行：

```bash
mpres task restore-confirmed <slug>
```

改变审核数量、角色、输出格式、参考资料访问、默认模型、课程 MCQ 要求、听众或范围等任务承诺时，必须建立 policy change request，并修改、重新展示和重新确认 TASK.md。sidecar 记录永远不能覆盖 TASK.md。

## 5. Planner-owned assignment contracts

每个 assignment 目录包含：

```text
ASSIGNMENT-REQUEST.yaml
ASSIGNMENT-BRIEF.yaml
ASSIGNMENT-DECISION.yaml
TASK-....md
```

coordinator 只能说明为什么需要该角色。planner 必须亲自完成：

- exact Markdown taskbook；
- hard constraints；
- replaceable hypotheses；
- local decision rights；
- 允许读取的抽取文本或网页来源；
- acceptance criteria；
- deferred questions。

只有运行 `mpres assignment approve` 后，该 assignment 才能执行。assignment 中出现 `.pdf`、`downloads/restricted-originals/` 或 restricted metadata 路径会被拒绝。

## 6. 分阶段 authoring

课程 content unit 默认六阶段：

```text
01_scope_sources
02_learner_need
03_domain_development
04_entry_diagnostics
05_learner_language
06_marp_integration
```

学术报告使用四阶段精简 profile：

```text
01_scope_sources
02_audience_domain
03_narrative_language
04_marp_integration
```

每阶段都有 planner-written assignment、耐久产物、提交和 coordinator 接受门。阶段 01 只能引用 `downloads/text/` 或明确说明不使用外部资料。课程阶段 04 必须设计 2—3 道选择题；阶段 06 完成题目页/答案页相邻、core/support 分类和选项审计。

## 7. 选择题契约

课程每个 content unit 必须有 2—3 道 multiple-choice prompt/answer pairs。每题至少记录：

```yaml
prompt_slide:
response_slide:
purpose:
preceding_comparison:
requires_fresh_inference: true
selection_rationale:
visible_labels: [A, B, C, D]
option_audit:
```

题目页必须是 core，答案页必须是紧邻的 support。选项要覆盖典型误区；正确项需说明理由，错误项需说明对应误解。能直接复制上一页结论而无需新推理的题不合格。

## 8. 参考资料

planner 或系统 ingestion 可以处理输入文件，随后把原件放入：

```text
downloads/restricted-originals/
```

并把抽取文本放入：

```text
downloads/text/
```

worker assignment、context bundle 和 reviewer 输入只能引用抽取文本。抽取文本不足时应记录 source gap、改用其他已批准文本或网页、缩小/删除相应 claim，或升级为范围问题；不得返回原 PDF。

## 9. GeoGebra

lesson author 仅在动态探索确有教学价值时做小规模搜索：

```text
site:geogebra.org/m ...
```

每个 unit 默认最多三次查询、最多选择三个资源。进入课件的资源必须：

- URL 为 `https://www.geogebra.org/m/<resource-id>`；
- `verification_status: verified`；
- 记录 title、author、activity 和验证时间；
- 用描述性 Markdown 文本链接；
- 即使学生不打开链接，PDF 仍完整讲清必需内容。

## 10. Python assets

默认顺序：

```text
普通文字/公式
→ Markdown 表格
→ 主题 CSS 布局
→ 简单手写 SVG
→ 已批准的现成资源
→ 最后才考虑 Python 图形
```

Python 图形必须逐项批准，并检查字体物理尺寸、箭头/标签重叠、legend 遮挡、纵横比、文字总量和教学必要性。普通表格不得用 Matplotlib 重新画一遍。

## 11. 一次审核与直接发布

状态机：

```text
authoring
→ review_requested
→ reviewing
→ author_revision
→ release_ready
→ finalized
```

唯一审核轮名为 `full`，包括：

- language；
- domain_accuracy；
- layout；
- pedagogy；
- audience。

五个 reviewer 独立查看同一个冻结源和 PDF。每条 finding 有稳定 ID、位置、问题、学习者影响、验收标准和验证方法，但没有 `resolved` 状态。

汇总后作者必须：

1. 对每条 finding 写 disposition、evidence 和修改位置；
2. 修改课件；
3. 完成 `AUTHOR-MODIFICATION-CHECKLIST.yaml`；
4. 更新 `AUTHOR-REVISION.md` 和 SELF-CHECK；
5. 重新运行 source lint、asset validation、PDF build 和 PDF inspection。

完成后直接形成 `release_ready` 冻结快照。reviewer 不再检查修改结果。release coordinator 只做最终机械构建；若发现必须改语义，则退回 author，而不是自行修复。

## 12. 渲染与检查

标准命令：

```bash
mpres render <slug> --presentation p01 --stage author
mpres render <slug> --presentation p01 --stage release
```

实际 Marp 命令包含：

```text
--pdf
--allow-local-files
--html
--theme-set themes/mathist-academic.css
--output <presentation>.pdf
```

这里 `--html` 只允许 Marp Markdown 使用受约束 HTML 语法，不生成 HTML 交付件。任何意外 HTML 文件都会被删除并使构建失败。

机械检查包括：Marp front matter、分页、slide ID、core/support、manifest、MCQ pairing、TeX 控制词、远程图片、资产、PDF 页数、方向、文本层、字体尺寸和内部制作词。禁止 screenshot API、PDF 页栅格化和模型视觉。

## 13. 线程、token 与监督

线程 registry 区分：

```text
active
idle_reusable
terminal_not_releasable
closed
```

author 过的 presentation 不能由同一 thread 担任 reviewer。复用或关闭前必须提交 durable handoff。

Token collector 只导入精确计数，不抽取消息内容，不估算缺失值；可按 presentation、角色、unit、channel、thread 和 model 汇总。

planner 在 **二十分钟或一份 presentation 交付事件**中先发生者进行高层监督。author/review coordinator 在本 presentation 内自行监督 subroles。未激活的 presentation 不被误判为停滞。

## 14. 停止模式

- `pilot`：先完整交付第一份 presentation，暂停一次听取用户反馈；继续后按计划生产。
- `each`：每份交付后暂停。
- `all`：全部交付后暂停。

## 15. 安装与启动

要求：Python 3.11+、Node.js 18+、npm、Codex CLI、`pdftotext`；Tesseract 只用于系统 ingestion 的最后手段。

Linux/macOS：

```bash
./start.sh
```

Windows：

```powershell
.\start.ps1
```

更安全的启动器：

```bash
./start-safe.sh
```

```powershell
.\start-safe.ps1
```

Bootstrap 建立 `.venv`、安装 Python 项目，并执行：

```bash
npm install --no-audit --no-fund --no-package-lock
```

Marp 版本不固定，也不保留 `package-lock.json`。`mpres doctor --strict` 会验证实际安装的 CLI 是否能生成可解析的单页 PDF。

## 16. 常用命令

```text
mpres doctor
mpres task ...
mpres policy ...
mpres assignment ...
mpres production ...
mpres stage ...
mpres author assemble
mpres source lint
mpres assets ...
mpres geogebra validate
mpres render ...
mpres inspect pdf
mpres review ...
mpres thread ...
mpres token ...
mpres supervise ...
mpres audit ...
```

完整参数以 `mpres <command> --help` 为准。

## 17. 从旧版本迁移

本版把审核、assignment、authoring stage、参考资料权限和默认模型政策都改成了新的状态语义。旧任务中若仍含：

```text
initial / incremental / final / terminal review 状态
review_status / resolved 字段
固定 Marp CLI 版本或 package-lock.json
medium 默认推理强度
worker 可见的原 PDF 路径
coordinator 自动编写的 assignment
```

不要直接覆盖源码后继续旧状态。保留旧目录作审计档案，在 v0.3.0 中新建任务；可以人工迁移已经确认的教学大纲、抽取文本、语义对象、例题地图和 Marp 内容，但不要迁移旧 state、review request、findings lifecycle、approval 或 release 记录。

## 18. 安全边界与限制

危险启动器会绕过 Codex 审批和沙箱，只应在隔离 VM、容器或专用低权限账户中使用。仓库中的角色目录、只读副本和状态机是工作流约束，不是操作系统安全边界。

结构化 PDF 检查不能代替领域判断和教学判断；唯一一次 reviewer 审核承担全部独立内容审查。作者修改后不复核是用户选择的成本/质量取舍，release record 会明确保存这一事实。
