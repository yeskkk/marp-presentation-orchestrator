# Unit handoff minimum

A lesson author hands off:

- `section.md` and namespaced approved local assets;
- `UNIT-MANIFEST.yaml`;
- canonical `INTERACTION-RECORD.yaml` (compatibility interaction/MCQ views are generated mechanically);
- `UNIT-DELTA.yaml`;
- `UNIT-CONTEXT-PACKET.yaml`;
- `LESSON-TIME-PLAN.yaml`;
- `GEOGEBRA-RESOURCES.yaml`;
- `SELF-CHECK.md` and the durable checkpoint.

Slide IDs, semantic-object IDs, terminology, examples, global meeting number, and deck-local ordinal must match coordinator registries. A section fragment contains no YAML frontmatter and does not redefine global theme directives. After validation and integration, the lesson author may close; later revision uses the compiled deck context packet instead of live lesson scratch space.

`GEOGEBRA-RESOURCES.yaml` records whether a bounded `geogebra.org` search was relevant and attempted, the queries used, selected links, or the reason none was selected. Resources appear in `section.md` only as ordinary descriptive Markdown hyperlinks.
