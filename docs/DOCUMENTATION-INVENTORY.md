# 文档盘点与归属

以实际 v0.7.5 源码为基线，不用修改日期推断是否过时。问题类型：
规则已经被代码替代、旧/新入口并列、技能跨角色重复、README按版本追加导致前后矛盾。

## 现行入口

| 位置 | 使用者 | 更新依据 |
|---|---|---|
| README、AGENTS | 用户/main | 已实现整体步骤、确认与权限边界 |
| docs/WORKFLOWS | main/维护者 | 新建、续作、两种返修、恢复、迁移分别说明 |
| docs/OPERATIONS、HOST-PROTOCOL | 操作员/适配器 | 实际 CLI 和 runner.accept，不给 worker 当教学 prompt |
| docs/CONTENT-CONTRACT | 维护者/内容作者按需 | source_policy、geometry、固定主题 |
| .agents/skills 十项教学语义＋一项 main 按需运行维护 | 指定角色 | 一般判断方法与角色边界，不包含维护校准样例 |
| templates/compact 三项配置＋练习索引/保留策略样例 | 用户或对应程序 | Service.create 仍只复制三份配置 |
| control/schemas 四项语义＋练习索引、保留策略、程序用量报告 | 对应程序/语义消费者 | 结构校验不代替实际证据 |

## 整顿后的边界

旧模板从当前 templates 路径移到 compat/legacy/templates，逐文件保留原字节，仅旧加载器改路径。
模板数量不靠隐藏 symlink 或双份副本维持；新任务不读兼容目录。
配置默认值/runtime 不改；TASK 提问方式和注释重写，学生正文与备课字段分开。
README 原来的同段追加模式替换为导航＋明确工作流，删除“以后支持”与已支持能力矛盾的旧描述。
五个审核通道各有完整 skill，guidance.py 按实际角色/模式选取，来源写入请求包。
TASK 在真实会话首次实质工作时提供一次，后续复用；audience 完整方法首次提供，之后聚焦当前步骤。
具体事故与可校验结果样例移到 tests/fixtures/semantic，维护方法在 docs/development，均不注入运行输入。
原 .codex/agents 文件集合、runtime 配置、三份 compact 模板与四类结果 schema 保持不变。

## 兼容模板完整清单

下表的直接消费者来自 Python 字面名称扫描，不声称穷尽所有动态调用。
没有静态命中的模板不能贸然删除；其性质仍为兼容材料，绝不成为新 worker 必读。

