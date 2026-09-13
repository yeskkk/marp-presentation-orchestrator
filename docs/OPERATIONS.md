# 操作手册：只执行所需分支

## 1. 初始化与确认

```bash
mpres --root . task init economics --title "面向经济学的线性代数"
mpres --root . task present economics
# 向用户展示三份配置和教学冲突；以下命令只能在收到真实确认后调用。
mpres --root . task confirm economics --by user
mpres --root . task materialize economics
mpres --root . runner capacity economics
mpres --root . runner run economics --cycles 100 --interval 1
```

编辑模板的说明见 templates/README.md。present/confirm 不是模型可以自行批准的形式手续。
`--by` 只记录归属，不认证用户身份；宿主必须获取真实回复。

## 2. 状态与低介入执行

```bash
mpres --root . task status economics
mpres --root . task jobs economics
mpres --root . job show economics JOB_ID
mpres --root . runner outstanding economics
mpres --root . task metrics economics
```

command 模式 runner 在前台机械循环；Codex 可用 bridge run 直接执行精确请求，其它 bridge 由宿主转发，不是 main 重新规划。
正常无请求或已知阻断后 run 会返回，不承诺在后台继续。不要安排模型健康轮询。
metrics 的已知值和覆盖范围分开，缺值不是零，turn/usage行不当然等于底层模型调用次数。

## 3. 返修与暂停

```bash
mpres --root . repair open economics --presentation p01 --presentation p03 --mode review-first \
  --allow-slide-changes --report "按学生学习价值删除无用制作自述，保留必要条件。" --by user
mpres --root . runner run economics
mpres --root . repair present economics CASE_ID
# 修改方案时提交完整 expansion，重新展示新版本；不要执行两条互斥分支。
mpres --root . repair amend economics CASE_ID --proposal proposal.json --by user
# 取得对当前展示版本的真实确认后：
mpres --root . repair confirm economics CASE_ID --version 2 --by user
mpres --root . runner run economics
mpres --root . repair status economics
```

CASE_ID/version 取实际输出；proposal.json 是命令输入，不需要成为第二套长期运行记录。
`--proposal -` 支持 stdin。未确认且无未对账的在途工作可 cancel；用户未选目标不做顺手改稿。

```bash
mpres --root . repair cancel economics CASE_ID --by user --note "用户不采用本方案"
# pilot/each 原定暂停只有用户允许才继续：
mpres --root . workflow continue economics --by user --note "按既定计划继续"
```

## 4. 检查与可证明的恢复

```bash
mpres source check path/to/output
mpres figure check path/to/output
mpres --root . artifact inspect economics REVISION_ID --level source
mpres --root . artifact inspect economics REVISION_ID --level full
mpres --root . artifact gates economics REVISION_ID
mpres --root . workflow retry-checks economics --presentation p01 --note "渲染环境已修复"
```

仍 running 的 gate 不能重领；确认原进程已停后才 interrupt-gate。发布/组装同理：

```bash
mpres --root . artifact interrupt-gate economics GATE_ID --reason "已核实原检查进程停止"
mpres --root . artifact inspect economics REVISION_ID --level full --retry
mpres --root . workflow retry-publish economics --presentation p01 --note "已核实原发布进程停止"
mpres --root . workflow recover-assembly economics --job-id JOB_ID --note "已核实原组装进程停止"
```

这些命令不改 runtime、不解决语义争议。不要凭 error 字符串给自己伪造恢复授权。
`max_attempts` 是内容执行总数；两类 recovery 是有限只读工具预算，省略默认2，0关闭自动重试。

## 5. 反馈、交付与备份

```bash
mpres --root . feedback list economics --history
mpres --root . feedback record economics --rule feedback.json --by user
mpres --root . feedback inherit next-course --from-task tasks/economics --by user
mpres --root . workflow materialize economics
mpres --root . repair materialize economics CASE_ID
mpres --root . task backup-db economics /safe/path/task.sqlite3
mpres --root . task import-legacy /old/task/path --slug economics-imported
```

