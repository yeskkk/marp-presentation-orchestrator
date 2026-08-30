# Marp Presentation Orchestrator

这是一个以 **Codex CLI + Marp CLI** 为核心的课程/报告课件工作流。它把重点放在内容规划、并行写作、三轮独立审核和 PDF 交付，不再生成或检查课堂 HTML。

## 核心路线

```text
Marp Markdown + theme.css + local assets
              ↓
       @marp-team/marp-cli
              ↓
             PDF
```

项目没有 Quarto、Jupyter kernel、Reveal.js、Beamer 或 Marp HTML 交付件。Marp 内部可以调用 Chrome/Chromium/Edge/Firefox 生成 PDF，但工作目录只保留 PDF。

## 固定规则

开始任务时会提醒用户：

1. 每份课件必须经过初审、增量复审和终审三轮；
2. 每轮都有语言、领域正确性、版式/PDF、教学编排、听众契合五个通道；
3. 禁止课件截图、PDF 页栅格化/contact sheet 和模型视觉审核；
4. 默认推理强度为 `medium`，研究级或学术报告建议提高到 `high`/`max`；
5. Python 作图默认关闭；
6. 只有任务顶层 `TASK.md` 使用确认哈希；
7. 可以选择先交付第一份课件后暂停 (`pilot`)。

## 角色

```text
planner
├── author-coordinator × presentation
│   └── lesson-author × course meeting/content unit
├── review-coordinator × presentation
│   └── specialist-reviewer × 5 channels × 3 rounds
└── release-coordinator × presentation
```

不再使用 `worker1`、`worker2` 之类的编号角色名称。

## 安装要求

- Python 3.11+
- Node.js 18+
- npm
- Codex CLI
- Chrome/Chromium、Edge 或 Firefox 中至少一种
- `pdftotext`
- Tesseract 可选，仅用于扫描参考文献 OCR

Marp CLI 版本由 `package.json` 固定为 `@marp-team/marp-cli 4.5.0`。

## 启动

Linux/macOS：

```bash
chmod +x start.sh
./start.sh
```

Windows PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start.ps1
```

更安全的替代启动器：

```bash
./start-safe.sh
```

```powershell
.\start-safe.ps1
```

## 手动初始化

```bash
python scripts/bootstrap.py
```

需要启用可选 Python 图形包时：

```bash
python scripts/bootstrap.py --with-figures
```

安装完成后：

```bash
.venv/bin/mpres doctor --strict
```

Windows 使用 `.venv\Scripts\mpres.exe`。

## 初始任务流程

```bash
mpres task init \
  --title "课程题目" \
  --kind course \
  --sessions 16 \
  --minutes 90 \
  --stop-mode pilot
```

规划者填写 `tasks/<slug>/TASK.md`，然后：

```bash
mpres task present <slug>
# 等待用户明确确认当前版本
mpres task confirm <slug>
```

确认后定义 presentation 和内容单元：

```bash
mpres production init <slug> \
  --presentation "p01::第一部分" \
  --unit "p01::lesson01::第一课" \
  --unit "p01::lesson02::第二课"
```

## 作者流程

每个 lesson author 在自己的目录中写 `section.md`。协调者完成结构化地图并整合：

```bash
mpres author assemble <slug> --presentation p01
mpres source lint <slug> --presentation p01
mpres assets validate <slug> --presentation p01
mpres geogebra validate <slug> --presentation p01
mpres render <slug> --presentation p01 --stage author
```

Marp 源必须包含：

```yaml
---
marp: true
theme: mathist-academic
paginate: true
size: '16:9'
math: mathjax
---
```

每页都有稳定 slide ID 和 `core`/`support` 类。


## GeoGebra 补充资源

lesson author 会先判断本节内容是否适合动态探索。相关时才做一次小规模、仅限 `geogebra.org` 的检索；每节最多使用策略文件规定的少量资源。没有合适结果便记录后停止，不为了“有链接”而添加链接。

选中的资源必须写成普通 Markdown 超链接，例如：

```markdown
[GeoGebra：拖动参数观察函数图像](https://www.geogebra.org/m/RESOURCE_ID)
```

项目禁止 iframe、GeoGebra applet 脚本、远程预览图、截图、下载副本或任何形式的嵌入。PDF 本身必须完整可学；GeoGebra 只作为可选的课后或课堂外探索。每个 unit 都用 `GEOGEBRA-RESOURCES.yaml` 记录是否相关、检索词、结果和实际链接，整合时自动核对登记表与 `section.md`。

## Python 图形

Python 图形不是普通作者工具。要使用必须同时满足：

- TASK.md 明确允许；
- `EXECUTION-POLICY.yaml` 将 `python_generated` 改为 `enabled`；
- `ASSET-DECISIONS.yaml` 批准具体 asset；
- 说明 Markdown 表格、公式、CSS 布局和已有图片为何不够；
- 优先 SVG；带文字的栅格图禁止；
- 图形报告未发现小字和箭头遮字。

## 三轮审核

```bash
mpres review request <slug> --presentation p01
# 五通道提交
mpres review aggregate <slug> --presentation p01 --round initial --report ...
# 作者回应、重建
# incremental
# final
# terminal closure
```

增量轮只看旧 finding、指定改动和 regression；终审重新看全稿；closure 不是第四轮审核。

## 监督

主代理只在二十分钟到期或一份课件交付时做高层检查：

```bash
mpres supervise <slug> --scope planner --record
```

作者/审核协调者负责更细的并行角色监督：

```bash
mpres supervise <slug> --scope author --presentation p01 --record
mpres supervise <slug> --scope review --presentation p01 --record
```

## 主要命令

```text
mpres doctor
mpres task ...
mpres production ...
mpres author assemble
mpres role assignment-check / heartbeat
mpres checkpoint save / status
mpres reference ingest
mpres source lint
mpres assets validate / generate
mpres geogebra validate
mpres render
mpres inspect pdf
mpres review ...
mpres supervise
mpres token ...
mpres audit
```

## 交付目录

```text
tasks/<slug>/deliverables/<presentation>/
├── <presentation>.pdf
├── source/
├── findings.yaml
├── CLOSURE.md
├── render-report.json
├── pdf-inspection.json
└── release.json
```

## 验证

本版本的详细构建和测试记录见 `docs/VALIDATION.md`。自动测试覆盖 GeoGebra 站内检索登记、`/m/<resource-id>` 链接约束、禁止嵌入、Marp PDF-only 构建、三轮审核和并行生产。目标机器第一次正式使用前仍须运行 `mpres doctor --strict` 和真实 Marp PDF 冒烟测试。

## 已知限制

- 禁用截图意味着某些纯视觉审美问题仍须通过源结构、PDF 文字框、字号和人工阅读来判断；
- PDF 结构检查不能证明教学设计正确，因此五通道审核仍不可省略；
- 可选 Python 图形检查只能发现部分机械缺陷；
- Codex subagent 的 spawn/steer/restart 仍由 Codex 会话执行，仓库不是独立 App Server 调度器。
