# TASK — [[TASK_TITLE]]

> **Task directory:** `tasks/[[TASK_SLUG]]/`  
> **Task type:** `[[TASK_KIND_CODE]]`  
> **Course meetings:** [[SESSION_COUNT_OR_NA]]  
> **Nominal minutes per meeting:** [[MINUTES_OR_NA]]  
> **Delivery mode:** `[[STOP_MODE]]`  
> **Production mode:** `[[PRODUCTION_MODE]]`  
> **Authoring stage profile:** `[[AUTHORING_STAGE_PROFILE]]`  
> **Task runtime profile:** user-editable `TASK-RUNTIME-PROFILE.yaml`; defaults are planner `gpt-5.6-sol/high`, author `gpt-5.6-sol/medium`, reviewer `gpt-5.6-sol/low`  
> **Plan status:** awaiting explicit user confirmation of this exact `TASK.md`

## 1. 任务名称、简介与范围

**名称：** [[TASK_NAME]]

**目录：** `[[TASK_SLUG]]`

[[CONTENT_DESCRIPTION]]

### 范围内

[[IN_SCOPE]]

### 明确不做

[[OUT_OF_SCOPE]]

## 2. 开始工作前已经提醒用户的固定规则

1. 每份 presentation 只做一轮完整审核；五个独立通道同时审核完整冻结稿。
2. 作者逐条回应 findings、完成修改、自检和重新构建后，直接进入机械发布；修订稿不返回 reviewer，findings 不维护 resolved 状态。
3. **课程的每个 content unit 必须包含 2—3 道诊断性选择题。** 学术报告/普通报告不设这一配额。
4. 审核禁止截图、PDF 栅格化、联系表和模型视觉；只使用 Marp 源、结构化记录、构建日志和 PDF 页面几何/文本层。
5. 项目只交付 Marp 源和 PDF。author/release 可生成临时 Marp HTML 做机械溢出自检，但检查后必须删除，且 reviewer 不检查该 HTML。
6. 除本文件确认门外，不生成或检查哈希。
7. 用户在确认任务前自行检查和修改 `TASK-RUNTIME-PROFILE.yaml`。默认 planner 为 `gpt-5.6-sol/high`、author 为 `gpt-5.6-sol/medium`、reviewer 为 `gpt-5.6-sol/low`。可以按角色、review 通道或 presentation 细分，但 agent 不得自行决定，也不得在任务运行时动态改动。
8. worker 只能读取 `downloads/text/` 中的抽取文本。任何原 PDF 即使物理存在也禁止打开、解析、渲染、转换、OCR、截图或交给视觉模型。
9. Python 作图默认关闭；GeoGebra 仅可做有界站内搜索并以普通超链接引用。
10. planner 对 assignment 的语义内容负责。planner 可以审批一份结构化 batch plan，由程序机械展开每个 unit 的精确 assignment；这种展开仍视为 planner 编写。**只有撰写或修订顶层 `TASK.md` 必须由主 planner（main agent）亲自完成；其它 planner 工作均可委派给其它 planner。**

## 3. 目标听众

### 3.1 已有知识和经验

[[AUDIENCE_PRIOR_KNOWLEDGE]]

### 3.2 可能的薄弱处和误解

[[AUDIENCE_LIKELY_WEAKNESSES]]

### 3.3 期待获得的能力和理解

[[AUDIENCE_EXPECTED_GAINS]]

### 3.4 先前课程内容

[[PRIOR_COURSE_CONTEXT_OR_NA]]

先前出现过只能视为“见过”，不能直接视为掌握。assignment 必须写明本单元需要重新激活的最小知识。

## 4. 课程课次/报告结构

[[OVERALL_OUTLINE]]

课程必须按“第几节课”组织 content units；教材章节只作为参考来源和覆盖映射，不作为课件分节依据。报告仍可按逻辑部分组织。

课程时长采用宽松规划：名义时长定义自然下课点，默认可以准备约 1.5 倍材料。例如 40 分钟课堂可准备约 60 分钟课件；后约 20 分钟主要安排讲解例题。到点即可下课，不要求讲完。

## 5. presentation 与 content-unit 图

[[PRESENTATION_PLAN]]

课程中一个 content unit 对应一个按顺序编号的课次；不要按教材逻辑章节重新分节。报告按逻辑部分拆分。[[AUTHORING_STAGE_DESCRIPTION]] lesson authors 允许有界并行，author coordinator 统一术语、对象、例题、互动与最终 `presentation.md`。

