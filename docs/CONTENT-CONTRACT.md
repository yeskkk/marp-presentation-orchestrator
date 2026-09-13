# 内容契约：学生内容、源稿和工具边界

## 1. 可见内容与内部记录

| 保留在学生页 | 留在语义结果/数据库 |
|---|---|
| 当前问题、规范概念、必要条件、例题、答案理由、图形对应 | 先修假设清单、授课时钟、核心/补充控制说明 |
| 影响模型含义的假设与模拟数据披露 | “已检查术语”“本页满足几何要求”等验收自证 |
| 必要事实/外部图示的简短可访问出处 | 提取 TXT 行号、无用途摘录、资料缺口与等待授权 |

不是屏蔽词表：需要旧知识就给实际回顾题，需要边界就说明改变结论的条件。
删去一句没有学习损失则删/移；保留理由要具体到当前数学，不能只有“有教学意义”。
规范术语不等于证明密集；proof_depth 以确认要求为准。制作质量的承诺不等于已经有页内证据。

## 2. 合法源稿骨架

````markdown
---
marp: true
theme: mathist-academic
paginate: true
size: "16:9"
math: mathjax
---
<!-- slide-id: p01-l01-s01 -->
<!-- _class: core -->
# 哪一组数同时满足两个条件？

$x+y=2$ 与 $x-y=0$ 的共同解需要同时满足两式。

---
<!-- slide-id: p01-l01-s02 -->
<!-- _class: support -->
# 代回去检查

取 $x=1,y=1$，分别代回原式。
````

标题/段落/列表/强调/代码/标准表格/数学/分页/本地外部图片可用。raw HTML、内嵌 SVG、
HTML 表格、任意 comment/class/frontmatter style、局部图片大小/背景/filter、TeX CSS/缩字绕过
均禁止。字面代码里的 HTML 和数学小于号不是嵌入 HTML。机器元数据仅白名单注释。
真实检查以 `source_policy.py` 为准；文档不授权新语法。

## 3. 固定主题与过满内容

作者/编辑不拥有 theme.css；runner 安装当前只读主题，缺省提交时由新快照补齐。
不同课次主题不拼接。表格网格与字体由项目统一负责，表格宽/长则拆正文；
图片独立成段、图注另段。主题里的兼容类不代表可以使用 HTML 挂载类。

源稿过满应删空话、拆例题、分题目与答案、增加补充页；不把正文截图、缩公式或移出画布。
新主题的 gate 不能沿用旧主题结果；历史 artifact 不自动改写。

## 4. 从数学输入生成图

```json
{"version":1,"kind":"lines","lines":[[1,1,2],[1,-1,0]]}
```

```bash
mpres figure build assets/l01/intersection.plot.json
mpres figure check path/to/output
```

用同一方程定义求交点并画线点，不另填像素交点。受支持题材还有 projection、transform，
参数以实际生成器为准；不支持的题材不伪装成已经由门禁验算。
生成 `.svg`、`.plot.json`、`.py` 在 assets/<unit-id>/，标准 Markdown 引用：

```markdown
![两条直线的共同解](assets/l01/intersection.svg)
```

只改输入后重生成，不能手改 SVG；验证器用项目生成器重算，不执行作者/历史 Python。
新工作副本可迁移旧1/2/3版图示；已有草稿不自动覆盖。图与给定数学一致不证明教学选择恰当。

## 5. 三个不同检查级别

`source check` 验表达契约；artifact source gate 另核稳定 ID、core/support、TeX/资源等；
full gate 真跑固定 Marp、DOM、数学和 PDF 结构。机械成功不证明语义质量。
PDF 模型视觉、截图或 OCR 不是默认纠错路径；写作者修正文、工具维护修检查器，不能互相替代。

## 6. 结果规范与例子

四份 JSON Schema 在 `src/mpres/control/schemas/`。顶层未知字段会被拒；条件性要求取自请求。
结果中的 feedback_checks 引用实际 slide_id 与 quote；没有执行到的下游门禁不宣称已完成。
findings 由 reviewer 提，resolutions 由作者处置，状态由 runner 登记；三者不可互换。
