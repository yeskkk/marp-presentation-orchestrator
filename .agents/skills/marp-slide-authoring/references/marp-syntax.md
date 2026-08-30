# Marp syntax used by this project

Canonical frontmatter:

```yaml
---
marp: true
theme: mathist-academic
paginate: true
size: 16:9
math: mathjax
backgroundColor: '#ffffff'
---
```

Slides are separated by a line containing only `---`. Use local directives such as `<!-- _class: lead -->`. Images support Marp keywords such as `![w:600px](assets/example.svg)` and `![bg right:40%](assets/photo.jpg)`, but every image must be local and listed in ASSET-DECISIONS.yaml.


## GeoGebra links

A selected GeoGebra resource is written only as `[descriptive text](https://www.geogebra.org/...)`. Do not use an image marker `!`, raw `<a>` HTML, iframe/object/embed/script tags, or applet JavaScript. Keep enough context in the link text that a learner knows why to open it.
