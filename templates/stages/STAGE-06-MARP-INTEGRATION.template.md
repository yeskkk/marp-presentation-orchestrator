# Stage 06 — Marp 集成与单元自检（[[PRESENTATION_ID]] / [[UNIT_ID]]）

## 生成产物

- `source/section.md`
- `source/UNIT-MANIFEST.yaml`
- `source/INTERACTION-RECORD.yaml`（唯一可编辑的互动与 MCQ 真源）
- `source/UNIT-DELTA.yaml`
- `source/UNIT-CONTEXT-PACKET.yaml`
- `source/LESSON-TIME-PLAN.yaml`
- `source/GEOGEBRA-RESOURCES.yaml`
- `source/SELF-CHECK.md`
- 本地、获准资产

`INTERACTION-MANIFEST.yaml` 与 `MCQ-AUDIT.yaml` 由程序从 `INTERACTION-RECORD.yaml` 生成，不得分别手工维护。

## 集成检查

[[MARP_INTEGRATION_NOTES]]

## TeX 与互动检查

逐个数学环境检查裸 TeX 控制词；逐个互动检查 prompt/answer 相邻、core/support 配对、答案不泄露；课程单元的 MCQ 数必须为 2 或 3，报告单元无数量要求。

[[TEX_AND_INTERACTION_AUDIT]]

## 交付判定

[[HANDOFF_READINESS]]
