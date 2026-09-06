# Marp Presentation Orchestrator

这个项目把教材、教学意图和少量人工决策转化为 Marp 课件。目标不是让 main
agent 学会操作大量流程文档，而是让 Python 管理运行，AI 只负责教学语义。

**当前发布阶段：v0.6.9。** 新任务已使用关系型 SQLite；作业运行器可以按已批准
计划机械领取、启动、接收结果，预留后续审核／编辑容量，并拒绝不明确的外部状态。
本版接通的是「语义作业执行循环」，**尚未接通整稿 gate → 冻结 → 审核 → 修订 →
PDF 发布的全自动编排**。源码提交成功不等于课件验收或发布成功。该边界是有意保留
的，避免将尚未迁移的完整质量门禁绕过。旧生产接口仍显式使用 `legacy`，不能与
新任务的状态混写。

## 1. 谁负责什么

用户与 main agent 确定受众、先修知识、课次安排、教学范围和交付方式。用户在
任务开始前编辑模型配置。确认后，程序使用这份固定配置，不根据难度、置信度、
预算或重试次数改变模型和推理强度。

AI 的工作是规划、课次写作、整稿编辑、五通道语义审核和问题诊断。作业身份、
会话登记、重复提交、检查记录、耗时、token 和发布状态属于程序职责，不要求 AI
再写一套 request/brief/decision 文件。没有模型型 review/release coordinator。

## 2. 整体流程与本版已经接通的步骤

| 步骤 | 如何运作 | v0.6.9 状态 |
|---|---|---|
| 创建任务 | 生成三份用户入口和一份 SQLite 数据库 | 已实现 |
| 编写教学计划 | 在 task.yaml 中列出 deck、课次 brief 和获准资料；AI 可帮助形成语义内容 | 已实现校验 |
| 展示与确认 | 同时展示 TASK、非模型设置、runtime；用户确认后在数据库保存快照 | 已实现 |
| 实例化作业 | 从已批准课次生成数据库 job ID；重复运行不重复创建 | 已实现 |
| 宿主与容量 | 读取实际 inventory/limit/usage 能力，计算覆盖五 reviewer 和编辑者的持久池；并发只是上限 | 已实现 |
| 会话绑定与执行 | runner 生成精确请求，程序或宿主转发；短事务检查身份、固定 runtime 和独立性 | 已实现 |
| 内容提交 | 执行回执 + 语义结果 + 实际源码；保存只读修订，重复提交不重复推进 | 已实现 |
| 源码与布局验收 | 复用原有 Marp、数学、HTML DOM、PDF 机械检查 | 原有能力保留；新 runner 下一阶段接入 |
| 整稿编辑与冻结 | 程序收集单元，必要时启动短时编辑，不设常驻协调员 | 下一阶段 |
| 五通道完整审核 | 五个不同、独立的 reviewer 读取同一个冻结版本 | 数据约束已实现；自动调度下一阶段 |
| 修订与发布 | findings 路由 → 编辑 → 完整门禁 → PDF 交付 | 下一阶段 |

在 command 适配器模式下，本版已经无需 main 逐个选择、拼装和批准作业控制命令。
bridge 模式仍需要宿主转发精确请求和回执，但不需要 main 重新计算调度决策。
整稿生命周期自动推进继续留给下一独立阶段；不能提前宣布整套重构已经完成。

## 3. 目录和代码结构

```text
src/mpres/
  cli.py                    默认新入口；legacy 时才加载原命令行
  control/
    schema.sql              关系模型、外键、唯一约束、不可变配置
    store.py                SQLite 短事务、查询和一致性数据库备份
    service.py              配置确认、作业、绑定、提交、usage 和状态服务
    files.py                路径检查、只读修订、可写工作副本
    migration.py            旧任务只读导入到新目录
    cli.py                  新任务的薄命令行适配
    runner.py               宿主能力、持久池准入、作业领取、输入包、JSON 适配器
  runtime_profile.py        复用已验证的静态模型配置解析
  marp_source.py            Marp 解析、源码 lint（保留）
  html_layout.py            临时 HTML + DOM 几何检查（保留）
  math_inspection.py        数学源码与 renderer 检查（保留）
  pdf_inspection.py         PDF 结构、文本和边界检查（保留）
  assets.py, references.py  资产与参考资料工具（保留）
  legacy_cli.py             原 v0.6.7 命令行；仅用于旧式任务
  ...                       原生产模块，等待逐项迁移和删除

templates/compact/          新任务仅三份用户入口模板
templates/{其他目录}/       旧任务兼容模板，不复制到新任务
.agents/skills/             旧语义与管理 skills 暂存；不作为新控制面的运行依赖
schemas/                    后续集中存放少量 AI 语义输出 schema
scripts/                    静态验证与启动辅助，不存放 AI 调度决策
tests/compact/              新控制面回归；旧 tests 继续保留
```

