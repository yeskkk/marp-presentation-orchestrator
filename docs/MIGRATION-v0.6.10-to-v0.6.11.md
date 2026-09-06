# v0.6.10 → v0.6.11

数据库 schema 3 → 4 为短事务增量升级，增加 decks/releases，不修改原配置和内容。
旧确认缺少 workflow 时继续 authoring；新建任务默认 full。需要完整流程的旧任务应
导入新目录、补齐计划并由用户确认，不能运行中给固定配置追加授权。

全流程由 runner 接管，不再手建整稿或审核 job。原模型回执、容量和不确定状态规则
不变。检查/发布故障用 README 的显式恢复接口；不跳过 gates，不篡改 finding。
旧 skills/启动器尚未迁移；使用 README 的新 CLI。
