# v0.6.11 → v0.6.12

SQLite 仍为 schema 4；固定 runtime 不变。安装新增 jsonschema 依赖后继续读取原任务。
语义结果现在由四个严格 schema 校验，未知流程字段不再接受；作者结果仍以 summary
为最小输出，finding 身份和修订覆盖继续由关系服务验证。

26 个旧 skills 已删除，六个语义 skills 替代。start 脚本现在是 CLI 启动器，不启动
Codex 或常驻日志器、不自动安装。不再存在 author-coordinator 角色配置。可选 delegated
planner 只做短时语义规划，不调度。旧 task 模板/Python 兼容接口保留但不进入新任务。
