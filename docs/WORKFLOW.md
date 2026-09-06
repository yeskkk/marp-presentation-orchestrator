# 工作流入口

整体流程、步骤解释和代码结构以根目录 README.md 为准，不再双份维护长流程说明。

固定链：确认 → 单元写作/源码 gate → 组装 → 整稿编辑 → full gate → 五通道独立审核 →
finding 修订/full gate → 独占发布。运行事实在 task.sqlite3，AI 只提交实际内容和语义 JSON。
正常执行不需要 main 选择下一条命令。三份任务入口确认后不可动态改变 runtime。

旧流程说明已明确放入 docs/legacy，仅供理解未迁移旧任务；不要注入 compact 作业。