feedback 的规范输入字段是 id/report/expectation/possible_forms/acceptance/presentations/enabled。
来源与用户原话真实记录；跨任务继承的 presentation scope 必须适用于目标计划。
materialize 只配对已发布准确修订，不调用模型/重新渲染，不生成 ZIP；ready 才发 PDF/MD 路径。
DB backup 不包括资产和 PDF，不能宣称已经备份整个任务。

## 6. 安装和真实环境边界

```bash
python scripts/bootstrap.py --with-figures
./start.sh --check
./start.sh --cli toolchain doctor
python scripts/verify_theme.py --output /path/to/new-theme-evidence
```

不要在未授权的课件任务里安装软件、执行作者脚本或改审批策略。启动器支持参数不证明
宿主已接好真实 create/run/usage。独立测试替身只验证协议，不冒充真实模型、登录或原生 PDF。

## 交付时核对警告

`workflow status`与`task status`的`delivery_package.entries[].warning_report`提供数量及文件路径。
新发布在课件目录提供WARNINGS.md/json；零条也有记录。旧发布未记录时数量为null。
报告来自当前gate；不可编辑报告来消除warning，修改正文后重新检查才产生新修订的记录。

## 每次交互启动的任务选择

`./start.sh --task SLUG` 每次真实询问是否修改 TASK。修改分支不是恢复旧配置的要求；它允许
打开待改文稿，固定使用数据库确认 runtime。沿用分支严格核对，取消/EOF 不执行 Codex。
纯机械命令保持无交互。选择“不修改”不会自动确认新的课件批次，选择“修改”不等于批准改完后的内容。
启动器不结束已经运行的外部作业；有在途作业时应先在会话中查询真实状态，不能伪造取消。

## 局部恢复与原回执重接收

先看 `runner outstanding SLUG` 和 `runner tick SLUG` 返回的 `pending_responses`。
已有真实回执时修接收规则后用 `runner replay SLUG REQUEST_ID`；没有回执时先向真实宿主对账，
不能 replay 伪造数据。下一未派发步骤因本地输入失败而阻断时，修正原因后用
`runner resume-input SLUG ATTEMPT_ID`，随后 tick；不会重读此前已完成的所有页面。
命令失败会保留原始输入和错误，不自动豁免 schema 或证据。

## 有效政策与选定批次

`task policy-show SLUG` 给出有效TASK修订、容量、输入预算和各自来源事件。
新文本/限制用 `task policy-present SLUG [--handle-limit N] [--context-budget-bytes N]` 展示，
真实确认后 `task policy-confirm SLUG --presentation-id N --by user`。不接受更改模型或整份plan。
已有明确的历史授权自动建立索引，不从一般feedback猜测；旧event、配置和usage不改写。
`batch present SLUG --presentation P ...` / `batch confirm SLUG BATCH_ID --by user` 只启动所选
尚未交付稿，完成后暂停。它不是自动教学拆分，未知页数估计仍需planner关注。

原生Codex的离线索引、执行和对账命令见 [HOST-PROTOCOL](HOST-PROTOCOL.md)。


## 尚未交付范围的拆分与续做

先暂停并处理真实在途作业，`plan show` 读取有效分配。`plan present --proposal FILE`
接收内容范围到交付稿的完整有序分配；程序不能决定教学切点。`plan confirm ID --by ...`
只确认分配，不启动作者。新的 `batch present` 展开父范围和子稿后再确认生产批次。
已展示后输入或来源变化会拒绝旧确认；没有活跃生产时，同一确认重复执行是无副作用的。
已发布稿和正在整稿编辑/审核的稿件必须走现有返修路径，不能通过规划替换其发布记录。

子稿使用原范围配置的模型与推理强度，并继承作者参与历史。仅在新的工作目录中准备
旧单元稿；历史通过的门禁不随来源复制。若一个单元需要拆成更多课次，应先明确教学
目标与范围，不得在这条只分配既有课次的接口里伪造一个新单元。
