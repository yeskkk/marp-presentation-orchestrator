# 计量与前台异常交接

## 只读用量报告

```bash
bash start.sh --cli report usage linear-algebra-v7 --presentation p02-01 --presentation p02-02 --presentation p03 --format md
bash start.sh --cli report usage linear-algebra-v7 --format csv --output usage.csv
```

项目安装后启动器使用 `.venv`；已安装依赖的独立解释器可显式设置 `PYTHON_BIN`。
报告读取数据库，不迁移、不调用模型、不全量解码 wire。文件输出拒绝覆盖已有文件。
usage 是账本权威来源；call_id 使用已知 audience 命名空间还原后与真实请求/原响应对应，不猜 role。
JSON 提供逐调用、按课件/作业种类/审核通道/操作分组、已知及缺失计数、attempt 序号、输入包字节。
输入含缓存，输出含推理，不能重复相加；缺失字段 total=null，known_sum 仅已知小计。
金额未取得价格和账单证据就不计算。packet 字节不是完整模型上下文，也不是 token 数。

供应端耗时来自只读的已留存 turn 索引，缺索引或时间戳则未知；不会为了报表自动重建索引。
报告显式指出索引是否落后。确需重建时由操作员运行 bridge index，不隐式写入“只读报告”。
适配器耗时包含传输、恢复或对账边界，单独列出。新记录有明确开始/结束和 invocation_kind；
旧事件只能说明当时的观测，不追溯推断这是收费调用还是恢复动作。
阶段累计时间可以相互重叠；墙钟采用区间并集。统计窗口始于首个有证据时间，不必然是任务创建。
没有用量或时间证据的 main、外部 API 调用和等待原因不补造。

## 前台交接

```bash
bash start.sh --cli supervision pending linear-algebra-v7
bash start.sh --cli supervision ack linear-algebra-v7 HANDOFF_ID --by main --note '已核对原响应，按原 request 重放程序校验，未重发模型'
```

失败、拒收、执行未知、授权待决或前台预算耗尽返回 `needs_main_attention`、稳定交接 ID、简要原因。
调用宿主负责收到前台返回和退出码；2 表示需要处理/阻塞，3 表示执行未知，Ctrl-C 返回130。
写入 events 不是原生推送，也不能证明 main 已收到。重复未确认问题去重，ack 后新事件可以再次交接。
ack 只确认接管，不改变执行事实或自动重试。正常低频监督仍不需要常驻模型观察者。
SIGKILL 或宿主直接消失无法由该进程捕获；重启后 pending 同时列出未接受 host_requests，不能忽略它们。

## 记录真实等待原因

```bash
bash start.sh --cli supervision wait-start linear-algebra-v7 --reason resource --presentation p03 --by main --note '指定教材尚未挂载'
bash start.sh --cli supervision wait-end linear-algebra-v7 WAIT_ID --by main
```

reason 仅允许 user_decision、environment、resource、provider_reconciliation、scheduling、main_processing、other。
须记录实际原因，不能为让报表好看自动把所有空档记为外部等待。未结束等待的秒数保持未知。
原始计量及交接记录由存储保留策略保护；压缩调试正文不改变这些记录。
