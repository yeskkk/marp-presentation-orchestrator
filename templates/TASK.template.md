# TASK — [[TASK_TITLE]]

> **Task directory:** `tasks/[[TASK_SLUG]]/`  
> **Task type:** `[[TASK_KIND_CODE]]`  
> **Course meetings:** [[SESSION_COUNT_OR_NA]]  
> **Nominal minutes per meeting:** [[MINUTES_OR_NA]]  
> **Delivery mode:** `[[STOP_MODE]]`  
> **Default worker policy:** `gpt-5.6-sol`, reasoning effort `high`  
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
5. 项目只交付 Marp 源和 PDF，不生成、保存或审核 HTML。
6. 除本文件确认门外，不生成或检查哈希。
7. 所有 worker 默认 `gpt-5.6-sol/high`；极难研究报告可由用户明确提高到 `max`。
8. worker 只能读取 `downloads/text/` 中的抽取文本。任何原 PDF 即使物理存在也禁止打开、解析、渲染、转换、OCR、截图或交给视觉模型。
9. Python 作图默认关闭；GeoGebra 仅可做有界站内搜索并以普通超链接引用。
10. planner 亲自编写每个逻辑 worker 和每个 authoring stage 的精确 assignment；coordinator 只能提交 assignment request，不能代写。

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

## 4. 总体逻辑大纲

[[OVERALL_OUTLINE]]

时长只用于校准材料总量；content unit 按逻辑关系划分，不按分钟机械切块。

## 5. presentation 与 content-unit 图

[[PRESENTATION_PLAN]]

课程中一个 content unit 对应一节课；报告按逻辑章节拆分。[[AUTHORING_STAGE_DESCRIPTION]] lesson authors 允许有界并行，author coordinator 统一术语、对象、例题、互动与最终 `presentation.md`。

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

每个 content unit 按任务类型对应的阶段执行；planner 为每一阶段亲自写精确 assignment：

[[AUTHORING_STAGE_LIST]]

阶段之间允许带理由回退。[[MCQ_STAGE_REQUIREMENT]]

## 10. 执行、并发与模型

机器策略：

- `EXECUTION-POLICY.yaml`
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

- planner：规划、确认、亲自写全部精确 assignments、政策审计、二十分钟/交付事件高层监督。
- author-coordinator：结构化设计、请求 assignment、监督 staged lesson authors、整合、构建、自检和 post-review revision。
- lesson-author：一个 content unit 的一个 active stage，不改其他单元。
- specialist-reviewer：唯一一轮中的一个通道，不看其他通道或后续修订。
- review-coordinator：验证 planner assignments、监督五通道并聚合，不写 assignment、不改 findings。
- release-coordinator：只检查作者回应覆盖和机械门，直接发布；不判断 finding 是否修好。

## 13. 验收标准

[[ACCEPTANCE_CRITERIA]]

至少包括：覆盖、领域正确性、自然语言、听众契合、课程 unit 每个 2—3 道合格 MCQ、题答相邻分页、结构化地图一致性、Marp lint、PDF 页数/几何/文本层、本地资产、GeoGebra 规则、text-only 来源、一轮五通道报告、作者逐项回应、自修订记录和直接发布记录。

## 14. 规划者确认清单

[[PLANNER_CONFIRMATION_NOTES]]
