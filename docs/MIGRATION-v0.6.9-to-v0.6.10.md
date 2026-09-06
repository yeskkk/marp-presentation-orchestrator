# v0.6.9 → v0.6.10

继续使用原 task.sqlite3；首次打开自动升级 schema 2 → 3，新增 gate_runs。不会修改
确认快照、会话和已提交内容。缺少 quality 配置的旧快照使用固定兼容默认 auto/1800。
新提交由 runner 在下一次 tick 做 source gate。失败不改写已接受内容；修正后必须新修订。
full gate 为原生工具调用，不接受作者提交的“通过”标志。未配置渲染环境时明确失败。

旧脚本和 skills 尚未清理；compact 任务使用 README 中的新 CLI。没有新增 process YAML。
