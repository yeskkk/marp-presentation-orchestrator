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

维护先 `storage inspect`，再 `storage prune --dry-run`。有未决请求、活动写者或未结束门禁就不应用。
只按程序生成的计划及保留策略清理；不直接删 accepted=0、NULL request_id 或全部历史。
确认需要的完整调试归档已经保留后，按原计划 apply；计划变了就重新预览。
compact 实际回收空闲空间，但需足够磁盘与维护安全点。详见 [维护手册](../../../docs/STORAGE-MAINTENANCE.md)。

复盘用只读 `report usage`，按课件、角色、操作分组。缓存是输入子集，推理是输出子集；
供应端 turn 时间、适配器调用时间、并行累计、墙钟覆盖分别看；缺失不是零。
存在可描述等待原因时用 wait-start / wait-end 明确记录，不靠时间空档猜原因。
先减少程序拒收、资源缺口、重复输入和工具往返；不自行降模型、降强度、跳阅读或删审核通道。
见 [计量与交接](../../../docs/COST-AND-SUPERVISION.md)、[升级与返修](../../../docs/UPGRADE-v0.9.md)。
