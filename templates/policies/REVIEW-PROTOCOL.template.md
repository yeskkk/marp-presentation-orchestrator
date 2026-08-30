# 三轮五通道审核协议

## 三轮是全局硬规则

1. **初审 `initial`：全稿。** 五个通道独立阅读完整冻结快照，可以提出新 finding。
2. **增量复审 `incremental`：受限。** 只核查初审 findings、作者改动区域和由改动引起的 regression；不得借机重新发明一套全稿标准。
3. **终审 `final`：全稿。** 五个通道再次独立检查完整候选稿，可以发现初审未发现或修订后新显现的问题。

终审 findings 由作者做 terminal revision。之后的 release closure 只验证这些 finding 已按验收标准关闭、PDF 可以机械发布；它不是第四轮审核，不能新增实质 finding。

## 五个通道

- `language`：学生可见语言是否自然、明确，标题、问答、例题标签和术语是否稳健。
- `domain_accuracy`：本领域事实、定义、条件、推理、计算、图表语义和参考资料是否正确。
- `layout`：使用 Marp 源 lint、构建日志、PDF 页面几何、文字边界、字号和文本层检查成品；禁止截图和模型视觉。
- `pedagogy`：概念链、例题角色、先修激活、解释顺序、教材覆盖和难度坡度是否合理。
- `audience`：随机进入时能否理解当前对象、条件、单位和问题；是否符合目标听众的知识、动机和预期收获。

## finding

每条 finding 必须有稳定 ID、位置、问题、学习者影响、验收标准和验证方法。报告 prose 不能替代机器可读 finding。零 finding 仍须说明检查范围和证据。

## 边界

specialist reviewer 不改作者源；review coordinator 不弱化 finding；release coordinator 不发明新 finding。增量轮的新 ID 只能标为 regression。
