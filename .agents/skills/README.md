# 六个语义 skills 的阅读方式

## 不扫描全部内容

正常 worker 使用 packet.semantic_guidance，其中包含共同教学边界、一个角色正文、
当前 channel/mode 的必要小节。semantic_guidance_sources 记录来源与小节，已经在包内的文本
不再打开重读。operator/host 手册、templates 和 compat 不属于 worker 的默认输入。

## 两种入口

运行器调度：write→marp-writing；edit/revise→deck-editing；review→specialist-review 的单通道；
diagnose→problem-diagnosis 的有界/展开分支。audience_step 单独注入当前学生阅读或学习价值小节。
手动委派：先读所选 SKILL.md 及共同 learning-contract，再只读任务明确需要的引用小节。
course-planning 和 resource-design 是按需语义能力，不擅自创建一个新的机械角色池。

## 条件性说明

references/modes.md、channels.md、audience-steps.md 是按标题选择的内容，不是需要依次运行的阶段。
共同边界只写一处。每个 SKILL 以用途、输入、判断顺序、输出和失败边界组织，不按历史版本追加补丁。
选择逻辑在 control/guidance.py；未知/缺失小节应报错，不从 legacy 拼一份替代提示。

## 更新纪律

修改本体、对应分支、结果示例和路由测试；保留教学正反例。新规则不通过额外过程文件落地。
格式/结构测试不能证明模型理解，校准素材位于 examples/semantic/calibration-cases.json。
