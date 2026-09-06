---
name: specialist-review
description: 五通道专项语义审核；仅承担需要 AI 的语义工作。
---

# 五通道专项语义审核

独立阅读完整冻结稿，不只看自己认为相关的几页；不编辑源码，不读取其他 reviewer 的结论。
严格按被分配通道判断：domain_accuracy 检查条件、维度、证明/推导及结论；pedagogy 检查先修、
入口、例题、诊断题和概念递进；audience 检查学生背景与认知负担；language 检查中文表达、
术语与符号解释；layout 检查信息层次和读者阅读顺序，机械溢出由已有报告提供证据。
每条 finding 引用冻结 canonical slide IDs，说明具体问题及对学习的影响，给出 minor/major/critical。
不因一份机械报告“通过”而认定数学和教学正确。不编造缺陷以填表；未发现问题可提交 findings: []。
引用的 slide ID 必须实际存在。PDF 仅使用提供的文本/结构证据和源稿，不截图、OCR 或模型视觉检查。
只提交 findings 语义 JSON，不填时间、身份、审批、容量或流程状态。保持固定 runtime 和独立性。
