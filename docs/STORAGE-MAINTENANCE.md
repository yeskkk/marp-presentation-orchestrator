# 存储维护（v0.9.2）

先停止所有 adapter/runner，并解决状态未知和未接受的请求。不要按 bridge 的旧 accepted 位或 request_id 为空判断垃圾；只读占用查看不迁移数据库。

```sh
./start.sh --cli storage inspect linear-algebra-v7
./start.sh --cli storage migrate linear-algebra-v7 --by owner
./start.sh --cli storage prune linear-algebra-v7 --dry-run
./start.sh --cli storage prune linear-algebra-v7 --apply <预览中的plan_id> --by owner
./start.sh --cli storage compact linear-algebra-v7 --by owner
```

清理先迁移再预览。计划绑定数据库指纹；有新写入就要重做预览。`--policy` 可指定 storage-policy.template.json 格式的副本；默认成功记录保留 7 天、确认被同 job 后续成功尝试替代的失败保留 30 天。尚未解决的失败、未知执行及未经接受的请求不会因为过期而清掉。日期按 UTC 日界计算，保守多保留不足一天。

本版安全回收范围：重复恢复历史、过期流式正文、非最终答复的工具正文、逐字相同的门禁报告副本。保持 wire 的行号和终态/计量/最终答复，正文以原文摘要哈希、原字节量和保留理由替代。它不再是完整调试日志，但可完整重建既有索引投影。教材内容寻址缓存避免新快照重复；**不删除历史输入清单仍引用的旧文件，也不删除交付件或任务事实**。

`prune` 只释放 SQLite 内部页，`compact` 才尝试缩小文件。整理需足够磁盘空间，活动进程/未解决执行会阻止操作。每库事务独立；跨库中途失败会写 partial 审计，不声称全部回滚。可选 `--backup-dir <全新目录>` 使用 SQLite backup 生成操作前副本；这些备份由调用者控制保留上限，不自动生成不断膨胀的压缩归档。日志清理本身不默认建备份，使用 apply 前确认已有所需归档。报告的空间收益只指活动数据库，不扣除调用者保留的备份。

迁移从 schema 11 升为 12，保存当前触发命令、程序版本、起止时间和成功/失败；未知的历史执行人不补造。`storage migrate --by` 保存显式操作者标签，不能把它声称为外部身份认证。

新的 thread/resume 请求显式发送 excludeTurns=true，避免反复获取整段会话。部署版不支持时让错误明确返回，不在超时后盲目恢复或重新发起 turn；当前未知执行仍只能 reconcile。此项减少通信和落盘，不等于清空模型上下文。

协议核验来源：OpenAI Codex App Server 文档（2026-09-14 核验）；SQLite VACUUM 文档。
https://developers.openai.com/codex/app-server
https://www.sqlite.org/lang_vacuum.html