新任务的实际布局：

```text
tasks/<slug>/
  TASK.md
  task.yaml
  TASK-RUNTIME-PROFILE.yaml
  sources/                   获准参考资料
  content/                   作者可编辑的实际内容
  deliverables/              正式交付（本版不自动发布）
  .mpres/
    task.sqlite3             唯一运行事实源
    artifacts/<revision>/    已提交／导入的只读内容修订
    work/<attempt>/
      input/                 本次需要的参考文本快照
      output/                本次实际内容输出，不是过程报告
```

数据库保存 config、plan item、job、dependency、session、attempt、participation、
artifact、check、finding、decision、event 和 usage 的关系。不会再把两份整块 JSON
作为全部状态，也不再生成可写 JSON/YAML 登记投影。大型资产仍在文件系统。

## 4. 安装和使用

Python 需要 3.11 或以上。完整 Marp 生产还需要项目 `package.json` 固定的 Marp CLI、
Node.js 和可用浏览器。不要升级 Marp 版本来掩盖任务故障。

```bash
python -m venv .venv
# Linux/macOS；Windows 使用 .venv\Scripts\activate
. .venv/bin/activate
python -m pip install -e '.[dev]'
npm install
mpres --help
```

仅检查 Python 源码接口也可使用 `PYTHONPATH=src python -m mpres ...`；这不代表外部
渲染器已经安装或通过验收。

### 创建并确认

```bash
mpres --root . task init economics --title "面向经济学的线性代数"
```

编辑三份入口。最小的 `task.yaml` 课次部分示例：

```yaml
presentations:
  - id: p01
    title: 向量与经济数量
    units:
      - id: l01
        title: 坐标和单位
        brief: 从商品数量进入坐标表达，说明单位，安排一个例题和一个诊断问题。
        sources: [sources/chapter-1.txt]
```

其余配置保留模板字段。`provider.handle_limit: null` 表示尚未确认宿主容量；
这不是无限容量，后续 runner 必须在启动前拒绝未知能力。

```bash
mpres --root . task present economics
# 用户已看到准确内容并明确确认后才执行：
mpres --root . task confirm economics --by "user"
mpres --root . task materialize economics
mpres --root . task jobs economics
```

默认 runtime 延续原项目：planner = `gpt-5.6-sol/high`，author =
`gpt-5.6-sol/medium`，reviewer = `gpt-5.6-sol/low`。这是旧项目对 sol 的具体标识，
不代表程序替用户判断服务当前有哪些模型；用户须在确认前改为宿主实际支持的标识。

确认只对已展示的精确配置生效。确认后编辑文件会阻止后续写入，不会自动刷新运行
配置。只有顶层 TASK.md 使用既有确认摘要；源码、模板、提交内容不生成额外 hash。

### 作业执行接口（本阶段底层接口）

`job_id` 和 `attempt_id` 必须来自命令结果，不能把课次名称或任意 assignment 字符串
拿来当 ID。先取得实际宿主创建会话的证据，再登记：

```bash
mpres --root . session register economics --handle HOST_HANDLE \
  --family author --model gpt-5.6-sol --effort medium --receipt HOST_CREATION_RECEIPT
mpres --root . job bind economics JOB_ID --handle HOST_HANDLE
mpres --root . job started economics ATTEMPT_ID --receipt HOST_EXECUTION_RECEIPT
mpres --root . job submit economics ATTEMPT_ID \
  --result /path/to/result.json --source tasks/economics/content/l01
```

`result.json` 至少包含有意义的 `summary`。写作结果还必须提交实际 `presentation.md`；
审核结果包含 `findings` 数组，每条需要 message 和 slide_ids。控制字段由程序记录。
用户可在收到提交后删除传输用的结果文件，数据库才是结果真源。新 runner 的严格语义
schema 和自动门禁会在下一阶段接通；底层提交成功不等于 source gate 通过。

## 5. 一致性、独立性与恢复边界

每个连接明确启用外键；领取作业和登记结果分别在短的 `BEGIN IMMEDIATE` 事务里完成。
执行模型、渲染和准备文件修订在事务外进行。不会假称 SQLite 能回滚模型调用。

