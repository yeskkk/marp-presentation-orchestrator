# 语义结果：字段属于谁，什么时候需要

本页用于维护和宿主接入。worker 按本次请求中的 result_schema 与 required_result 输出，
不是照抄一份固定示范 JSON。权威结构在 control/schemas，实际证据约束还在 service/feedback/repairs。

## 1. 三种内容不要混在一个对象里

| 层 | 来源 | 内容 |
|---|---|---|
| 学生内容 | author 输出 Markdown/资产 | 解释、公式、题目、图与必要来源 |
| 语义 result | 指定 AI 角色 | 教学总结、发现/处置、真实页内证据和待决 |
| provider/程序事实 | 宿主/runner | receipt/runtime/usage、身份、序号、gate、发布 |

不要把 source_dir 或 receipt 塞到语义 result，不要让 result 声明 gate_passed/capacity_released。
存在 source_dir 的外层响应必须是作者类，且在本次允许 output 内。

## 2. 四类结果及条件义务

| schema | 通常字段 | 条件义务 |
|---|---|---|
| plan | presentations，按需 teaching | 每稿 id/title/units；每课 id/title/brief/sources，不额外造阶段/人员字段 |
| author-result | summary；可选 teaching_notes/open_questions | 每次回应实际 feedback；revise 对每条本轮 finding 给 resolutions；确认返修给 repair_checks；获准删/并给 slide_changes |
| review-result | summary、findings | 每条只有 message/slide_ids/severity；feedback issue 要有可路由 finding；返修覆盖确认问题族；audience final 不丢前序发现 |
| diagnosis-result | summary、hypotheses、confidence、affected_slide_ids、recommended_action | 返修前 diagnose 必须有 expansion；普通有界诊断不据此直接改稿 |

feedback_checks 的 id/version 必须来自本次 historical_feedback，quote 必须实际位于所引页面。
不是“每类三项都满足”的自证；可 not_applicable 但须说明真实内容的原因，不能凭所属通道跳过。
不足不得伪造来源或 satisfied；下游尚未发生是执行事实，不要在学生页写“以后补资料/等待审核”。
当前 runner 的 issue 限制不能通过文档补句子绕过，范围或权限问题要明确待决。

## 3. 编辑特有字段

resolutions: finding_id、addressed/needs_decision、explanation，说明原问题、具体修改和作者复算。
处置必须回应同一个 finding 的对象与问题，不能以不相关的改进替代；这不是独立验修结果。
repair_checks: problem_id、addressed/not_found/needs_decision、explanation、真实 slide_ids。
slide_changes: 原 slide_id、delete/merge、target_slide_id（delete为null）、reason；
仅确认允许结构调整时使用，累计对应原返修基线。没有删除的页保留 ID。

## 4. audience 子步骤不是新的 schema 文件

student / production_language 返回 phase/read_slide_ids/summary/observations/findings。
有 attention_candidates 的第二步还必须逐项 attention_checks：candidate_id、disposition、
learning_loss_if_removed、reason、finding_index。keep 使用 null；remove/rewrite/move_to_notes
指向本步 findings 的零基索引，且同页。候选不是定罪/删词表，完整段落仍要读。

前序 completed 步骤不用重做。最终 run 原样保留之前的 findings，同时给整轮真实反馈检查。
不要为“完整性”制造正面 observations，也不能在最后静默丢掉难修问题。

## 5. 维护资料不进入任务

worker 只使用当前 result_schema、required_result 与真实任务证据，不读取校准样例作为工作方法。
具体正反例在 tests/fixtures/semantic，仅供源码维护和回归验证，详见开发目录中的语义维护说明。
它们既不是课件模板，也不构成真实作业的 ID、阅读或执行证明。
