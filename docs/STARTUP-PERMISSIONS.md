# 启动权限：先明确选择，再传入真实参数

`start.sh`、`start-safe.sh` 和 PowerShell 启动器调用同一个 Python 入口。
本地先选择任务及本次修改方向，再选权限；空输入不放行，取消不启动模型。
选择只影响新启动的交互主会话，不修改 TASK、模型强度、现有 worker 或生产/返修授权。

| 参数值 | 传入的 sandbox | shell 网络请求 |
|---|---|---|
| read-only | read-only | 不额外开放；不能冒充整个客户端离线 |
| workspace | workspace-write | 显式 false |
| workspace-network | workspace-write | 显式 true |
| full | danger-full-access | 不由本 sandbox 限制；需 FULL 二次确认或额外开关 |

工作区模式同时清空额外 saved writable_roots，保留 Codex 标准临时目录语义；不是写入任意磁盘。
命令审批为 `--approval on-request` 或 `never`，默认前者。never 意味不请求审批升级，不等于无条件允许所有操作。
不使用 bypass/yolo/full-auto；尾随 `--` 不得覆盖所选 sandbox、approval、config、profile 或额外写目录。
启动前展示实际构造的参数和作用范围，并探测所装 CLI 的 --help；缺必须参数则明确停止，没有静默降级。

```bash
# 已在终端中：直接明确两种选择，不再重复问菜单
bash start.sh --task linear-algebra-v7 --intent keep --permissions workspace-network

# 无终端也能预览，不启动模型，不构造无人值守执行
bash start.sh --task linear-algebra-v7 --intent keep --permissions workspace --print-command

# 仅本地检查
bash start.sh --check --permissions workspace
```

`--intent keep` 不批准任何新交付/返修；`--intent edit` 不派发生产。
完整访问须同时 `--permissions full --allow-full-access`；普通工作不需要该选项。
PowerShell 对应 `./start.ps1 --task ... --intent ... --permissions ...`；同一参数解析实现。
非交互参数用于预选/预览，并没有把交互 Codex 偷换成 exec 模式。

显示的是启动器明确请求并传入的设置，不伪称已突破宿主、组织策略、OS 或外层沙箱。
`effective_host_policy_verified=false` 直到会话实际检查；在 Codex 查看 `/status` 后仍要用真实 toolchain doctor
验证浏览器/socket 能力。已有权限 profile 与旧 sandbox 键不兼容时让客户端明确报错，不擅自清空组织配置。
Linux PTY/参数/取消/退出码测试不等于原生 Windows 权限或浏览器验收。

参数依据（2026-09-14 核对官方文档；本地 --help 仍是部署入口检查）：
- https://developers.openai.com/codex/cli/reference
- https://developers.openai.com/codex/config-reference
