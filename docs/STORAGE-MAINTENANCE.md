# 当前版本检查点与存储维护（v0.9.6）

不断返修的任务以**当前正式发布版本及必要依赖**为基准，不再永久保存全部旧稿、逐次工作目录、通信全文和维护备份。当前版本未被成功交付的后继替换前，始终受保护。用户资料、未制作章节材料、配置、授权、用量、执行身份和必要处置账本不是垃圾。

## 首次检查与启用

```sh
bash start.sh --cli task open linear-algebra-v7
bash start.sh --cli storage inspect linear-algebra-v7
bash start.sh --cli storage checkpoint linear-algebra-v7 --dry-run
bash start.sh --cli storage checkpoint linear-algebra-v7 --apply PLAN_ID --by main
bash start.sh --cli storage policy linear-algebra-v7 --current-only --by main
```

将 `PLAN_ID` 替换为刚预览的真实 ID。启用策略之前不自动删除历史；`--current-only` 持久记录用户已确认的策略。此后在 adapter 关闭或重新打开任务的安全点，每个新发布基线至多自动收尾一次。活动进程、未决执行、尚未闭环返修或不完整交付会延期，不假装已经清理。`--manual-only` 关闭自动收尾，手动预览/应用仍可用。

## 回收内容与保留内容

程序通过发布关系识别当前叶子稿。`p03 -> p03` 这样的同 ID 保留映射不是拆分，不能误判为被替代父稿。真正被子稿取代的父稿、旧版 artifact/PDF、闭环 work 与旧门禁目录可回收。已修改或无法验证的公共目录、无法识别的备份文件保留并报告，不递归盲删用户目录。旧教材工作快照可删；用户来源与未来课件可能共用的内容缓存保持。

只有请求全部取得正面的终态/业务闭环证据，通信全文才转成最小投影：保留路由、线程、turn、实际运行参数、计量、终态和最终回执事实。投影**从原 wire 日志重建**，不是相信可丢弃 sidecar。投影种子与删除旧 wire 行在同一事务提交；保留最高真实行号，后续行号不复用。有解析问题的原始行不删除。旧记录引用可用：

```sh
bash start.sh --cli storage evidence linear-algebra-v7 --wire-id 12345
```

返回明确区分原文仍在和正文已清理；不伪造已删除通信全文。sidecar 丢失或任务路径改变后，从带校验的种子和新 wire 行重新建索引。历史请求不得重发，已闭环请求的 replay 只返回其处置事实，不重新验收已删除旧稿。

旧任务数据库自动迁移至 schema 13；旧版本程序不得继续写入。事务式迁移有审计，不为每次 metadata 升级自动制造一份永久全库备份。需要保留的外部备份仍由用户自行决定，不能让清理命令每轮增加一份无限期备份。

## 中断恢复与真实空间核算

计划绑定数据库与文件清单。先记 checkpoint，再把计划对象移入同文件系统临时区；登记 tombstone 后删除临时区，随后精简已闭环报告、压缩数据库。保留当前源文件及全部资产的校验值，前后复核计量不变。

```sh
bash start.sh --cli storage checkpoint linear-algebra-v7 --status
bash start.sh --cli storage checkpoint linear-algebra-v7 --resume CHECKPOINT_ID --by main
```

未完成检查点会阻止生产接续，先恢复原有限计划。多次恢复不重新发模型调用。阶段间是可恢复的提交，不谎称文件系统与两个数据库存在一个总事务。报告使用**整个任务目录**的前后字节量，包含备份与暂存，不只报活动数据库的减少。VACUUM 需要额外空间；旧备份和暂存已先回收，不复制整库来制造净增长。

## 归档缺 PDF 的验证边界

默认必须存在一致的当前 canonical/checked PDF 对。仅针对主动去掉 PDF 的审计副本，可以显式使用 `--allow-missing-pdf` 预览及应用；这个开关不产生 PDF、不更改发布记录、不证明交付就绪，自动维护永远不使用它。真实生产中先恢复/重新渲染当前源稿，不以该开关绕过验收。

## 原有低层维护接口

`storage prune` 的按保留天数精简和 `storage compact` 仍保留，适用于不选择当前版本检查点的项目；它们不替代整目录生命周期管理。`storage inspect` 始终只读，不自动迁移。禁止按旧 `accepted=0`、空 request_id 或行龄直接判定垃圾。

缩库只减少磁盘和本地处理开销，不等于清空供应端会话，也不能按删除的字节数换算成节省 token。
