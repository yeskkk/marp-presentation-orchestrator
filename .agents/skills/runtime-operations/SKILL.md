---
name: runtime-operations
description: Main-only operational recovery, storage maintenance and usage evidence. Load on an actual operational need, never into every content worker packet.
---

# 主代理运行维护

这是 main 的按需操作指南，不新增 worker、reviewer 或常驻观察 agent。

异常终态先看 `supervision pending`、确切 request 和原响应。`runner replay` 仅重新验证已留存的原结果；
执行未知先用 `bridge reconcile` 对账，不能把重试、ack、数据库 accepted 旧位当作执行完成。
前台 runner/bridge 返回 needs_main_attention 与 handoff_id；调用宿主应处理非零退出并读取该返回。
程序没有宣称支持原生宿主推送；SIGKILL 不能被进程自己捕获，重开后靠未决请求与持久证据接管。
处理完用 `supervision ack` 写明操作者和措施；这不更改 attempt、授权或计量。

维护先 `storage inspect`。连续返修任务优先当前版本检查点：`storage checkpoint --dry-run` 后应用确切计划；用户确认 `storage policy --current-only` 后，在 adapter 关闭或重开任务的安全点自动收尾。当前正式稿及依赖、用户资料、未决工作和计量保留，旧完整内容不永久累积。不要按旧 accepted 位、NULL request_id 或年龄直接删。

检查点中断先 `storage checkpoint --status` 再 `--resume`，不要启动生产覆盖暂存。历史回执用 `storage evidence --wire-id` 区分原文/已清理事实；已闭环旧请求不重新发送。维护报告看包括备份、暂存的**全目录净变化**。不要求为了清理再建一份永久全量备份。详见 [维护手册](../../../docs/STORAGE-MAINTENANCE.md)。

复盘用只读 `report usage`，按课件、角色、操作分组。缓存是输入子集，推理是输出子集；
供应端 turn 时间、适配器调用时间、并行累计、墙钟覆盖分别看；缺失不是零。
存在可描述等待原因时用 wait-start / wait-end 明确记录，不靠时间空档猜原因。
先减少程序拒收、资源缺口、重复输入和工具往返；不自行降模型、降强度、跳阅读或删审核通道。
见 [计量与交接](../../../docs/COST-AND-SUPERVISION.md)、[升级与返修](../../../docs/UPGRADE-v0.9.md)。
