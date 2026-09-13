# 验证口径与发布

## 1. 可执行检查

```bash
PYTHONPATH=src python -m pytest tests/compact
python scripts/validate_project.py
python scripts/check_documentation.py
python -m compileall -q src scripts tests
bash -n start.sh start-safe.sh
```

既有 legacy 回归继续保留；涉及 daemon/进程 fixture 的模块使用独立 pytest 进程，
不要并发写同一个 fixture 工作区。每个阶段包重新解压、独立跑完整模块，失败不能通过删除测试规避。
校验模板 relocation 只调整 fixture/路径断言，不放宽原行为。

## 2. 文档不是无测试资产

检查当前/兼容模板集合、默认配置语义不漂移、文档本地链接、命令示例被实际 parser 接受，
并验证角色说明的存在和消费路径。变更教学规则时同时改具体正反例，不仅测试某关键词出现。
内容例子必须经过现有 Schema/源码检查；最小 JSON 示范不等于带真实回执的完整提交。

## 3. 迁移与内容保护

打开旧库不重写配置/源码/历史 gate。目录 materialize、旧图重生成、review-first 在任务副本验证。
主题/HTML/数学/资料/权限限制不因文档重排放松。准确记录使用哪份基线和哪些真实证据。

## 4. 不得夸大测试

确定性宿主替身验证协议和分支，不证明真实模型的教学质量或真实学生体验。
原生 Matplotlib 图示不等于原生 Marp PDF；缺固定 Marp/账号时如实注明，不造通过证据。
原生检查命令为 `mpres toolchain doctor` 和 `scripts/verify_theme.py`，只在独立输出目录运行。
源码包生成后核对 ZIP 完整性、路径、文件字节、无私有数据/字体；不新增文件 hash 清单。
