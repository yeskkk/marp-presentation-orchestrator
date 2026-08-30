# Marp authoring standard

## 源文件

- canonical source 是 `presentation.md`；各 lesson author 提交不含 YAML frontmatter 的 `section.md`。
- 幻灯片用单独一行 `---` 分隔；代码块和数学环境中的横线不算分页。
- 每页必须有 `<!-- slide-id: ... -->` 和 `<!-- _class: core -->` 或 `support`。
- 全局指令只出现在 canonical frontmatter；局部样式使用 Marp local directives 或已批准的 CSS 类。
- 数学使用 `$...$` 与 `$$...$$`，frontmatter 采用 `math: mathjax`。

## 内容密度

标题应简洁但不能牺牲对象和主语。3–5 个 bullet 是常见而非机械硬规则；一页一条主要消息。文字过多时优先拆页，不缩小字体。

## 表格、CSS 与图片

- 比较、分类、条件—性质、步骤—解释优先使用 Markdown 表格。
- 两栏、提示框和公式卡优先使用统一主题 CSS。
- 本地图片必须有教学目的、替代文本和来源；背景图只在不会损害文字可读性时使用。
- Python 图形默认关闭；经 TASK 和资产决策表批准后才可运行。


## GeoGebra 在线资源

- 对确实适合动态探索的数学内容，lesson author 可以做一次限量检索；检索范围只允许 `geogebra.org`。
- 检索不是配额：不相关时写明理由后停止；相关但没有找到合适资源时记录结果，不勉强添加。
- 每个内容单元最多使用策略文件规定的少量链接。
- 选中的资源只以普通 Markdown 超链接出现；禁止 iframe、object、embed、script、GGBApplet、远程图片、截图、缩略图和下载副本。
- PDF 离线阅读时内容仍须完整；链接只是课后或课堂外的可选探索。

## 只输出 PDF

标准构建只运行 Marp CLI 的 PDF 输出。项目不生成、不保存、不审查 HTML，也不使用 HTML 作为内容阅读材料。
