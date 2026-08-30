from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from mpres.geogebra import validate_presentation_geogebra_registry
from mpres.interactions import MCQ_RATIONALES, validate_presentation_interactions
from mpres.util import MPresError, read_yaml, relative_display, task_path, write_json_atomic

SLIDE_ID_RE = re.compile(r"<!--\s*slide-id\s*:\s*([^>]+?)\s*-->", re.IGNORECASE)
CLASS_RE = re.compile(r"<!--\s*_class\s*:\s*([^>]+?)\s*-->", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HTML_IMAGE_RE = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
BULLET_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+", re.MULTILINE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]+>")
MATH_BLOCK_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
INLINE_MATH_RE = re.compile(r"\$(?!\$).*?(?<!\$)\$", re.DOTALL)
REMOTE_RE = re.compile(r"^(?:https?:)?//", re.IGNORECASE)

# This is deliberately a known-command list rather than a generic English-word
# heuristic.  It catches the common failure mode where a TeX control word loses
# its leading backslash without treating every multi-letter identifier as an
# error.  Longer alternatives are compiled first so reports preserve the exact
# token (for example, ``qquad`` rather than ``quad``).
BARE_TEX_CONTROL_WORDS = (
    "Longleftrightarrow",
    "Longrightarrow",
    "Longleftarrow",
    "Leftrightarrow",
    "Rightarrow",
    "Leftarrow",
    "longleftrightarrow",
    "longrightarrow",
    "longleftarrow",
    "operatorname",
    "underbrace",
    "overbrace",
    "substack",
    "varepsilon",
    "vartheta",
    "varsigma",
    "varrho",
    "varphi",
    "mathbb",
    "mathbf",
    "mathcal",
    "mathrm",
    "mathsf",
    "mathtt",
    "textrm",
    "textsf",
    "texttt",
    "overline",
    "underline",
    "supseteq",
    "subseteq",
    "nrightarrow",
    "nleftarrow",
    "rightarrow",
    "leftarrow",
    "mapsto",
    "implies",
    "partial",
    "nabla",
    "approx",
    "equiv",
    "propto",
    "notin",
    "supset",
    "subset",
    "argmin",
    "argmax",
    "bmod",
    "pmod",
    "dfrac",
    "tfrac",
    "qquad",
    "boxed",
    "begin",
    "infty",
    "lambda",
    "upsilon",
    "epsilon",
    "ldots",
    "cdots",
    "vdots",
    "ddots",
    "Gamma",
    "Delta",
    "Theta",
    "Lambda",
    "Sigma",
    "Upsilon",
    "Omega",
    "sqrt",
    "frac",
    "text",
    "mbox",
    "left",
    "right",
    "cdot",
    "times",
    "leq",
    "geq",
    "neq",
    "parallel",
    "perp",
    "forall",
    "exists",
    "emptyset",
    "setminus",
    "cap",
    "cup",
    "land",
    "lor",
    "iff",
    "quad",
    "sum",
    "prod",
    "iint",
    "iiint",
    "int",
    "lim",
    "min",
    "max",
    "det",
    "gcd",
    "exp",
    "log",
    "ln",
    "sin",
    "cos",
    "tan",
    "alpha",
    "beta",
    "gamma",
    "delta",
    "zeta",
    "eta",
    "theta",
    "iota",
    "kappa",
    "mu",
    "nu",
    "xi",
    "pi",
    "rho",
    "sigma",
    "tau",
    "phi",
    "chi",
    "psi",
    "omega",
    "ell",
    "Re",
    "Im",
    "to",
    "in",
    "div",
    "pm",
    "mp",
    "le",
    "ge",
    "ne",
    "dots",
    "end",
)
BARE_TEX_AMBIGUOUS_CONTROL_WORDS = frozenset(
    {
        "Re",
        "Im",
        "in",
        "to",
        "pm",
        "mp",
        "le",
        "ge",
        "ne",
        "ln",
        "mu",
        "nu",
        "xi",
        "pi",
    }
)
BARE_TEX_CONTROL_WORD_RE = re.compile(
    r"(?<![\\A-Za-z])(?P<command>"
    + "|".join(
        re.escape(word)
        for word in sorted(
            set(BARE_TEX_CONTROL_WORDS) - BARE_TEX_AMBIGUOUS_CONTROL_WORDS,
            key=len,
            reverse=True,
        )
    )
    + r")(?![A-Za-z])"
)
BARE_TEX_AMBIGUOUS_CONTROL_WORD_RE = re.compile(
    r"(?<![\\A-Za-z_{}])(?P<command>"
    + "|".join(
        re.escape(word) for word in sorted(BARE_TEX_AMBIGUOUS_CONTROL_WORDS, key=len, reverse=True)
    )
    + r")(?![A-Za-z_{}])"
)
MATH_FRAGMENT_RE = re.compile(
    r"(?P<block>\$\$(?P<block_body>.*?)\$\$)"
    r"|(?P<inline>(?<![\\$])\$(?!\$)(?P<inline_body>.*?)(?<![\\$])\$(?!\$))"
    r"|(?P<bracket>\\\[(?P<bracket_body>.*?)\\\])"
    r"|(?P<paren>\\\((?P<paren_body>.*?)\\\))",
    re.DOTALL,
)
FENCED_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
TEX_TEXT_ARGUMENT_RE = re.compile(
    r"\\(?:text|textrm|textsf|texttt|mbox|operatorname|mathrm|mathbf|mathsf|mathtt|mathcal|mathbb)\s*\{"
)
EXERCISE_TITLE_RE = re.compile(
    r"(?:随堂练习|课堂练习|小结练习|练习|自测|小测|试一试|你来做|停下来做|先做|"
    r"学生判断|现场判断|综合判断|判断[:：]|错误诊断|现场互译|哪里不严谨|逐条改写|"
    r"exercise|self[- ]?check|quiz|try it)",
    re.IGNORECASE,
)
EXERCISE_RESPONSE_MARKER_RE = re.compile(
    r"^\s*(?:\*\*)?(?:参考答案|答案|解答|解题步骤|solution|answer)"
    r"\s*(?:\*\*)?\s*[:：]\s*(?:\*\*)?",
    re.IGNORECASE | re.MULTILINE,
)
INTERACTION_ROLES = {"exercise_prompt", "exercise_hint", "exercise_answer"}
MULTIPLE_CHOICE_RATIONALES = MCQ_RATIONALES
MULTIPLE_CHOICE_OPTION_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:\*\*)?(?P<label>[A-Z])"
    r"(?:[.)：:、．）])(?:\*\*)?(?:\s+|$)",
    re.MULTILINE,
)


