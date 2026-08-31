# Marp Presentation Orchestrator v0.4.1

这是一个面向 **Codex CLI + Marp** 的课程与报告课件生产框架。它把用户确认、planner 亲自编写 assignment、分阶段并行 authoring、一次五通道全稿审核、作者自行修改和 PDF-only 发布组织成一个可审计的状态机。

## 1. 正式产物与临时机械检查

正式产物链只有：

```text
canonical Marp Markdown
        ↓
@marp-team/marp-cli
        ↓
PDF
```

项目不使用 Quarto、Reveal.js、Beamer 或第二份讲稿源。正式交付只包含 Marp 源、结构化记录和 PDF。

为了在提交审核之前发现文字溢出，author/release 构建会额外执行一次**临时机械检查**：

```text
presentation.md
        ↓
marp --html（临时目录）
        ↓
Playwright / Chromium
        ↓
逐页比较 scrollWidth/clientWidth、scrollHeight/clientHeight
        ↓
写入结构化检查报告并删除临时 HTML
```

临时 HTML：

- 只存在于系统临时目录；
- 不进入 source snapshot、review bundle 或 deliverables；
- 不作为另一种课件版本；
- 不使用截图和模型视觉；
- 检查完成后自动删除。

作者的临时 HTML 溢出检查不通过，便不会生成 PDF，也不能提交审核。reviewer 不重新检查机械溢出；layout 通道只审核层级、分组、密度、节奏和教学呈现设计。

## 2. 固定政策

1. 每份 presentation 只做**一次**完整五通道审核。
2. 审核后作者逐条回应 findings、完成修改、自检和重新构建；reviewer 不再复核，findings 不维护 resolved 生命周期。
3. 课程的每个课次必须包含 **2—3 道**真正具有诊断作用的选择题及紧邻答案页；学术报告免除数量要求。
4. planner 亲自编写并批准每个精确 assignment；coordinator 只能提交 assignment request。
5. planner 的全局默认运行策略是 `gpt-5.6-sol/max`；所有 workers 默认 `gpt-5.6-sol/high`。唯一真源为根目录 `MODEL-POLICY.yaml`。
6. worker 只能读取 `downloads/text/` 中的抽取文本，禁止打开、解析、转换、OCR、截图或引用原 PDF。
7. 禁止截图、PDF contact sheet 和模型视觉审核。
8. Python 生成图形默认关闭；文本、公式、Markdown 表格、CSS 和简单本地资产优先。
9. GeoGebra 只允许引用经过验证的 `https://www.geogebra.org/m/...` 资源，且只能使用普通 Markdown 超链接；允许同一个资源在不同课次中重复使用，不做去重要求。
10. Marp CLI 版本不固定，由 bootstrap 安装当时可用版本，doctor 用实际能力 probe 判断可用性。
11. 只有任务顶层 `TASK.md` 使用用户确认摘要，其它源文件、报告、产物和压缩包不生成哈希。

## 3. 课程组织与时间策略

课程课件必须按连续编号的课次组织：

```text
第 1 节课
第 2 节课
第 3 节课
...
```

教材章节只用于资料覆盖和来源映射，不能直接充当课件分节依据。每个 course content unit 就是一节课；报告 content unit 才按逻辑部分组织。

时间规划是建议，不是硬门：

- 名义课堂时长定义自然停止点；
- 默认可准备约名义时长的 1.5 倍材料；
- 例如 40 分钟课堂可准备约 60 分钟课件；
- 前部 core path 应覆盖本节课必须完成的概念链、必要活动和诊断题；
- 后部主要安排可选的讲解例题；
- 到点可以直接下课，不要求讲完整份课件。

每个课次填写 `LESSON-TIME-PLAN.yaml`，明确 nominal time、自然停止页和 optional example bank。程序只检查结构是否清楚，不因时长估算偏差阻止发布。

## 4. 角色

```text
planner
  ├── author-coordinator × presentation
  │     └── lesson-author × numbered meeting / report unit
  ├── review-coordinator × presentation
  │     └── specialist-reviewer × 5 channels
  └── release-coordinator × presentation
```

- **planner**：采访用户、写 TASK.md、亲自写 assignment、处理政策变更和高层监督；默认 Sol/max。
- **author-coordinator**：建立整份 deck 的教学地图、术语、语义对象、例题、时间计划和资产决策；监督 lesson authors；整合 canonical `presentation.md`；执行作者机械门并在审核后自行修改。
- **lesson-author**：完成一个编号课次或报告内容单元。
- **specialist-reviewer**：只审核一个通道，不看其它通道 finding，也不检查临时 HTML 或机械 overflow report。
- **review-coordinator**：并行启动五个 reviewer、验证报告齐全并汇总 findings。
- **release-coordinator**：验证作者流程与机械构建条件齐全，重新执行发布机械门并交付；不判断 finding 是否“解决得足够好”。

## 5. 首次问询

没有活动任务时，planner 一次性询问：

1. 课程或报告题目；
2. 目标听众、先修知识、薄弱点和预期收获；
3. 总体大纲；
4. 演讲策略；
5. 参考资料；
6. `pilot`、`each` 或 `all` 交付模式；
7. 是否允许少数 Python-generated assets，默认否。

课程还询问课次和每次名义时长，并在 TASK.md 中按“第 N 节课”建立 units。

在展示 TASK.md 前，必须提醒用户：一次五通道审核、审核后不复核、课程每课 2—3 道 MCQ、禁止截图与原 PDF、planner Sol/max、workers Sol/high、临时 HTML 只用于 author/release 机械门、PDF-only 交付、Python 图形默认关闭。

## 6. TASK.md 确认门

```bash
mpres task init ...
# planner 完成 tasks/<slug>/TASK.md
mpres task present <slug>
# 用户明确确认当前版本
mpres task confirm <slug>
mpres task gate <slug>
```

`TASK.md` 是唯一使用确认摘要的文件。生产初始化后冻结。重大政策变化必须修改并重新确认 TASK.md；sidecar 不能覆盖用户确认的计划。

## 7. Planner-owned assignment contracts

每个 assignment 目录包含：

```text
ASSIGNMENT-REQUEST.yaml
ASSIGNMENT-BRIEF.yaml
ASSIGNMENT-DECISION.yaml
TASK-....md
```

planner 必须亲自写 exact taskbook、hard constraints、replaceable hypotheses、local decision rights、允许读取的抽取文本、acceptance criteria 和 deferred questions。只有 `mpres assignment approve` 后才能执行。

## 8. Authoring stages

课程单元默认六阶段：

```text
01_scope_sources
02_learner_need
03_domain_development
04_entry_diagnostics
05_learner_language
06_marp_integration
```

报告使用四阶段精简 profile。课程阶段 04 必须设计 2—3 道 MCQ；阶段 06 完成题目/答案相邻、core/support、option audit、课次边界和时间计划。

## 9. 一次审核与直接发布

状态机：

```text
authoring
→ review_requested
→ reviewing
→ author_revision
→ release_ready
→ finalized
```

唯一审核轮名为 `full`，包含：

- language；
- domain_accuracy；
- layout（教学呈现设计，不检查机械 overflow）；
- pedagogy；
- audience。

审核请求只包含冻结源和 PDF，不包含临时 HTML、HTML layout report 或其它机械版式证据。机械门已经由 author 在提交前完成。

汇总后作者必须：

1. 对每条 finding 写 disposition、evidence 和修改位置；
2. 修改课件；
3. 完成 `AUTHOR-MODIFICATION-CHECKLIST.yaml`；
4. 更新 `AUTHOR-REVISION.md` 和 SELF-CHECK；
5. 重新运行 source lint、asset validation、临时 HTML layout inspection、PDF build 和 PDF inspection。

完成后直接形成 `release_ready`。reviewer 不检查修改结果。

## 10. 机械检查

标准作者构建：

```bash
mpres render <slug> --presentation p01 --stage author
```

单独检查临时 HTML：

```bash
mpres inspect html-layout <slug> --presentation p01 --stage author
```

检查器读取 Marp 输出中的：

```css
section[data-marpit-scope]
.marpit > section
```

并使用每页的真实尺寸比较：

```text
scrollWidth  vs clientWidth
scrollHeight vs clientHeight
```

因此不把 1280×720 硬编码成所有主题的唯一页面尺寸。报告记录每页 ID、client/scroll/computed dimensions 和溢出量。正式 PDF 仍另外检查页数、方向、文本层、最小字号、内部制作词和页面结构。

## 11. 参考资料、GeoGebra 与资产

worker 只获得 `downloads/text/`。抽取文本不足时记录 source gap、改用其它已批准文本或网页、缩小/删除 claim，或者升级范围问题；不得返回原 PDF。

GeoGebra 资源必须真实验证，只能以描述性 Markdown 链接出现。同一个 material 可以在不同课次中反复引用，只要各课次登记各自的教学用途；程序不要求跨课次去重。

Python 图形默认关闭。普通表格不得用 Matplotlib 重画；即使批准图形，也要检查最终物理字号、箭头/文字重叠、legend、纵横比和教学必要性。

## 12. 安装与启动

需要 Python 3.11+、Node.js 18+、npm、Codex CLI、`pdftotext`；Tesseract 只供系统 ingestion 的最后手段。

```bash
./start.sh
```

或更安全的：

```bash
./start-safe.sh
```

bootstrap 会：

1. 建立 `.venv`；
2. 安装 Python 包；
3. 安装未固定版本的 Marp CLI；
4. 安装 Playwright Chromium（已有 `MPRES_CHROMIUM_EXECUTABLE` 时可跳过）；
5. 运行 doctor。

```bash
python scripts/bootstrap.py
.venv/bin/mpres doctor --strict
```

Doctor 同时验证 Marp PDF probe 和 Chromium 临时 HTML layout probe。

## 13. 常用命令

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
mpres inspect html-layout ...
mpres inspect pdf ...
mpres review ...
mpres thread ...
mpres token ...
mpres supervise ...
mpres audit ...
```

## 14. 安全与限制

危险启动器绕过 Codex 审批和沙箱，只能用于隔离 VM、容器或专用低权限账户。仓库中的角色目录、只读副本和状态机不是操作系统级安全边界。

结构化 HTML/PDF 检查只能发现机械问题，不能证明语言、数学和教学质量。唯一一次 reviewer 审核承担独立内容审查；作者修订后不复核是明确的质量/成本取舍。