| 相对于 compat/legacy/templates | 直接消费者或分类 |
|---|---|
| `TASK.template.md` | `tasks.py` |
| `assignments/TASK-author-coordinator.template.md` | `production.py` |
| `assignments/TASK-deck-revision-author.template.md` | `production.py` |
| `assignments/TASK-diagnostic-reviewer.template.md` | `diagnostics.py` |
| `assignments/TASK-lesson-author.template.md` | `production.py` |
| `assignments/TASK-maintenance.template.md` | `maintenance.py` |
| `assignments/TASK-specialist-reviewer.template.md` | `review.py`, `maintenance.py` |
| `context/FULL-REVIEW-CONTEXT.template.md` | `review.py` |
| `policies/CLASSROOM-SELF-CONTAINMENT-STANDARD.template.md` | `tasks.py` |
| `policies/EXECUTION-POLICY.template.yaml` | `tasks.py` |
| `policies/MARP-AUTHORING-STANDARD.template.md` | `tasks.py` |
| `policies/POLICY-AMENDMENT.template.md` | 动态文件名/兼容资料；不属新任务入口 |
| `policies/POLICY-AMENDMENT.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `policies/POLICY-CHANGE-REQUEST.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `policies/POLICY-PRECEDENCE.template.yaml` | `tasks.py` |
| `policies/REFERENCE-ACCESS-POLICY.template.yaml` | `tasks.py` |
| `policies/REVIEW-PROFILE.template.yaml` | `tasks.py` |
| `policies/REVIEW-PROTOCOL.template.md` | `tasks.py` |
| `policies/TASK-RUNTIME-PROFILE.template.yaml` | `tasks.py` |
| `policies/THREAD-LIFECYCLE.template.md` | `tasks.py` |
| `policies/TOKEN-COLLECTOR-POLICY.template.yaml` | `tasks.py` |
| `policies/WORKER-ASSIGNMENT-WRITING-STANDARD.template.md` | `tasks.py` |
| `policies/WORKER-PROMPT-PREAMBLE.template.md` | `tasks.py` |
| `presentation-header.template.md` | `production.py` |
| `review/review-aggregate.template.md` | 动态文件名/兼容资料；不属新任务入口 |
| `review/review-finding.schema.json` | 动态文件名/兼容资料；不属新任务入口 |
| `review/review-report.template.md` | `review.py`, `maintenance.py` |
| `section.template.md` | `production.py` |
| `stages/STAGE-01-SCOPE-SOURCES.template.md` | `stages.py` |
| `stages/STAGE-02-LEARNER-NEED.template.md` | `stages.py` |
| `stages/STAGE-03-DOMAIN-DEVELOPMENT.template.md` | `stages.py` |
| `stages/STAGE-04-ENTRY-DIAGNOSTICS.template.md` | `stages.py` |
| `stages/STAGE-05-LEARNER-LANGUAGE.template.md` | `stages.py` |
| `stages/STAGE-06-MARP-INTEGRATION.template.md` | `stages.py` |
| `stages/STAGE-GATE-REPORT.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `stages/STAGE-M01-BASELINE-AUDIT.template.md` | `stages.py` |
| `stages/STAGE-M02-DELTA-DESIGN-PATCH.template.md` | `stages.py` |
| `stages/STAGE-M03-INTEGRATION-SEMANTIC-CHECK.template.md` | `stages.py` |
| `stages/STAGE-R01-DEFECT-SCOPE.template.md` | `stages.py` |
| `stages/STAGE-R02-PATCH-REGRESSION.template.md` | `stages.py` |
| `stages/STAGE-REPORT-02-AUDIENCE-DOMAIN.template.md` | `stages.py` |
| `stages/STAGE-REPORT-03-NARRATIVE-LANGUAGE.template.md` | `stages.py` |
| `stages/STAGE-REPORT-04-MARP-INTEGRATION.template.md` | `stages.py` |
| `stages/STAGE-REPORT-COMPACT.template.md` | 动态文件名/兼容资料；不属新任务入口 |
| `stages/UNIT-STAGE-STATE.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/ASSET-DECISIONS.template.yaml` | `production.py` |
| `structured/ASSIGNMENT-BRIEF.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/ASSIGNMENT-DECISION.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/ASSIGNMENT-REQUEST.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/AUTHOR-CONTEXT-PACKET.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/AUTHOR-MODIFICATION-CHECKLIST.template.yaml` | `production.py`, `review.py` |
| `structured/AUTHOR-RESPONSES.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/AUTHOR-REVISION-COMPLETE.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/AUTHOR-REVISION.template.md` | `production.py` |
| `structured/BATCH-ASSIGNMENT-EXPANSIONS.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/BATCH-ASSIGNMENT-PLAN.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/CHECKPOINT.template.json` | `tasks.py` |
| `structured/CORRECTIVE-CYCLE.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/CORRECTIVE-SCOPE.template.md` | `maintenance.py` |
| `structured/COURSE-LANGUAGE-REGRESSION.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/COURSE-SEMANTIC-OBJECTS.template.yaml` | `course_consistency.py` |
| `structured/COURSE-TERMINOLOGY.template.yaml` | `course_consistency.py` |
| `structured/CROSS-DECK-HANDOFFS.template.yaml` | `course_consistency.py` |
| `structured/DECK-MANIFEST.template.yaml` | `production.py` |
| `structured/DIAGNOSTIC-CASE.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/DIAGNOSTIC-RESULT.template.yaml` | `diagnostics.py` |
| `structured/ENGINE-INCIDENT.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/EXAMPLE-MAP.template.md` | `production.py` |
| `structured/GEOGEBRA-RESOURCES.template.yaml` | `production.py` |
| `structured/GEOGEBRA-UNIT-RESOURCES.template.yaml` | `production.py` |
| `structured/INCIDENT-INDEX.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/INCIDENT-OCCURRENCE.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/INTERACTION-MANIFEST.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/INTERACTION-RECORD.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/LEARNER-LANGUAGE-FINDING.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/LESSON-TIME-PLAN.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/LESSON-TIME-PLANS.template.yaml` | `production.py` |
| `structured/MAINTENANCE-CHECKLIST.template.yaml` | `maintenance.py` |
| `structured/MAINTENANCE-RETROSPECTIVE.template.md` | `review.py`, `maintenance.py` |
| `structured/MATH-RENDERER-PROBE.template.json` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/MATH-SOURCE-INVENTORY.template.json` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/MCQ-AUDIT.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/MILESTONE-CHECKPOINT.template.json` | `tasks.py` |
| `structured/OPERATIONAL-WORKAROUND.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/PATCH-SCOPE.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/PEDAGOGY-MAP.template.md` | `production.py` |
| `structured/PERFORMANCE-BUDGET.template.yaml` | `tasks.py` |
| `structured/POST-REVIEW-REVISION.template.md` | `revision_routing.py` |
| `structured/PRESENTATION-CONTINUITY-MAP.template.yaml` | `production.py` |
| `structured/PRESENTATION-WORK-PLAN.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/PRODUCTION-PROFILE.template.yaml` | `tasks.py` |
| `structured/RELEASE-JOB.template.yaml` | `control_jobs.py` |
| `structured/RELEASE-RETROSPECTIVE.template.md` | `production.py` |
| `structured/REVIEW-AGGREGATION-JOB.template.yaml` | `control_jobs.py` |
| `structured/REVIEW-PLAN.template.yaml` | `review.py` |
| `structured/REVISION-ROUTING.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/SELF-CHECK.template.md` | `production.py` |
| `structured/SEMANTIC-OBJECTS.template.yaml` | `production.py`, `course_consistency.py` |
| `structured/SLIDE-DENSITY-AUDIT.template.yaml` | `production.py` |
| `structured/SOURCE-GAPS.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/TERMINOLOGY-YAML.template.yaml` | `production.py` |
| `structured/TERMINOLOGY.template.md` | `production.py` |
| `structured/THREAD-CLOSE-REPORT.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/THREAD-HANDOFF.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/THREAD-REGISTRY.template.yaml` | `tasks.py` |
| `structured/TOOLCHAIN-LOCK.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/UNIT-CONTEXT-PACKET.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/UNIT-DELTA.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |
| `structured/UNIT-MANIFEST.template.yaml` | 动态文件名/兼容资料；不属新任务入口 |

## v0.9 当前增量

练习规则进入活动指南；教材缓存和输入预检由程序执行；维护/计量文档仅 main 按需读取。
本轮未改兼容模板，不为 legacy 模板增加或执行专项测试。