## 6. 演讲策略

[[OVERALL_PRESENTATION_STRATEGY]]

至少说明：认知入口、直觉和精确表述次序、正反例、表示变化、必要计算、迁移例题、课程 MCQ 的诊断目标、活动价值、听众注意负担和提高内容安排。

## 7. Marp、页面与资产策略

- 主题：[[MARP_THEME_DECISION]]
- 页面比例：[[MARP_SIZE_DECISION]]
- 图片策略：[[IMAGE_POLICY_DECISION]]
- Python 作图：[[PYTHON_ASSET_DECISION]]

优先顺序通常是：自然语言/公式 → Markdown 表格 → CSS 布局 → 合适的本地资产 → 经批准的 Python 图。不要把普通表格画成图。

## 8. 参考资料与 text-only 协议

[[REFERENCES_AND_USES]]

worker assignment 只能引用抽取文本的路径、行号或检索词。文本不足时写 source-gap，改用其他批准文本、授权网页、收缩/删除表述或升级范围问题。**不得回看原 PDF。**

## 9. Authoring stages

每个 content unit 按所选 production profile 执行。planner 审批 batch plan 后，程序为每个 unit 展开一份精确 assignment；同一个固定 lesson-author thread 在该 assignment 下依次完成全部阶段：

[[AUTHORING_STAGE_LIST]]

每阶段只写该 profile 所需的 canonical artifact 与里程碑 checkpoint；`mpres stage submit` 验证后自动激活下一阶段，不重新 spawn、不另写 stage assignment，也不等待 coordinator 验收。迁移任务完全跳过绿地六阶段；阶段之间允许带理由回退。[[MCQ_STAGE_REQUIREMENT]]

## 10. 执行、并发与模型

机器策略：

- `EXECUTION-POLICY.yaml`
- `TASK-RUNTIME-PROFILE.yaml`
- `REVIEW-PROFILE.yaml`
- `REFERENCE-ACCESS-POLICY.yaml`
- `POLICY-PRECEDENCE.yaml`

[[REASONING_EFFORT_DECISION]]

[[PARALLELISM_DECISION]]

## 11. 交付与暂停

- `pilot`：先完整交付第一份课件，暂停等待用户反馈一次。
- `each`：每份课件后暂停。
- `all`：全部完成后暂停。

[[DELIVERY_MODE_NOTES]]

## 12. 角色边界

- main agent：唯一必须亲自撰写或修订顶层 `TASK.md` 的 planner；其余 planner 职责均可委派。
- delegated planner：可代行 batch plan、assignment 审批、政策审计、异常判断和高层监督；planner 仍拥有语义责任。
- author-coordinator：结构化设计、请求 assignment、监督当前关键路径上的 lesson authors、整合、构建、自检并冻结完整 deck；handoff 后可关闭。
- lesson-author：一个固定 content unit、一份 planner-approved assignment、一个连续 thread，依次完成所选 profile 的全部阶段；写 context packet 后可关闭，不负责 post-review revision。
- deck-revision-author：在唯一一轮审核后读取冻结稿、五通道 findings 与 `AUTHOR-CONTEXT-PACKET.yaml`，独立完成整份 deck 的回应、修订、自检和交接。
- specialist-reviewer：唯一一轮中的一个通道；五名 reviewer 都必须完整阅读整份冻结 deck，不看其他通道或后续修订。
- review-coordinator：验证 planner assignments、监督五通道并聚合，不写 assignment、不改 findings。
- release-coordinator：只在 `release_ready` 后启动，检查 deck-revision-author 的回应覆盖和机械门并直接发布；不判断 finding 是否修好，也不预先占用 thread。

纯技术 workflow-engine bug 也不得在任务中热修。必须建立 task policy amendment、修订并重新确认 `TASK.md`；引擎重构作为独立工作处理。

## 13. 验收标准

[[ACCEPTANCE_CRITERIA]]

至少包括：覆盖、领域正确性、自然语言、听众契合、课程 unit 每个 2—3 道合格 MCQ、题答相邻分页、按课次分节、宽松时间计划和自然停止点、结构化地图一致性、作者临时 HTML 溢出自检、Marp lint、PDF 页数/几何/文本层、本地资产、GeoGebra 规则、text-only 来源、一轮五通道报告、作者逐项回应、自修订记录和直接发布记录。

## 14. 规划者确认清单

[[PLANNER_CONFIRMATION_NOTES]]
