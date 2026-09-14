# 语义角色与阅读入口

先理解用户当前要规划、修改还是执行。任务确定后，所有角色建立一次完整 TASK 上下文；
同一线程后续复用，不因新 job、分段或修正反复阅读。角色指南不替代任务意图。

## 角色导航

| 工作 | 独立 skill |
|---|---|
| 课程规划 | [course-planning](course-planning/SKILL.md) |
| 单课写作 | [marp-writing](marp-writing/SKILL.md) |
| 整稿编辑、作者修订 | [deck-editing](deck-editing/SKILL.md) |
| 数学与领域准确性审核 | [domain-accuracy-review](domain-accuracy-review/SKILL.md) |
| 教学设计审核 | [pedagogy-review](pedagogy-review/SKILL.md) |
| 学生视角审核 | [audience-review](audience-review/SKILL.md) |
| 语言与术语审核 | [language-review](language-review/SKILL.md) |
| 信息布局审核 | [layout-review](layout-review/SKILL.md) |
| 问题诊断 | [problem-diagnosis](problem-diagnosis/SKILL.md) |
| 资源设计 | [resource-design](resource-design/SKILL.md) |

## 运行时读取

runner 根据 job 的实际 kind/channel/mode 提供共同教学边界、一个角色的完整方法和必要分支。
不能把五个审核者的职责拼成一个大 prompt，也不能只给每个 reviewer 一段泛泛提醒。
reviewer 都使用原 specialist-reviewer agent 定义和 reviewer runtime family，角色配置不拆分。
audience 首段提供完整角色方法，后续只提供当前步骤，最终只综合已经完成的阅读。

手动委派同样按已指定通道选择一个 skill，不自己选择五个角色，也不扫描所有 references。
编辑与诊断的分支说明仅在对应任务使用，不创建额外流程。共同教学原则见
[learning-contract](_shared/learning-contract.md)。具体权限和格式由当前请求及项目契约负责。

## 维护与运行分开

skills 写通用判断方法，不收集事故经过、旧题目、任务专名或校准题。
维护项目源码时可以使用测试素材检验方法与格式，但维护资料不注入语义作业、不要求 worker 阅读。
不以段落数、关键词黑名单或篇幅 lint 判断 skill 好坏；实际维护应审查职责、方法与输入输出是否对应。

main 只有在恢复、清理或用量分析时按需读取 [runtime-operations](runtime-operations/SKILL.md)。
该项不是第十一个内容角色，不提供新 reviewer 或常驻观察者；guidance.py 不把它装入 worker 包。
