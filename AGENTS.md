# 工作入口

先查询实际任务，不从聊天历史推断运行状态。整体结构见 README；具体流程见 docs/WORKFLOWS.md。

## 首次建立任务上下文

先理解用户当前是新建、修改还是继续任务，不能启动后默认继续生产。
任务及本次方向确定后，main、delegated planner 和所有 worker 在实质规划／写作／审核前，
完整读一次该任务 TASK.md。新建任务先形成任务草案；修改任务先识别用户修改意图，
再以原文和已提出的改动开展工作。不能仅凭三份文件存在就启动生产。
同一会话已经读过则复用，只接收后续授权变更，不因新 job、纠错或分段试读重读全文。
runner 的 task_context.action 明确 read_full／reuse／apply_delta；手动 Codex 遵守相同顺序。
历史已派发请求不追溯伪造阅读，新的会话各自建立一次上下文。

## 选择路径

新任务：规划并展示三份配置，等待用户确认。已有任务：查询数据库并继续 runner，不重新初始化。
已发布返修：先只读展开，展示精确方案与目标；用户确认后才进入选定的 review-first/edit-first。
只有显式 legacy 命令读取 compat/legacy；不得把兼容模板混入 SQLite 新任务。

## 职责

main 处理需求、教学冲突与真实授权，不健康轮询、不手工填状态、不选 worker 的模型。
runner 决定可执行作业与机械恢复；宿主执行精确请求并提供真实 receipt/runtime/usage。
worker 使用包内自己的指南和结果 schema，不扫描全部 skills、模板或任务目录。
十个 skills 只承担语义工作；数据库、assignment、容量、gate、发布都不由模型声明成立。

## 全局边界

用户在任务确认前自行选择模型和强度；运行中不升降级或隐藏 fallback。
布局由固定主题提供；禁止作者 CSS、正文 HTML、inline SVG、临时图片尺寸和缩字绕过。
不截图、OCR、模型视觉查 PDF。原生渲染检查由项目程序执行。
历史反馈必须在 brief 中回顾，但 readback/检查记录不进入学生页。
数学严谨与证明密度分开；使用学习损失删除反事实，不为先修/核心/时长/引用清单自动辩护。
作者依本轮 findings 自修和复算；不增加 reviewer 验修轮次。

## 继续与交付

./start.sh 启动交互 Codex，--cli 或 mpres 执行控制命令；手动开启 Codex 走同一入口。
未知外部执行先对账，不盲重发；没有实际 close 证据不释放容量。不得伪造用户同意。
交付仅引用 delivery_package.state=ready 的 entries[].pdf 和 .markdown；目录不是 ZIP。
README 的实现边界必须如实保留，测试替身不冒充真实教学或原生浏览器验收。

五个审核 skill 对等独立，但 .codex/agents 仍用 specialist-reviewer 按指定通道选取。
校准示例和源码维护资料不属于运行任务的必读输入；不要扫描 tests/fixtures 作为工作指南。