@dataclass
class Slide:
    index: int
    slide_id: str | None
    classes: list[str]
    title: str | None
    source: str
    visible_text: str
    visible_characters: int
    bullets: int
    table_rows: int
    image_paths: list[str]


@dataclass
class Deck:
    frontmatter: dict[str, Any]
    slides: list[Slide]
    source_path: str


def _mask_preserving_newlines(value: str) -> str:
    return "".join("\n" if character == "\n" else " " for character in value)


def _mask_non_math_regions(source: str) -> str:
    """Hide regions where TeX-looking examples are not rendered as mathematics."""

    masked = COMMENT_RE.sub(lambda match: _mask_preserving_newlines(match.group(0)), source)
    masked = FENCED_CODE_RE.sub(lambda match: _mask_preserving_newlines(match.group(0)), masked)
    return INLINE_CODE_RE.sub(lambda match: _mask_preserving_newlines(match.group(0)), masked)


def _is_unescaped(value: str, position: int) -> bool:
    backslashes = 0
    cursor = position - 1
    while cursor >= 0 and value[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 0


def _mask_tex_text_arguments(value: str) -> str:
    """Mask text/font command arguments while retaining offsets and line numbers."""

    characters = list(value)
    cursor = 0
    while match := TEX_TEXT_ARGUMENT_RE.search(value, cursor):
        opening = match.end() - 1
        depth = 0
        closing: int | None = None
        for index in range(opening, len(value)):
            character = value[index]
            if character == "{" and _is_unescaped(value, index):
                depth += 1
            elif character == "}" and _is_unescaped(value, index):
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing is None:
            cursor = match.end()
            continue
        for index in range(opening + 1, closing):
            if characters[index] != "\n":
                characters[index] = " "
        cursor = closing + 1
    return "".join(characters)


def _bare_tex_control_word_issues(source: str) -> list[dict[str, Any]]:
    """Return likely TeX control words that lost their leading backslash."""

    masked_source = _mask_non_math_regions(source)
    issues: list[dict[str, Any]] = []
    body_groups = ("block_body", "inline_body", "bracket_body", "paren_body")
    for fragment in MATH_FRAGMENT_RE.finditer(masked_source):
        body_group = next(name for name in body_groups if fragment.group(name) is not None)
        body = fragment.group(body_group)
        body_start = fragment.start(body_group)
        scan_body = _mask_tex_text_arguments(body)
        matches = [
            *BARE_TEX_CONTROL_WORD_RE.finditer(scan_body),
            *BARE_TEX_AMBIGUOUS_CONTROL_WORD_RE.finditer(scan_body),
        ]
        for match in sorted(matches, key=lambda item: item.start()):
            source_offset = body_start + match.start()
            line = masked_source.count("\n", 0, source_offset) + 1
            context_start = max(0, match.start() - 28)
            context_end = min(len(body), match.end() + 28)
            context = re.sub(r"\s+", " ", body[context_start:context_end]).strip()
            issues.append(
                {
                    "command": match.group("command"),
                    "slide_line": line,
                    "context": context,
                }
            )
    return issues


def _multiple_choice_audit_errors(
    slide_id: str,
    slide_source: str,
    option_audit: Any,
) -> list[str]:
    """Validate that every visible MCQ option has a structured audit row."""

    errors: list[str] = []
    source_labels = [
        match.group("label") for match in MULTIPLE_CHOICE_OPTION_RE.finditer(slide_source)
    ]
    duplicate_labels = sorted(
        label for label in set(source_labels) if source_labels.count(label) > 1
    )
    if duplicate_labels:
        errors.append(
            f"Multiple-choice slide {slide_id} repeats option labels: "
            + ", ".join(duplicate_labels)
            + "."
        )
    unique_source_labels = list(dict.fromkeys(source_labels))
    if len(unique_source_labels) < 2:
        errors.append(
            f"Multiple-choice slide {slide_id} must expose at least two options using "
            "labels such as `- A. ...` so source lint can inventory them."
        )

    if not isinstance(option_audit, dict) or not option_audit:
        errors.append(
            f"Multiple-choice slide {slide_id} needs option_audit as a non-empty mapping "
            "keyed by the visible option labels."
        )
        return errors

    audit_rows = {str(label).strip().upper(): value for label, value in option_audit.items()}
    audit_labels = list(audit_rows)
    missing = [label for label in unique_source_labels if label not in audit_rows]
    extra = [label for label in audit_labels if label not in unique_source_labels]
    if missing:
        errors.append(
            f"Multiple-choice slide {slide_id} lacks option_audit rows for: "
            + ", ".join(missing)
            + "."
        )
    if extra:
        errors.append(
            f"Multiple-choice slide {slide_id} audits labels absent from the prompt source: "
            + ", ".join(extra)
            + "."
        )

    truth_statuses: list[str] = []
    for label in unique_source_labels:
        audit = audit_rows.get(label)
        if audit is None:
            continue
        if not isinstance(audit, dict):
            errors.append(
                f"Multiple-choice slide {slide_id} option {label} audit must be a mapping."
            )
            continue
        if audit.get("stem_compatible") is not True:
            errors.append(
                f"Multiple-choice slide {slide_id} option {label} must record "
                "stem_compatible: true."
            )
        truth_status = str(audit.get("truth_status") or "").strip()
        truth_statuses.append(truth_status)
        if truth_status not in {"correct", "incorrect"}:
            errors.append(
                f"Multiple-choice slide {slide_id} option {label} truth_status must be "
                "correct or incorrect."
            )
        wording_check = str(audit.get("wording_check") or "").strip()
        if len(wording_check) < 8:
            errors.append(
                f"Multiple-choice slide {slide_id} option {label} needs a substantive "
                "wording_check using the exact mathematical meaning."
            )
        if truth_status == "correct":
            justification = str(audit.get("justification") or "").strip()
            if len(justification) < 8:
                errors.append(
                    f"Multiple-choice slide {slide_id} option {label} needs a substantive "
                    "justification."
                )
        elif truth_status == "incorrect":
            misconception = str(audit.get("misconception") or "").strip()
            if len(misconception) < 8:
                errors.append(
                    f"Multiple-choice slide {slide_id} option {label} needs a substantive "
                    "misconception description."
                )
    if unique_source_labels and "correct" not in truth_statuses:
        errors.append(f"Multiple-choice slide {slide_id} has no audited correct option.")
    if unique_source_labels and "incorrect" not in truth_statuses:
        errors.append(f"Multiple-choice slide {slide_id} has no audited distractor.")
    return errors


def _split_frontmatter(lines: list[str]) -> tuple[dict[str, Any], list[str]]:
    if not lines or lines[0].strip() != "---":
        raise MPresError("Canonical Marp source must begin with YAML frontmatter.")
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        raise MPresError("Marp YAML frontmatter is not closed.")
    import yaml

    try:
        value = yaml.safe_load("".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise MPresError(f"Invalid Marp YAML frontmatter: {exc}") from exc
    if not isinstance(value, dict):
        raise MPresError("Marp YAML frontmatter must be a mapping.")
    return value, lines[end + 1 :]


def _split_slides(lines: list[str]) -> list[str]:
    slides: list[list[str]] = [[]]
    fence_marker: str | None = None
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence_marker is None:
                fence_marker = marker
            elif marker == fence_marker:
                fence_marker = None
            slides[-1].append(line)
            continue
        if fence_marker is None and line.strip() == "---":
            slides.append([])
        else:
            slides[-1].append(line)
    return ["".join(chunk).strip() for chunk in slides if "".join(chunk).strip()]


def _visible_text(source: str) -> str:
    text = COMMENT_RE.sub(" ", source)
    text = MARKDOWN_IMAGE_RE.sub(" ", text)
    text = HTML_IMAGE_RE.sub(" ", text)
    text = MATH_BLOCK_RE.sub(" MATH ", text)
    text = INLINE_MATH_RE.sub(" MATH ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"~~~.*?~~~", " ", text, flags=re.DOTALL)
    text = re.sub(r"[#>*_`|\[\]()]+", " ", text)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text


def _table_rows(source: str) -> int:
    count = 0
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3:
            if re.fullmatch(r"[|:\-\s]+", stripped):
                continue
            count += 1
    return count


def _image_paths(source: str) -> list[str]:
    values = [*MARKDOWN_IMAGE_RE.findall(source), *HTML_IMAGE_RE.findall(source)]
    result: list[str] = []
    for value in values:
        cleaned = value.strip().strip("<>")
        if " " in cleaned and not cleaned.startswith(("data:", "http://", "https://", "//")):
            cleaned = cleaned.split()[0]
        result.append(unquote(cleaned))
    return result


def parse_deck(path: Path) -> Deck:
    path = path.resolve()
    text = path.read_text(encoding="utf-8")
    frontmatter, body_lines = _split_frontmatter(text.splitlines(keepends=True))
    raw_slides = _split_slides(body_lines)
    slides: list[Slide] = []
    for index, source in enumerate(raw_slides, start=1):
        slide_id_match = SLIDE_ID_RE.search(source)
        class_match = CLASS_RE.search(source)
        heading_match = HEADING_RE.search(source)
        visible = _visible_text(source)
        classes = class_match.group(1).split() if class_match else []
        slides.append(
            Slide(
                index=index,
                slide_id=slide_id_match.group(1).strip() if slide_id_match else None,
                classes=classes,
                title=heading_match.group(1).strip() if heading_match else None,
                source=source,
                visible_text=visible,
                visible_characters=len(visible),
                bullets=len(BULLET_RE.findall(source)),
                table_rows=_table_rows(source),
                image_paths=_image_paths(source),
            )
        )
    if not slides:
        raise MPresError("Marp source contains no slides.")
    return Deck(frontmatter=frontmatter, slides=slides, source_path=str(path))


def _manifest_check(
    source_root: Path, deck: Deck, *, policy: dict[str, Any] | None = None
) -> dict[str, Any]:
    manifest_path = source_root / "DECK-MANIFEST.yaml"
    errors: list[str] = []
    warnings: list[str] = []
    if not manifest_path.is_file():
        return {"ok": False, "errors": ["DECK-MANIFEST.yaml is missing."], "warnings": []}
    manifest = read_yaml(manifest_path)
    if not isinstance(manifest, dict):
        return {"ok": False, "errors": ["DECK-MANIFEST.yaml must be a mapping."], "warnings": []}
    rows = manifest.get("slides") or []
    if not isinstance(rows, list):
        errors.append("DECK-MANIFEST.yaml slides must be a list.")
        rows = []
    manifest_ids = [
        str(item.get("id")) for item in rows if isinstance(item, dict) and item.get("id")
    ]
    source_ids = [slide.slide_id for slide in deck.slides if slide.slide_id]
    missing_manifest = sorted(set(source_ids) - set(manifest_ids))
    missing_source = sorted(set(manifest_ids) - set(source_ids))
    if missing_manifest:
        errors.append("Slides missing from manifest: " + ", ".join(missing_manifest[:12]))
    if missing_source:
        errors.append("Manifest IDs missing from source: " + ", ".join(missing_source[:12]))
    kinds = [item.get("kind") for item in rows if isinstance(item, dict)]
    invalid_kinds = sorted({str(kind) for kind in kinds if kind not in {"core", "support"}})
    if invalid_kinds:
        errors.append("Invalid slide kinds: " + ", ".join(invalid_kinds))

    row_by_id = {
        str(item.get("id")): item
        for item in rows
        if isinstance(item, dict) and item.get("id")
    }
    slide_by_id = {slide.slide_id: slide for slide in deck.slides if slide.slide_id}
    interaction_pairs: list[dict[str, str]] = []
    for slide in deck.slides:
        if not slide.slide_id:
            continue
        row = row_by_id.get(slide.slide_id) or {}
        role = str(row.get("interaction_role") or "").strip()
        interaction_format = str(row.get("interaction_format") or "").strip()
        if role and role not in INTERACTION_ROLES and role != "none":
            errors.append(f"Slide {slide.slide_id} has invalid interaction_role {role!r}.")
        if EXERCISE_TITLE_RE.search(slide.title or "") and role not in INTERACTION_ROLES:
            errors.append(
                f"Exercise-like slide {slide.slide_id} must declare interaction_role as "
                "exercise_prompt, exercise_hint, or exercise_answer."
            )
        if interaction_format == "multiple_choice":
            rationale = str(row.get("selection_rationale") or "").strip()
            if role != "exercise_prompt":
                errors.append(
                    f"Multiple-choice slide {slide.slide_id} must be an exercise_prompt."
                )
            if rationale not in MULTIPLE_CHOICE_RATIONALES:
                errors.append(
                    f"Multiple-choice slide {slide.slide_id} must use one of the approved "
                    f"selection rationales: {', '.join(sorted(MULTIPLE_CHOICE_RATIONALES))}."
                )
            errors.extend(
                _multiple_choice_audit_errors(
                    slide.slide_id,
                    slide.source,
                    row.get("option_audit"),
                )
            )
        if role == "exercise_prompt":
            paired_with = str(row.get("paired_with") or "").strip()
            if str(row.get("kind") or "") != "core":
                errors.append(f"Exercise prompt {slide.slide_id} must be a core slide.")
            if EXERCISE_RESPONSE_MARKER_RE.search(slide.source):
                errors.append(
                    f"Exercise prompt {slide.slide_id} contains an answer/solution marker; "
                    "move the response to the paired support slide."
                )
            if not paired_with:
                errors.append(f"Exercise prompt {slide.slide_id} must declare paired_with.")
                continue
            response_row = row_by_id.get(paired_with)
            response_slide = slide_by_id.get(paired_with)
            if response_row is None or response_slide is None:
                errors.append(
                    f"Exercise prompt {slide.slide_id} references missing response {paired_with}."
                )
                continue
            response_role = str(response_row.get("interaction_role") or "").strip()
            if response_role not in {"exercise_hint", "exercise_answer"}:
                errors.append(
                    f"Exercise prompt {slide.slide_id} must pair with a hint/answer slide, "
                    f"not {response_role or 'an untyped slide'}."
                )
            if str(response_row.get("kind") or "") != "support":
                errors.append(f"Exercise response {paired_with} must be a support slide.")
            if str(response_row.get("paired_with") or "").strip() != slide.slide_id:
                errors.append(
                    f"Exercise pair {slide.slide_id} -> {paired_with} must be reciprocal."
                )
            if response_slide.index != slide.index + 1:
                errors.append(
                    f"Exercise response {paired_with} must immediately follow prompt "
                    f"{slide.slide_id} in PDF page order."
                )
            interaction_pairs.append(
                {
                    "prompt": slide.slide_id,
                    "response": paired_with,
                    "response_role": response_role,
                }
            )
        elif role in {"exercise_hint", "exercise_answer"}:
            paired_with = str(row.get("paired_with") or "").strip()
            prompt_row = row_by_id.get(paired_with)
            if not paired_with or prompt_row is None:
                errors.append(f"Exercise response {slide.slide_id} must reference its prompt.")
            elif str(prompt_row.get("interaction_role") or "").strip() != "exercise_prompt":
                errors.append(
                    f"Exercise response {slide.slide_id} does not reference an exercise_prompt."
                )
    task_kind = str((policy or {}).get("task_kind") or "").strip()
    interaction_contract = validate_presentation_interactions(
        source_root,
        [item for item in rows if isinstance(item, dict)],
        task_kind=task_kind,
    )
    errors.extend(interaction_contract["errors"])
    warnings.extend(interaction_contract["warnings"])
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "manifest_slide_count": len(manifest_ids),
        "source_slide_count": len(source_ids),
        "core_count": sum(kind == "core" for kind in kinds),
        "support_count": sum(kind == "support" for kind in kinds),
        "interaction_pairs": interaction_pairs,
        "interaction_contract": interaction_contract,
    }


def lint_deck(
    source_root: Path,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    deck_path = source_root / "presentation.md"
    if not deck_path.is_file():
        raise MPresError(f"Canonical Marp source is missing: {deck_path}")
    deck = parse_deck(deck_path)
    errors: list[str] = []
    warnings: list[str] = []
    front = deck.frontmatter
    required = {
        "marp": True,
        "theme": "mathist-academic",
        "paginate": True,
        "size": "16:9",
        "math": "mathjax",
    }
    for key, expected in required.items():
        if front.get(key) != expected:
            errors.append(f"Frontmatter {key!r} must be {expected!r}, got {front.get(key)!r}.")
    if "style" in front:
        errors.append("Inline frontmatter CSS is forbidden; use theme.css.")

    limits = (policy or {}).get("source_limits", {}) if isinstance(policy, dict) else {}
    warning_chars = int(limits.get("warning_visible_characters_per_slide", 650) or 650)
    error_chars = int(limits.get("error_visible_characters_per_slide", 1000) or 1000)
    warning_bullets = int(limits.get("warning_bullets_per_slide", 7) or 7)
    warning_rows = int(limits.get("warning_table_rows_per_slide", 9) or 9)

    ids: list[str] = []
    slide_reports: list[dict[str, Any]] = []
    tex_control_word_issues: list[dict[str, Any]] = []
    for slide in deck.slides:
        slide_errors: list[str] = []
        slide_warnings: list[str] = []
        slide_tex_issues: list[dict[str, Any]] = []
        if not slide.slide_id:
            slide_errors.append("Missing <!-- slide-id: ... -->.")
        else:
            ids.append(slide.slide_id)
        if not ({"core", "support"} & set(slide.classes)):
            slide_errors.append("Slide class must include core or support.")
        if slide.visible_characters > error_chars:
            slide_errors.append(
                "Visible text is too dense "
                f"({slide.visible_characters} characters > {error_chars})."
            )
        elif slide.visible_characters > warning_chars:
            slide_warnings.append(
                f"Visible text is dense ({slide.visible_characters} characters > {warning_chars})."
            )
        if slide.bullets > warning_bullets:
            slide_warnings.append(f"Slide has {slide.bullets} bullet/list items.")
        if slide.table_rows > warning_rows:
            slide_warnings.append(f"Slide table has {slide.table_rows} content rows.")
        if re.search(r"<\s*(?:script|iframe|object|embed)\b", slide.source, re.IGNORECASE):
            slide_errors.append("Executable or embedded HTML elements are forbidden.")
        if "<style" in slide.source.lower():
            slide_errors.append("Per-slide <style> blocks are forbidden; use theme.css.")
        for issue in _bare_tex_control_word_issues(slide.source):
            recorded = {
                "slide": slide.index,
                "slide_id": slide.slide_id,
                **issue,
            }
            slide_tex_issues.append(recorded)
            tex_control_word_issues.append(recorded)
            slide_errors.append(
                f"Bare TeX control word {issue['command']!r} in math at source line "
                f"{issue['slide_line']}; add the leading backslash or rewrite the notation. "
                f"Context: {issue['context']}"
            )
        for ref in slide.image_paths:
            if REMOTE_RE.match(ref) or ref.lower().startswith("data:"):
                slide_errors.append(f"Remote or embedded image is forbidden: {ref}")
                continue
            candidate = (source_root / ref).resolve()
            try:
                candidate.relative_to(source_root)
            except ValueError:
                slide_errors.append(f"Image path escapes source tree: {ref}")
                continue
            if not candidate.is_file():
                slide_errors.append(f"Referenced image is missing: {ref}")
        errors.extend(
            f"slide {slide.index} ({slide.slide_id or 'no-id'}): {msg}"
            for msg in slide_errors
        )
        warnings.extend(
            f"slide {slide.index} ({slide.slide_id or 'no-id'}): {msg}" for msg in slide_warnings
        )
        slide_reports.append(
            {
                **asdict(slide),
                "source": None,
                "tex_control_word_issues": slide_tex_issues,
                "errors": slide_errors,
                "warnings": slide_warnings,
            }
        )
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        errors.append("Duplicate slide IDs: " + ", ".join(duplicates))
    manifest = _manifest_check(source_root, deck, policy=policy)
    errors.extend(manifest["errors"])
    warnings.extend(manifest["warnings"])
    geogebra = validate_presentation_geogebra_registry(
        source_root,
        deck_path.read_text(encoding="utf-8"),
        maximum_selected_per_unit=int(
            (((policy or {}).get("online_resources") or {}).get("geogebra") or {}).get(
                "max_selected_links_per_unit", 3
            )
            or 3
        ),
    )
    errors.extend(geogebra["errors"])
    warnings.extend(geogebra["warnings"])
    interactions = manifest.get("interaction_contract", {})
    theme = source_root / "theme.css"
    if not theme.is_file():
        errors.append("theme.css is missing.")
    else:
        theme_text = theme.read_text(encoding="utf-8", errors="replace")
        if "@theme mathist-academic" not in theme_text:
            errors.append("theme.css does not declare @theme mathist-academic.")
        if re.search(r"font-size\s*:\s*(?:[0-9]|1[0-5])px", theme_text, re.IGNORECASE):
            warnings.append(
                "theme.css contains a font size below 16px; verify it is not student text."
            )
    return {
        "schema_version": 1,
        "source": str(deck_path),
        "frontmatter": deck.frontmatter,
        "slide_count": len(deck.slides),
        "slides": slide_reports,
        "tex_control_word_issues": tex_control_word_issues,
        "manifest": manifest,
        "geogebra": geogebra,
        "interactions": interactions,
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
    }


def lint_task_source(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    stage: str = "author",
) -> dict[str, Any]:
    task = task_path(root, slug)
    if stage == "author":
        base = task / "workers" / "author-coordinator" / "drafts" / presentation_id
    elif stage == "release":
        base = task / "workers" / "release-coordinator" / "release-ready" / presentation_id
    else:
        raise MPresError("Source-lint stage must be author or release.")
    policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    report = lint_deck(base / "source", policy=policy)
    report_path = base / "build" / f"source-lint-{stage}.json"
    write_json_atomic(report_path, report)
    report["report_path"] = relative_display(report_path, root)
    return report
