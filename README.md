# Marp Presentation Orchestrator v0.5.0

这是一个面向 **Codex CLI + Marp** 的课程课件与报告制作框架。它把用户确认、planner 亲写 assignment、按课次并行制作、单次五通道审核、作者自行修订、机械发布、单一并发日志、课程连续性和已发布课件维护组织成可审计的工作流。

正式演示产物始终是：

```text
canonical Marp Markdown
        ↓
@marp-team/marp-cli
        ↓
PDF
```

临时 HTML 只用于 author/release 的浏览器机械检查，检查后立即删除，不进入 reviewer bundle、deliverables 或长期存储。

## 1. 全局运行政策

根目录的 `MODEL-POLICY.yaml` 是唯一模型真源：

```yaml
planner:
  model: gpt-5.6-sol
  reasoning_effort: max
workers:
  model: gpt-5.6-sol
  reasoning_effort: high
```

`.codex/config.toml` 和角色 TOML 必须与之相符。线程注册时还会记录实际 model/effort；不匹配便拒绝接受该线程。线程批次启动前执行 capacity preflight，并保留 task policy 指定的未分配容量。

## 2. 用户确认与固定政策

只有任务顶层：

```text
tasks/<slug>/TASK.md
```

使用用户确认摘要。其它 source、reference、finding、PDF、release、日志和压缩包均不生成或检查哈希。

首次问询必须提醒用户：

- 每份 presentation 只进行一轮完整五通道审核；
- 作者回应 findings、完成修改流程和机械自检后直接发布，reviewer 不复核；
- findings 不维护 resolved 生命周期；
- planner 默认 Sol/max，workers 默认 Sol/high；
- 课程每节课包含 2—3 道诊断性选择题，学术报告除外；
- worker 只能读取抽取文本，禁止打开原 PDF；
- 截图、PDF contact sheet、模型视觉审核全部禁止；
- Python 图形默认关闭；
- GeoGebra 只允许已验证的普通超链接，可跨课次复用；
- delivery mode 为 `pilot`、`each` 或 `all`。

改变审核数量、输出格式、原 PDF 权限、选择题配额或 assignment ownership 等任务承诺，必须修改并重新确认 TASK.md。

## 3. 角色和职责

```text
planner
├── author-coordinator × presentation
│   └── lesson-author × 课次/报告内容单元
├── review-coordinator × presentation
│   └── specialist-reviewer × 五个通道
└── release-coordinator × presentation
```

- **planner**：采访、TASK 确认、亲自写全部 exact assignments、模型与线程政策、presentation 级监督和暂停门。
- **author-coordinator**：完成 deck-level maps，监督并行 lesson authors，整合源文件，运行机械门，回应唯一一次审核。
- **lesson-author**：一个内容单元、一份 planner-approved assignment、同一个 thread、完整 staged authoring。
- **specialist-reviewer**：只审核一个通道的冻结全稿，不见其他通道 findings，不看作者后续修订。
- **review-coordinator**：验证五份当前 handoff，原子汇总，生成 finding routing，不改作者源。
- **release-coordinator**：只做机械构建和发布，不判断 finding 是否修好。

## 4. 一个 lesson assignment、一个 thread、内部多阶段

课程单元在同一个 lesson-author thread 中依次完成：

```text
01 scope and extracted sources
02 learner need
03 domain development
04 cognitive entry and diagnostics
05 learner-facing language
06 Marp integration and self-check
```

报告使用 task profile 中的精简阶段。阶段是**内部工作步骤**，不是新的 assignment 或 worker：

```bash
mpres stage start ...
mpres stage submit ...
```

`submit` 验证当前耐久 artifact 和 checkpoint 后自动激活下一阶段。不会重新 spawn、不会要求 planner 重写 stage assignment，也不等待 coordinator 单独验收。`complete` 仍作为兼容别名存在，但新任务统一使用 `submit`。

## 5. 按第几节课组织课程

课程 content unit 对应连续编号的课堂：

```text
第 1 节课
第 2 节课
……
```

教材章节只用于资料映射，不决定 deck 的一级结构。每节课有：

- 名义课堂时长内的 core path；
- 一个自然停止点；
- 停止点后的 optional worked-example extension bank。

默认可为 40 分钟课堂准备约 60 分钟材料；后约 20 分钟主要用讲解例题填充。这个比例只产生规划建议，不是发布硬门。到点可以直接下课，不必讲完。

## 6. 课程级术语、对象与连续性

课程任务初始化：

```text
COURSE-TERMINOLOGY.yaml
COURSE-SEMANTIC-OBJECTS.yaml
CROSS-DECK-HANDOFFS.yaml
```

每份 deck 还维护：

```text
TERMINOLOGY.yaml
SEMANTIC-OBJECTS.yaml
PRESENTATION-CONTINUITY-MAP.yaml
```

机械检查验证：

- deck term 是否映射到课程级 term；
- course-scoped object 是否存在于课程注册表；
- 后续 deck 是否声明 `incoming_from`；
- 是否存在相应 cross-deck handoff；
- 重新激活的术语和对象是否真实存在。

这样减少跨课的术语漂移、对象换名和无解释的抽象跳转。

## 7. 页面教学动作密度

每张 slide 在 `SLIDE-DENSITY-AUDIT.yaml` 中声明：

```yaml
id:
principal_teaching_move:
substantial_blocks:
split_rationale:
```

硬规则不是固定字符数，而是“一页主要承担一个教学动作”。超过三个 substantial blocks 且没有合理的同屏理由会阻塞；三个块没有理由会报警。字符数、bullet 数和表格行数只作为辅助信号。

## 8. 选择题要求

课程每个课次必须有 2—3 对：

```text
core prompt slide
→ 紧邻的 support answer/hint slide
```

MCQ audit 至少记录：

- 学生在 prompt 前已经掌握的信息；
- 有意保留到回答页的信息；
- 题目要求的新推理；
- 单一 decision unit；
- prerequisite 是否已经出现；
- cue leakage 检查；
- composite-option 检查；
- visible labels、正确项理由和每个错误项对应的误区。

只复制上一页结论、prompt 泄露答案、一道题包含多个独立任务、题答不相邻或 option audit 不完整都会阻塞。

## 9. Author 机械提交门

review request 之前，author 必须通过：

1. Marp source lint；
2. 本地资产与 GeoGebra 规则；
3. 课程术语、语义对象和 continuity；
4. principal-teaching-move density；
5. 数学 source inventory；
6. 临时 Marp HTML renderer probe；
7. 临时 HTML overflow/out-of-bounds 检查；
8. Marp PDF 构建；
9. PDF 页面、文字层、字号、裁切和内部词检查。

### 临时 HTML 溢出检查

框架运行 Marp HTML 输出到临时目录，再用 Playwright 遍历：

```css
section[data-marpit-scope], .marpit > section
```

逐页比较实际：

```text
scrollWidth / clientWidth
scrollHeight / clientHeight
```

并检查直接子元素越界、重复 slide ID、浏览器错误、本地请求失败和非预期外部请求。临时 HTML 随检查目录删除。

机械 overflow 是 author/release 的阻塞式自检，**不是 reviewer 工作**。

### 数学排版检查

只保留两个机械层次：

```text
MATH-SOURCE-INVENTORY
MATH-RENDERER-PROBE
```

不建立 `MATH-PDF-EVIDENCE`。source 层检查 delimiter、environment 和命令；HTML renderer 层检查 MathJax/KaTeX/MathML 节点、renderer error 和原始 TeX 泄漏。通过不代表公式在数学上正确，domain-accuracy reviewer 仍需完整判断数学内容。

## 10. 唯一一次五通道审核

冻结稿由五个隔离通道并行审核：

```text
language
domain_accuracy
layout
pedagogy
audience
```

layout reviewer 只评价信息层级、语义分组、密度、节奏和呈现设计，不重复做机械 overflow。

reviewer 在聚合前可受限重提交，但只能改：

```text
location
evidence_path
reviewer_note
```

finding ID、channel、issue、learner impact、acceptance criteria 和 verification method 不得改变。

review coordinator 先验证全部五个当前 handoff；任何一份失败都不修改共享 registry。全部通过后一次性提交，并根据冻结 `DECK-MANIFEST.yaml` 生成：

```text
finding → slide/source → 原 lesson-author 或 author-coordinator
```

无法路由便 fail closed。作者逐条回应、修改并重跑全部机械门，随后直接发布；没有 reviewer recheck，也不检查 resolved。

## 11. 单一项目日志守护进程

所有角色把日志请求发给常驻 Python daemon。只有 daemon 写入：

```text
tasks/<slug>/logs/project.jsonl
```

调用者不打开各自日志文件，也不接触并发写入锁。daemon 内部串行化请求并写入单调递增的 `daemon_sequence`。

```bash
mpres log-daemon start
mpres log-daemon status
mpres log-daemon stop
mpres log tail <slug>
```

`start.sh`、`start.ps1` 和安全启动器会在 Codex 前启动 daemon。测试使用明确的 test transport，生产路径始终使用 daemon。

本项目**不实现 crash-recovery 子系统**；崩溃后由 planner 检查 task state、单一 project log、thread registry、checkpoint、handoff 和现有产物后决定继续或重启。

## 12. 确定性 current launch plan

机械调度由 Python 汇总，但不替 planner 写 assignment，也不创建 orchestration journal：

```bash
mpres orchestration author-plan <slug> --presentation p01
mpres orchestration review-plan <slug> --presentation p01
```

计划显示：

- assignment 是否 ready；
- unit 当前内部 stage；
- 是否应启动、复用或继续同一 thread；
- 可复用 handle；
- 实际 model/effort 政策；
- 所需新 handle 和 capacity preflight。

`--save` 只覆盖一个当前 plan 文件，不保存 attempt 历史。

## 13. 线程生命周期

`THREAD-REGISTRY.yaml` 记录 handle、实际 model/effort、当前 assignment、独立性标签和 handoff。规则包括：

- planner thread 必须符合 Sol/max；
- workers 必须符合 Sol/high；
- author thread 不得审核自己参与制作的 deck；
- 五个 reviewer 使用独立 active handles；
- idle compatible handle 优先复用；
- interrupt 不等于真正释放容量；
- capacity preflight 必须保留配置的余量。

## 14. Extracted-text-only 参考资料

系统 ingestion 可以接收 PDF，但 worker 只能看到：

```text
downloads/text/
```

禁止 worker 打开、解析、渲染、转换、OCR 或截图原 PDF。抽取文本不足时，只能记录 source gap、寻找已批准文本/网页资料、收缩表述或升级范围问题。

## 15. GeoGebra 与 Python 图形

GeoGebra：

- 只允许已验证的 `https://www.geogebra.org/m/...`；
- 只用普通描述性 Markdown 超链接；
- 不嵌入、不截图、不下载 applet；
- 同一资源可在不同课次重复使用，不做去重硬门。

Python 图形默认关闭。只有 TASK 和 exact asset decision 双重批准才可使用。优先顺序：

```text
自然语言/公式 → Markdown 表格 → CSS → 简单 SVG → 合法已有资源 → Python 图形
```

## 16. Corrective maintenance

已发布 deck 可以进入：

```text
targeted_patch
full_corrective_review
```

planner 亲写 maintenance assignment；历史 release 不覆盖。targeted patch 只改授权缺陷并重跑机械门。full corrective review 进行一次新的五通道完整审核，作者自行修订后直接发布，不复核。新版本发布到：

```text
deliverables/<id>/revisions/rNNNN/
```

`CURRENT-REVISION.json` 指向当前版本。

## 17. 明确不实现的系统

v0.5.0 有意不实现：

- crash-recovery/resume orchestration subsystem；
- workflow-engine freeze/migration subsystem；
- `MATH-PDF-EVIDENCE`；
- token 与 orchestration attempt 的关联；
- reviewer 对 author revision 的二次验收；
- persistent HTML delivery；
- non-TASK hashes。

## 18. 安装与启动

要求：

- Python 3.11+；
- Node.js 18+ 和 npm；
- Codex CLI；
- Chromium/Chrome；
- `pdftotext`；
- Tesseract 仅供 system ingestion 的最后手段。

```bash
python scripts/bootstrap.py
./start.sh
```

安全模式：

```bash
./start-safe.sh
```

Windows：

```powershell
.\start.ps1
# 或
.\start-safe.ps1
```

Marp 版本不固定，`package-lock.json` 禁止提交。环境兼容性由：

```bash
.venv/bin/mpres doctor --strict
```

实际执行 Marp PDF 和浏览器 probe 判断。

## 19. 常用命令

```text
mpres task ...
mpres policy ...
mpres assignment ...
mpres production ...
mpres stage start|submit|status|reopen ...
mpres orchestration author-plan|review-plan ...
mpres thread capacity|register|assign|handoff|release ...
mpres render ...
mpres inspect html-layout ...
mpres review ...
mpres maintenance ...
mpres audit ...
mpres log-daemon ...
mpres log tail ...
```

## 20. 安全边界

`--dangerously-bypass-approvals-and-sandbox` 只能在外部隔离 VM/container 或专用低权限账户中使用。项目状态、目录与 audit 能减少普通流程漂移，但不能替代操作系统权限隔离。详见 `docs/SECURITY.md`。
