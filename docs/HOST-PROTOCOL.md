# 宿主接入：机械请求，不是 AI skill

## 1. 所有权

Runner 生成 operation/request_id/job/attempt/session、精确 runtime 和输入包。
宿主执行真实工具或模型调用，返回 receipt、实际模型与强度、usage。AI 只填写 result 中的
教学内容，不能自己生成“真实 provider receipt”。三种身份不能混淆。

支持 `provider.mode=command`（用户配置 argv，JSON stdin/stdout）与 `bridge`（宿主转发）。
项目不自带某个未公开 Codex API 的假实现，不承诺任何环境都有 close/reset/inventory。

## 2. 五种请求的顺序

| operation | 输入 | 输出和限制 |
|---|---|---|
| capabilities | 查询真实宿主 | receipt、handle_limit、handles、supports_close/reset、usage_reporting；不是复述用户设置 |
| create | request_id、slot_id、runtime | handle、model、reasoning_effort、receipt；幂等创建，对账未知结果 |
| brief | attempt/session、历史反馈快照 | runtime、receipt、usage、readback；每项 id/version/approach，未完成不发 run |
| audience_step | 同一 reviewer 的当前 phase/sequence 与页范围 | runtime、receipt、usage、result；按实际 result_schema 回传，不能跳步/编辑原稿 |
| run | attempt/session、packet、result_schema | runtime、receipt、usage、result；只有作者有 source_dir，且必须位于本次 output |

一般为 capabilities → create/复用 → brief → run。audience 为 brief → 多次 audience_step
→ 最终 run 汇总，不另起三名 reviewer。readback 已经读过反馈，不声称这是认知盲测。

## 3. 输入包及模型工作范围

`input_files` 里的必读文本必须完整提供；不能先自动摘要/截断整稿再让 reviewer 宣称读过。
`resource_manifest` 是允许按需访问的准确文件，不自动内联 SVG/XML/PDF/主题/脚本。
引用资源清单不证明已读；不能默认读取整个任务目录，也不能执行 reproduction_source。

`semantic_guidance` 说明当前角色怎么作语义判断；`result_schema` 是此次结构约束；
`required_result`、historical_feedback、repair_scope 给出条件性义务。优先使用实际请求，
不要把某个旧版固定 JSON 格式粘贴给所有角色。工作模式由请求决定，不由模型自己改。

`source_preparation` 指出新工作副本的主题/旧图示重生成结果。不要复制历史 SVG/主题覆盖新副本。
`submission_correction` 表示真实调用已完成、结果被拒，需新 attempt 有界修正；不是重发旧请求。

## 4. 结果、用量与传输证据分开

作者 result 使用 author-result；review 使用 review-result；diagnose 使用 diagnosis-result。
planning 是 plan 语义对象，不是 runner 自动安排的人员队列。JSON Schema 只是第一层；
服务层还核对 slide ID/真实摘录、finding、当前反馈版本和明确删页授权。

usage 是 `{call_id, counters}` 数组；counters 包括 input_tokens、cached_input_tokens、
output_tokens、reasoning_tokens、total_tokens。未知写 null；不要把缓存/推理重复加进总量，
不要把 receipt 中整段历史对话复制进每个 result。各协议字段的真实处理在 runner.accept。

同一个请求重放只允许相同真实证据；不接受冲突 receipt 或 hidden runtime fallback。
已有 runtime/usage 表明执行完成时，确定的源码拒收可进入有限修正；丢失回执/运行状态未知
必须 outstanding/宿主对账，不盲目再创建或释放 session。

## 5. bridge 示例（文件仅为传输，数据库仍是真源）

```bash
mpres --root . runner host economics --report actual-host.json
mpres --root . runner tick economics
mpres --root . runner accept economics --request exact-request.json --response actual-response.json
mpres --root . runner outstanding economics
```

JSON 可由 stdin 传入。main 只做必要转发，不在转发时重新选模型、重排课程或宣布 gate 通过。
bridge 有实际工具回合，不宣传为零模型控制成本。unknown 状态不靠改 SQL/回执文件“修好”。

## 6. 部署验收

用真实宿主验证每个 operation、重复 request 的幂等性、短回执和部分用量、异常断线、
过期 inventory、budget 失败与恢复。再做小规模课程与原生渲染，不把 fixture 当生产接线。
当前源码不包含用户任务里所有本地 bridge 补丁，文档整理也不会自动安装/接通它们。
