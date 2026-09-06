# 控制面设计边界

SQLite 约束事实关系，短事务领取和登记；模型、浏览器、文件暂存都在事务外。
源码快照/gate/五 reviewer/finding/release 是不同事实，不能用其中一个代替另一个。
作业、模板和 CLI 不能创造真实 provider 回执。发布 prepared 与独占文件创建共同支持
崩溃后对账；外部模型调用的不确定性不自动重试。

六个 active skills 只处理语义，四个 JSON schema 只约束语义结果。大 PDF/图像留在
文件系统，报告/计时/token 留在库中。旧模块暂为兼容，默认入口无二次可写状态。
