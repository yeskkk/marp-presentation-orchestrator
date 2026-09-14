# v0.9 登记事项落实索引

原 BUGS.md、FEATURE-REQUESTS.md 保留为运行时登记原文，本文件给出累计源码的处理位置。
“保留回归”不表示重新创建已有功能；测试宿主替身不代替实际部署/模型/浏览器验收。

| 登记 | 当前处理 | 主要回归/实现位置 |
|---|---|---|
| BUG-20260913-01 | 保留已确认任务容量授权路径 | effective_policy_batches、job_runner |
| BUG-20260913-02 | 保留有效 TASK 首次全文/后续授权差异 | task_context、effective_policy_batches |
| BUG-20260913-03 | 保留历史桥接原响应对账，不伪造原接受 | host_receipt_recovery、codex_bridge |
| BUG-20260913-04 | 保留当前主题表格修复 | default_theme |
| BUG-20260913-05 | 保留增量索引；v0.9.2减少恢复历史并清理到期冗余正文 | codex_incremental、v092_storage |
| BUG-20260913-06 | 保留拒收上下文；程序重放与语义重做分离 | host_receipt_recovery、bounded_recovery |
| BUG-20260913-07 | 保留单作业授权重试上限 | bounded_recovery |
| BUG-20260913-08 | 保留有界旧图语法升级，不放宽内容合同 | source_contract、legacy_figure_upgrade（现有内容兼容，不是 legacy 模板专项） |
| BUG-20260913-09 | 保留单一 finding/确定性字段路由 | review_references、host_receipt_recovery |
| BUG-20260913-10 | v0.9.1统一有界引文匹配，不改数字/符号/否定 | quote_evidence、v091_exercises |
| BUG-20260913-11 | 保留输入预算授权与同 attempt 恢复 | effective_policy_batches、host_receipt_recovery |
| BUG-20260913-12 | 保留 finding_refs 合并；不逐字复制已有 finding | review_references、audience_reading |
| BUG-20260913-13 | 保留活动/空闲/授权总时长边界；异常需接管 | codex_incremental、v093_operations |
| BUG-20260913-14 | 保留机械待验重试，版本与真实门禁不得伪造 | revision_quality、delivery_bundle |
| BUG-20260914-01 | v0.9.2迁移审计、只读入口、不补造旧执行人 | store、v092_storage |
| BUG-20260914-02 | 保留 fresh/continue 来源边界 | context_resources |
| BUG-20260914-03 | v0.9.0吸收合理编拟生活算例并清除活动指南冲突 | learning-contract、v090_rules |
| BUG-20260914-04 | 保留正式修改后的暂停/恢复及未冻结稿编辑 | effective_policy_batches |
| BUG-20260914-05 | v0.9.3前台终态交接、持久 ack、未知请求恢复；未实现虚构宿主推送 | supervision、v093_operations；真实宿主接收由部署确认 |
| BUG-20260914-06 | 保留同一冻结稿唯一引文定位及原始证据 | review_references、v091_exercises |
| BUG-20260914-07 | v0.9.0重写失效接口测试；修两个 fake-server 子进程导入路径 | codex_bridge、codex_incremental；全 compact 回归 |
| BUG-20260914-08 | v0.9.1与数学定界/句末标点合并为一个保守格式层 | quote_evidence、v091_exercises |
| BUG-20260914-09 | v0.9.0/1区分 read/modify/execute，执行仍依已有授权 | learning-contract、resource-design、context_resources |
| BUG-20260914-10 | 保留显式教材清单；v0.9.1付费前预检、内容寻址缓存 | preflight、files、v091_exercises |
| BUG-20260914-11 | 保留可配置图形标签和确定性坐标 | computed_figures |
| FR-20260914-01 | v0.9.3菜单/参数/范围/取消/明确 argv；不默许提权 | permissions、v093_permissions、interactive_start；原生 Windows/真实权限待部署验收 |

新增：练习单页硬要求、全量覆盖索引及现有审核隔离检查（v0.9.0/1）；
安全保留/预览/应用/实际压缩与门禁单一报告（v0.9.2）；
供应端/适配器时间分离、可归因与未归因等待、程序用量报告（v0.9.3）。

未改 legacy 模板，不为它们安排专项测试。未改变用户已确认模型、low、容量16或固定主题边界。
新版源代码经规则/程序层验证；本次没有付费重做三个课件，不能提前宣称其实际返修稿通过教学验收。
