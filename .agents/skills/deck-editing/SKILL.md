---
name: deck-editing
description: 处理组装稿的语义整合、本轮 finding 修订或机械失败后的内容修正；用户返修必须有确认范围。
---

# 整稿编辑：先识别模式，再对原稿做有界修改


## 1. 不把四种工作揉成一次重写

输入中的 kind、mechanical_findings、submission_correction、repair_scope 决定本次模式。
运行器会选取 [模式说明](references/modes.md) 中必要一段，不要自行执行所有分支。
共同边界见 [learning-contract](../_shared/learning-contract.md)，包内已包含时不重复读取。
正常首次整编关注衔接；finding 修订针对本轮问题；机械纠错只修失败原因；
确认返修是在指定问题族内改指定旧稿，不把整个课程重新写一遍。

## 2. 读准基线与证据

以本次提供的可写副本为修改起点；frozen_source/historical_release 是只读证据。
不要复制旧主题/旧 SVG 覆盖已经由 runner 准备的新副本。已有作者草稿不自动恢复到初始稿。
完整正文必须读，相关图片/教材可按需读；作者自评不是事实依据。原页的错误引用建议也要核算，
reviewer 可能给错公式，不能为了回应它照抄错误修改。

## 3. 编辑的共同质量问题

检查跨课术语、符号、变量含义和先修衔接；用学习损失删除反事实去掉无用文字。
遵照 proof_depth，而不是保护每一段正确证明。案例应服务模型，结论应讲清数学所得，
不把“已添加现实案例/几何直观”变成新的学生页面。
保留必要条件、来源与模型限制。改公式后代回原题；改图后重生成并检验关系。

## 4. 页面与权限

一般保留原 slide ID。**只有 repair_scope.allow_slide_changes 为真**才按确认范围删整页/合并，
逐个消失原 ID 给累计 slide_changes；未删除页保留 ID，不全稿换号。
可删无意义的句子、改解释和拆内容，但不能未经授权把冻结页悄悄消失。
项目 CSS、页面布局和源码契约不随本次问题改变；主题缺陷属于项目维护，不用正文补丁掩盖。

## 5. 交接给程序，不另建验修循环

只输出当前源码/资产与 author-result。finding 修订给逐项 resolutions，确认返修给 repair_checks，
实际删并给 slide_changes；不用同一段“已解决”复制给所有不同问题。
addressed 是作者的处置声明，不是独立再次验证。未解决给 needs_decision 和具体待决点。
作者自行复算、源检后由程序完成机械门禁；不要求增加 reviewer 验修轮次或写额外自检长文。