同一会话只能有一个未结束 attempt。同轮五个审核通道不能复用同一个会话；参与过
本稿写作的会话不能审核本稿。runtime 必须与已确认配置匹配。

启动结果丢失时使用 `job uncertain` 保留容量占用；不会自动重新启动、假装关闭或伪造
handoff。本版支持同一个创建／执行请求的回执对账；未明确的创建或执行会让 runner 停止
继续发出请求。它不会通过修改数据库假装外部工作已停止。
目录只读是防误写保护，不是对同一系统用户提供安全沙箱。

## 6. 状态、耗时和 token 查询

```bash
mpres --root . task status economics
mpres --root . job show economics JOB_ID
mpres --root . task metrics economics
```

每个 usage call 直接关联 attempt，从而可以关联 job、课次、角色和配置。缺失计数保留
null，重复 call ID 不重复计费，不同值不能静默覆盖。`attempt_coverage` 和
`record_field_coverage` 分开；没有 usage 时显示未知，不显示零成本。金额没有价格
依据时不推断。command／bridge 协议现已接收逐调用 token 回执，并按 attempt 关联。
启动前必须有 `usage_reporting: true` 的真实能力声明；承诺回传却缺少回执时不接受
该执行结果。某字段确实不可获得时仍允许明确的 null，不转换成零。底层 `job usage`
也保留为回执导入接口。它不意味着模型会话在任务创建以前的消耗已全部被采集。

`task backup-db` 使用 SQLite 备份 API，但只导出数据库，不包含被引用的内容文件；
命令和结果都明确这一点。完整可搬运任务导出留待后续集成，不应只压缩一个活库文件。

## 7. 旧任务如何迁移

```bash
mpres --root . task import-legacy /path/to/old-task --slug economics-imported
```

导入器优先只读访问旧 SQLite；没有数据库时才读取 task.json，并标记其来源未核验。
旧目录不写入。已有源码复制为 `origin=import, verified=0` 的修订；不相信旧
handoff_ready，不导入会话为可用句柄，也不伪造审核通过。没有足够语义依据的 brief
留空，必须由用户或 planner 补齐并重新确认。模型配置可以带入草案，但不会自动批准。

还没迁移的旧任务可以明确使用 `mpres legacy ...`。新任务调用旧服务会在任务路径
入口失败，不能在旁边再建立一个 mutable-state.sqlite3。兼容模块不是永久双轨目标，
后续每迁移一类能力就停止旧路径的默认使用并删除无用材料。

## 8. 运行器怎样接管

运行器不会创建一个新的模型协调员。`Runner.tick()` 在数据库中领取工作，编译该课
brief 和必要的资料路径，返回精确的 `create` 或 `run` 请求；重复 tick 不会再次
发出已领取请求。`Runner.run()` 则通过用户确认的外部适配器执行这些请求并接收结果。

### 能力与容量

容量不能只相信项目配置。宿主必须报告实际 handle 列表、上限、close/reset 和 token
回传能力。报告有效期为 120 秒；过期或已登记会话从 inventory 中消失，会阻止继续
准入，而不是推测容量已释放。

持久池预算包含全部计划中不同 runtime 的作者池、每个 reviewer 通道的槽位、整稿
编辑槽位，以及外部已有句柄和恢复余量。所有 reviewer 通道分占不同槽位。空间不足
时，只把实际作者并发压到用户确认上限以下，不改模型或推理强度；最低配置仍放不下
就不启动。任务还没有审核作业时，审核槽位只是预算预留，不提前创建五个空闲模型。

本版保守地按“不释放、不重置”的池计算。即使宿主报告支持 close/reset，本版也不会
靠未执行的 close 假装释放容量；句柄复用也不会被宣传成“上下文已清空”。跨作业历史
消耗需要依靠 provider 实际回传的 token 判断，不能仅凭 packet 大小推断。

### command 模式：程序直接执行

用户在确认前填写 `task.yaml`：

```yaml
provider:
  mode: command
  command: [python, /absolute/path/to/your_provider_adapter.py]
  handle_limit: 16
  external_handles: 1
  recovery_reserve: 2
  supports_close: false
  supports_reset: false
context_budget_bytes: 262144
provider_timeout_seconds: 1200
```

adapter 是宿主 API 的薄封装：从 stdin 读取一个 JSON 请求，在 stdout 返回一个
JSON 响应，诊断文字写 stderr。项目使用 argv 调用，`shell=False`；不执行模型返回
的任意命令。**仓库不内置某个供应商的账户、API key 或未经验证的 Codex 线程 API。**

