---
name: problem-diagnosis
description: 解释给定问题证据，或在返修前展开用户指出的问题族；不是自动改稿、运行状态恢复或用户确认。
---

# 只读诊断：区分事实、假设、范围和处理方向


## 1. 先识别诊断用途

普通有界诊断只解释当前证据；repair_scope 的 diagnose 是返修前问题展开。
运行器选取 [模式说明](references/modes.md)，不要把两者当作直接改稿许可。
只读，writable_directory 为 null 时不能写 source；输出 diagnosis-result。
共同边界见 [learning-contract](../_shared/learning-contract.md)。

## 2. 事实、假设、未观察严格分开

先指出具体页面/公式/标记/报告中的现象，再提出根因。看不到的页面不能写 observed。
例如合法 Markdown 表格的列难区分：先确认源码表格和主题证据；可能是全局 table 样式，
不能直接要求作者写 HTML。数学图错位先比较数学输入与生成结果，别笼统说模型视觉差。
工具报错、模型输出错误与宿主回执丢失是不同事实，不能互相推出。

## 3. 根因的最小核验

数学：给适用条件、可代回的数值或反例，检查错误是否真的存在。
教学：指出学生需要猜什么、删去哪些陈述无损学习；注意证明深度是否被旧要求误导。
工具：引用真实错误及最小相关源码，给可复现步骤/缺少证据；不编造运行结果或自动更改环境。
权限/资料：明确需要哪种补证和范围，不能因此扩大访问目录或更换 runtime。

## 4. 建议有边界

每个 hypothesis 写 explanation 与真实 slide_ids；confidence 是对诊断可信度，不是换模型指令。
recommended_action 只能用本次 schema 的 no_change/scoped_revision/more_evidence/full_review。
指出无关正确内容/条件/出处不应误伤。不因为“需要保证质量”默认多派 reviewer 验修。
范围应由实际证据和用户问题决定，不让一个微小词句问题膨胀为全课重写。

## 5. 交接

summary 说明已观察问题、主假设和关键不确定性；不自报已修复、已通过门禁或已获用户许可。
没有必要输出时钟/日志/状态等字段。确认返修前只交 expansion 提案，后续仍等用户审阅确切版本。
