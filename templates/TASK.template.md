# TASK — [[TASK_TITLE]]

> **Task directory:** `tasks/[[TASK_SLUG]]/`  
> **Task type:** [[TASK_KIND]]  
> **Course meetings:** [[SESSION_COUNT_OR_NA]]  
> **Nominal minutes per meeting:** [[MINUTES_OR_NA]]  
> **Delivery mode:** `[[STOP_MODE]]`  
> **Default model policy:** `gpt-5.6-sol`, reasoning effort `medium`  
> **Plan status:** awaiting explicit user confirmation of this exact `TASK.md`

## 1. 任务名称、内容简介与范围

**名称：** [[TASK_NAME]]

**目录名：** `[[TASK_SLUG]]`

**内容简介：**

[[CONTENT_DESCRIPTION]]

**范围内：**

[[IN_SCOPE]]

**明确不做：**

[[OUT_OF_SCOPE]]

## 2. 开始工作前已经提醒用户的固定规则

1. 每份 presentation 必须经过三轮审核：初审全稿、增量复审、终审全稿；终审后的作者修订只进入放行闭环，不构成第四轮探索性审核。
2. 每轮都有五个独立通道：语言、领域正确性、版式与 PDF 成品行为、教学编排、听众契合。
3. 审核禁止截图、PDF 栅格图、联系表和模型视觉；使用 Markdown 源、结构化清单、Marp 日志、PDF 页面几何与文本层作为证据。
4. 只交付 Marp 源和 PDF。Marp CLI 可以在内部借助浏览器生成 PDF，但项目不生成、不保存、不审核 HTML。
5. 除本文件的用户确认门外，不生成或检查任何哈希码。
6. 默认推理强度为 `medium`；研究级、学术报告、陌生领域或高风险事实核验应在确认阶段提高到 `high` 或 `max`。
7. Python 作图默认关闭。只有 TASK.md 明确允许、且资产决策表说明表格、公式、CSS 或普通图片无法完成同一教学任务时，才可生成图形。
8. 对适合动态数学探索的内容，author 应做一次有界的 `geogebra.org` 站内检索；仅可选用公开 material，并且只能作为普通 Markdown 超链接引用。禁止嵌入、下载、截图、预览图或二维码；不相关或找不到合适资源时记录理由后停止。

## 3. 目标听众

### 3.1 已有知识和经验

[[AUDIENCE_PRIOR_KNOWLEDGE]]

### 3.2 可能的薄弱处和误解

[[AUDIENCE_LIKELY_WEAKNESSES]]

### 3.3 听众希望获得什么

[[AUDIENCE_EXPECTED_GAINS]]

### 3.4 先前课程内容

[[PRIOR_COURSE_CONTEXT_OR_NA]]

先前出现过的内容只能视为“见过”，不能直接视为已经掌握；每份 assignment 都要写明需要重新激活的最小知识。

## 4. 总体逻辑大纲

内容按逻辑关系划分，不按时长机械切片。时长只用于校准材料总量。

[[OVERALL_OUTLINE]]

## 5. presentation 单元与课次/内容单元

[[PRESENTATION_PLAN]]

每份课程课件把每节课拆成一个独立内容单元，交给一个 `lesson-author`；报告把每个逻辑段落视为内容单元。内容单元可以并行制作，由 `author-coordinator` 统一术语、语义对象、例题角色、主题 CSS 和最终 `presentation.md`。

## 6. 总体演讲策略

[[OVERALL_PRESENTATION_STRATEGY]]

至少说明：为什么主题值得关心、听众进入新概念的认知入口、直觉与精确表述的次序、正例与反例如何建立边界感、例题承担的迁移作用、复杂计算如何压缩、表格何时优先于图形，以及提高内容如何照顾认真学生而不压垮主要叙事。

## 7. Marp 与视觉策略

- 基础主题：[[MARP_THEME_DECISION]]
- 页面比例：[[MARP_SIZE_DECISION]]
- HTML 标签：只在 Markdown 表格和原生 Marp 语法无法表达必要结构时使用；最终仍只输出 PDF。
- 插图策略：[[IMAGE_POLICY_DECISION]]
- Python 作图：[[PYTHON_ASSET_DECISION]]

视觉不是“尽量多画图”。优先顺序通常是：简洁文字与公式 → Markdown 表格 → CSS 双栏/提示框 → 已有且合适的本地图片 → 经批准的 Python 图形。

## 8. 参考资料

[[REFERENCES_AND_USES]]

共享资料统一放在 `tasks/[[TASK_SLUG]]/downloads/`；抽取文本用于检索，公式、图表、精确引文和页码仍须回看原件。

GeoGebra 属于可选在线探索资源，不属于课件的必需依赖。lesson author 在适用时记录站内检索；author coordinator 决定是否选用。课件离线打开和不访问链接时仍须完整可讲。

## 9. 执行、并发和推理强度

机器可读策略位于：

- `tasks/[[TASK_SLUG]]/EXECUTION-POLICY.yaml`
- `tasks/[[TASK_SLUG]]/REVIEW-PROFILE.yaml`

推理强度决定：

[[REASONING_EFFORT_DECISION]]

并发安排：

[[PARALLELISM_DECISION]]

## 10. 交付与暂停方式

`[[STOP_MODE]]` 的含义：

- `pilot`：先完整交付第一份课件并暂停一次，等待用户根据真实 PDF 反馈；继续后，其余课件按计划推进。
- `each`：每份课件交付后暂停。
- `all`：所有计划课件交付后才暂停。

本任务的具体说明：

[[DELIVERY_MODE_NOTES]]

## 11. 角色边界

- `planner`：采访、规划、确认门、分配 presentation、每二十分钟或收到一份课件交付事件时做一次高层监督；不写逐页内容。
- `author-coordinator`：建立结构化教学设计，拆分内容单元，监督并行 lesson authors，整合 `presentation.md`，回应 findings。
- `lesson-author`：只完成一个课次/内容单元及其结构化证据，不改其他单元。
- `specialist-reviewer`：只在指定通道和指定轮次独立审核，不改作者源。
- `review-coordinator`：监督五通道审核，验证报告完整性，汇总但不弱化 finding，推动三轮闭环。
- `release-coordinator`：终审后验证 closure，做机械最终构建和发布；不得新增实质意见。

## 12. 验收标准

[[ACCEPTANCE_CRITERIA]]

至少包含：内容覆盖、领域正确性、听众契合、自然语言、例题迁移、结构化地图一致性、Marp 源 lint、PDF 页数和页面几何、PDF 文本层、字体可读性、本地资产、三轮审核记录和终审后放行记录。

## 13. 规划者的确认清单

[[PLANNER_CONFIRMATION_NOTES]]