```bash
mpres --root . runner run economics --cycles 100 --interval 1
```

这是前台机械进程，不需要 main 定时巡检。它执行有界循环，在阻塞、待回执或无可运行
作业时返回。后续可以由操作系统服务管理器托管，不需要另开模型监督线程。

### bridge 模式：宿主只能从模型工具侧启动线程

```bash
mpres --root . runner host economics --report host-report.json
mpres --root . runner capacity economics
mpres --root . runner tick economics
mpres --root . runner outstanding economics
```

`host-report.json` 是工具实际返回的 inventory 转换结果，不能凭空编写。也可以
使用 `--report -` 从 stdin 读入，不必保留过程文件。

首次 tick 按需要返回创建请求，宿主以给定 runtime 创建会话，再回传实际 handle：

```bash
mpres --root . runner attach economics --slot SLOT_ID --handle REAL_HANDLE \
  --model gpt-5.6-sol --effort medium --receipt REAL_CREATION_RECEIPT
```

刷新 host inventory 后，下次 tick 返回 `run` 请求。宿主只转发请求中的工作，不另写
assignment 文档。通过 `runner accept --request REQUEST.json --response RESPONSE.json`
回传结果；两个 JSON 是传输介质，不是 task 下必须生成的事实文件。不能读取、生成
或者伪造不存在的 provider 回执。

bridge 仍有宿主工具转发的模型回合，不能算“零模型调度成本”。输入包声明读写边界，
但本项目不能替宿主实现工具沙箱。adapter 必须落实这些访问限制；当前协议明确输出
`sandbox_enforced_by_project: false`，不会把 prompt 说成操作系统隔离。

### 最小 adapter 协议

`capabilities` 响应：

```json
{
  "handle_limit": 16,
  "handles": ["actual-main-handle"],
  "supports_close": false,
  "supports_reset": false,
  "usage_reporting": true,
  "receipt": "actual-inventory-receipt"
}
```

`create` 请求含 `request_id`、`slot_id` 和固定 `runtime`；响应含实际
`handle`、`model`、`reasoning_effort`、`receipt`。重复回传同一创建结果无副作用。
创建是否成功无法确认时槽位保留为 uncertain，不再盲发第二次。

`run` 请求含 `request_id`（同 attempt）、`session_id`、固定 `runtime` 和
`packet`。响应形状：

```json
{
  "receipt": "actual-execution-receipt",
  "runtime": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
  "source_dir": "output",
  "result": {"summary": "解释了坐标的单位，并写出例题与诊断问题。"},
  "usage": [{"call_id": "actual-call-id", "counters": {
    "input_tokens": 100, "cached_input_tokens": 80,
    "output_tokens": 5, "reasoning_tokens": 0, "total_tokens": 105
  }}]
}
```

数字只是协议示例，不是本项目的实际运行消耗。响应中的实际 runtime 不符时拒绝
接受，不能默许 provider fallback。source_dir 必须位于本次 output 子树。
AI 只提供语义结果和内容，时间戳、ID、回执、计数由宿主／控制程序提供。

## 9. 测试、实现边界和继续方向

```bash
PYTHONPATH=src python -m pytest tests/compact
python scripts/validate_project.py
```

新测试覆盖事务身份、固定 runtime、实际 inventory 准入、容量压缩、不同 reviewer
槽位、重复 tick、并发 runner、未知创建、执行回执恢复、上下文上限、输出路径、token
缺失及 JSON subprocess 适配器。`tests/compact/fake_provider.py` 是明确的确定性测试
替身，**不是真实模型服务，也不能用于质量验证**。旧测试仍按模块隔离执行，没有删掉
失败用例来制造通过结果。

v0.6.8 数据库首次由本版访问时，在一个事务中升级到 schema 2；已确认配置和源码
修订不改变。版本号属于源码版本，schema 版本单独维护。

这次连续交付两个阶段：v0.6.8（关系型运行事实）和 v0.6.9（机械作业执行循环）。
下面的工作尚未宣布完成：整稿质量门禁的数据库化接入、自动冻结／五通道审核／修订／
发布链、语义 schema 完整收敛、约六个语义 skills、其余旧管理模板与兼容模块的删除。
它们会继续按可验收的独立阶段推进，不用未验证的中间结果冒充 v0.7.0。

### 本次更新摘要

v0.6.9 增加短事务 runner、实际宿主回执、持久角色池容量准入、有界输入包、固定 runtime
执行核对和逐调用 usage 回传。没有把源稿提交误报为完整课件交付。
