# 模板入口：只生成三份用户配置

| 模板 | 生成文件 | 内容所有者 | 不应放什么 |
|---|---|---|---|
| `compact/TASK.template.md` | `TASK.md` | main 整理、用户确认 | runner 操作手册、逐页自检回执 |
| `compact/task.template.yaml` | `task.yaml` | 用户确认的计划与执行上限 | 模型推理强度、临时 gate 豁免 |
| `compact/TASK-RUNTIME-PROFILE.template.yaml` | 同名配置去除 `.template` | 用户在确认前自行选择 | agent 自动升降级策略 |

`Service.create()` 只复制这三份文件；本 README 不复制到任务。
确认保存完整配置快照。修改模板只影响之后新建的任务，不重写旧任务或给它新增授权。
课次 `brief` 描述教学工作，不是可直接粘贴到学生页的文案。

## 不同结构不要混用

模型结果的权威定义在 `src/mpres/control/schemas/` 的四份 JSON Schema，不在模板目录。
校验规则还包含服务层的实际 ID、证据、反馈和返修范围检查；JSON Schema 通过不等于交付。
全局布局在 `src/mpres/control/theme.css`，不是一个让作者填写的 `style: |` 字段。

旧模板已移至 [compat/legacy](../compat/legacy/README.md)。它们不再是新任务的输入，
不能从旧模板挑选 SELF-CHECK、assignment 或 stage 表单拼成“更完整”的新流程。
完整步骤见 [README](../README.md)，精确命令见 [操作手册](../docs/OPERATIONS.md)。

结果字段与条件义务见 [SEMANTIC-RESULTS](../docs/SEMANTIC-RESULTS.md)，维护案例仅供源码工作使用，见 [维护说明](../docs/development/SEMANTIC-MAINTENANCE.md)，不加载到运行任务。
