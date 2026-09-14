# 升级到 v0.9.x 并返修既有课件

各版本是累计完整源码，不是顺序安装的补丁。采用最新 v0.9.3 即含前三版改进；旧版本留作里程碑。
升级程序不代表此次已经重做了课件。本次验证没有调用真实模型，不改上传的任务、课件或原数据库。

## 保护既有任务

先让任务与 adapter 停在可确认的安全点；未知执行先对账，不强杀后假定完成。
保留整个旧项目/任务备份，包括 tasks、.mpres、素材、不可变源码、已交付 PDF/Markdown、用户配置。
不要只留一个 task.sqlite3，也不要把空的新任务目录覆盖过去。运行副本的24项局部修复已纳入累计源码。
升级 src、scripts、.agents、模板和配套文档；TASK/task.yaml/runtime、实际材料与运行数据保持原样。
依赖安装按原项目 bootstrap 文档操作，数据库不要在旧版和新版程序间交替写入。

```bash
bash start.sh --cli storage inspect linear-algebra-v7
bash start.sh --cli storage migrate linear-algebra-v7 --by owner
bash start.sh --cli task policy-show linear-algebra-v7
bash start.sh --cli supervision pending linear-algebra-v7
bash start.sh --cli report usage linear-algebra-v7 --presentation p02-01 --presentation p02-02 --presentation p03 --format md
```

只读 inspect/report 不迁移；显式 migrate 把 schema 升到12并写审计。没有降级迁移；回退须用升级前完整备份，
不能让 v0.8.10 写 schema12。清理不是升级的前置条件；有未解决执行时先保留数据，不为缩库破坏恢复证据。
新命令可经 bash start.sh --cli 使用；没有项目 .venv 时显式设置 PYTHON_BIN 指向已安装依赖的解释器。

## 只返修 p02-01、p02-02、p03

全局新规则经活动 guidance 输入，不靠 legacy 模板，也不改写旧发布的审核事实。
但返修的准确范围、目标发布版本和新用户要求必须走现有正式修订/返修路径。
先核对有效 TASK；确需写入本次用户新要求时，使用 policy-present / policy-confirm 展示和登记精确变化。
不要自动确认、用新模板替换整份 TASK、改变已确认 low/runtime/容量或清空历史记录。

给主代理的返修说明可以使用：

> 本次只处理 linear-algebra-v7 的 p02-01、p02-02、p03，基于各自当前已提交的发布版本。
> 全量检查所有实际要求学生作答的随堂练习及附加子问，不限已发现的五页。
> 题干和必要具体数据、对象、图示、单位、条件须在同一题目页给足或足以确定；允许运用已学知识，
> 不允许记忆前例的实例数字。答案可另页但不能补题设；一页放不清则简化或更换同目标题，不能缩字。
> 修题时同步答案、图形、引用和练习索引。维持合理编拟生活算例原则，不因无新闻出处阻塞。
> 不修改 p01，不重规划课程，不启动后续课件；不增加第六审核通道或作者修改后的全套 reviewer 验修。
> 先展开并展示准确返修范围，收到明确确认后按已确认 edit-first 流程执行；新修订实际通过当前机械门禁。

已知问题定位（只是种子，不代替全量覆盖）：p02-01 第67页；p02-02 第22、32、40页；p03 第31页。
程序使用稳定 slide-id 定位；页码仅指此次归档的旧稿。返修提案需允许必要的题目替换，不能机械只补一个 A。
`repair open` 精确选择三个 presentation，然后诊断/展开，`repair present` 展示，`repair confirm` 记录真实确认。
范围尚未展开前不直接伪造 proposal_version 或 --by 用户的同意。默认 edit-first；本次不主动追加 review-first。

## 返修后应看到的证据

新写作/编辑/返修输出含 exercises.json、题页自检覆盖；教学法和学生视角有逐题 exercise_checks，
缺必要题设形成明确阻断 finding。隔离题页接口只返回该页学生可见内容及本页图形路径，不夹答案/备注。
机器验证索引、页引用与审核覆盖，不宣称能仅靠关键词证明语义充分；实际教师质量仍需真实返修交付检验。
历史已派发/已接受结果不追溯按新 schema 拒收，新派发修订应用新契约。用户最终取得仍是实际 ready 交付件。

## 存储与日志

先看 dry-run，再明确 apply，最后 compact。默认保留期内的新记录不会因为本轮测试可缩库就立即删除。
留存、迁移和压缩的限制见 [存储维护](STORAGE-MAINTENANCE.md)。不要虚报节省 token：本地缩库不是模型上下文清空。
