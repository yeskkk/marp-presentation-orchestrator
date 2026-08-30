from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from mpres.production import initialize_production
from mpres.tasks import confirm_task, create_task, present_task


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[1]
    for name in ["templates", "themes", ".agents", ".codex"]:
        shutil.copytree(source / name, tmp_path / name)
    for name in ["pyproject.toml", "package.json", "AGENTS.md"]:
        if (source / name).exists():
            shutil.copy2(source / name, tmp_path / name)
    (tmp_path / "tasks").mkdir()
    return tmp_path


def fill_placeholders(path: Path, value: str = "已由任务规划者完整填写的具体内容") -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\[\[[A-Z0-9_]+\]\]", value, text)
    path.write_text(text, encoding="utf-8", newline="\n")


def make_confirmed_task(root: Path, *, stop_mode: str = "all") -> str:
    slug, task = create_task(
        root=root,
        title="测试课程",
        slug="test-course",
        kind="course",
        stop_mode=stop_mode,
        sessions=2,
        minutes=90,
    )
    fill_placeholders(task / "TASK.md")
    with (task / "TASK.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\n" + "完整规划说明。" * 240)
    present_task(root, slug)
    confirm_task(root, slug)
    return slug


def initialize_one_deck(root: Path, *, stop_mode: str = "all") -> tuple[str, Path]:
    slug = make_confirmed_task(root, stop_mode=stop_mode)
    initialize_production(
        root,
        slug,
        ["p01::第一份课件"],
        ["p01::u01::第一节内容"],
    )
    return slug, root / "tasks" / slug


def complete_assignments(task: Path) -> None:
    paths = [
        task / "workers" / "author-coordinator" / "assignments" / "p01" / "TASK-AUTHOR-COORDINATOR.md",
        task / "workers" / "review-coordinator" / "assignments" / "p01" / "TASK-REVIEW-COORDINATOR.md",
        task / "workers" / "release-coordinator" / "assignments" / "p01" / "TASK-RELEASE-COORDINATOR.md",
        task / "workers" / "lesson-authors" / "p01" / "u01" / "TASK-LESSON-AUTHOR.md",
    ]
    for path in paths:
        fill_placeholders(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n\n" + "任务差异与验收要求。" * 30)


def complete_author_source(task: Path) -> Path:
    complete_assignments(task)
    unit = task / "workers" / "lesson-authors" / "p01" / "u01" / "source"
    section = unit / "section.md"
    fill_placeholders(section)
    section.write_text(
        "<!-- slide-id: p01-u01-s01 -->\n<!-- _class: core -->\n\n"
        "## 第一节内容\n\n这是一个用于验证 Marp PDF 流程的清晰页面。\n",
        encoding="utf-8",
    )
    (unit / "UNIT-MANIFEST.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "presentation_id": "p01",
                "unit_id": "u01",
                "title": "第一节内容",
                "slide_ids": ["p01-u01-s01"],
                "concept_chains": ["chain-1"],
                "semantic_objects": [],
                "examples": [],
                "assets": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (unit / "SELF-CHECK.md").write_text(
        "# Unit self-check\n\n" + "已检查对象、术语、听众进入点和页面内容。\n" * 30,
        encoding="utf-8",
    )
    (unit / "GEOGEBRA-RESOURCES.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "presentation_id": "p01",
                "unit_id": "u01",
                "relevant": False,
                "rationale": "This test unit does not need an interactive GeoGebra resource.",
                "site_scope": "geogebra.org",
                "search_attempted": False,
                "search_queries": [],
                "search_outcome": "not_applicable",
                "selected_resources": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    author = task / "workers" / "author-coordinator" / "drafts" / "p01" / "source"
    header = author / "HEADER.md"
    fill_placeholders(header)
    header.write_text(
        "---\nmarp: true\ntheme: mathist-academic\npaginate: true\nsize: '16:9'\n"
        "math: mathjax\nbackgroundColor: '#ffffff'\n---\n\n"
        "<!-- _class: lead core -->\n<!-- slide-id: p01-title -->\n\n"
        "# 第一份课件\n\n测试课程\n",
        encoding="utf-8",
    )
    for name in [
        "PEDAGOGY-MAP.md",
        "EXAMPLE-MAP.md",
        "TERMINOLOGY.md",
        "SEMANTIC-OBJECTS.yaml",
        "SELF-CHECK.md",
        "RELEASE-RETROSPECTIVE.md",
    ]:
        fill_placeholders(author / name)
    (author / "SELF-CHECK.md").write_text(
        "# Deck self-check\n\n" + "已检查内容、术语、随机进入、Marp 源和 PDF 结构。\n" * 35,
        encoding="utf-8",
    )
    (author / "ASSET-DECISIONS.yaml").write_text(
        "schema_version: 1\npresentation_id: p01\npolicy:\n  python_generated: disabled\nassets: []\n",
        encoding="utf-8",
    )
    return author


def finalize_canonical_source(root: Path, slug: str, task: Path) -> Path:
    from mpres.production import assemble_units

    assemble_units(root, slug, "p01")
    author = task / "workers" / "author-coordinator" / "drafts" / "p01" / "source"
    (author / "DECK-MANIFEST.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "presentation_id": "p01",
                "title": "第一份课件",
                "content_units": [
                    {"id": "u01", "title": "第一节内容", "source": "sections/u01/section.md"}
                ],
                "slides": [
                    {"id": "p01-title", "unit": "front", "kind": "core", "concept_chain": "intro", "semantic_objects": [], "examples": [], "assets": [], "source_refs": []},
                    {"id": "p01-u01-s01", "unit": "u01", "kind": "core", "concept_chain": "chain-1", "semantic_objects": [], "examples": [], "assets": [], "source_refs": []},
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return author


def install_fake_marp(root: Path) -> Path:
    binary = root / "node_modules" / ".bin" / "marp"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(
        """#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
import fitz

if '--version' in sys.argv:
    print('4.5.0')
    raise SystemExit(0)
args = sys.argv[1:]
try:
    source = Path(args[0])
    output = Path(args[args.index('--output') + 1])
except Exception:
    print('invalid fake marp invocation', file=sys.stderr)
    raise SystemExit(2)
text = source.read_text(encoding='utf-8')
markers = sum(1 for line in text.splitlines() if line.strip() == '---')
pages = max(1, markers - 1)
doc = fitz.open()
for index in range(pages):
    page = doc.new_page(width=960, height=540)
    page.insert_text((72, 90), f'Marp test slide {index + 1}', fontsize=28)
    page.insert_text((72, 140), 'Readable mathematical presentation content.', fontsize=22)
output.parent.mkdir(parents=True, exist_ok=True)
doc.save(output)
doc.close()
print(f'Wrote {output}')
""",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary
