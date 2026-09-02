from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from mpres.state import get_presentation, load_state
from mpres.util import MPresError, read_yaml, relative_display, task_path, write_json_atomic
from mpres.control_jobs import release_workspace

ALLOWED_HOSTS = {"geogebra.org", "www.geogebra.org"}
RESOURCE_PATH_RE = re.compile(r"^/m/[A-Za-z0-9_-]+/?$")
MARKDOWN_LINK_RE = re.compile(
    r"(?<!!)\[([^\]]+)\]\(\s*(https?://[^\s)]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)",
    re.IGNORECASE,
)
MARKDOWN_IMAGE_LINK_RE = re.compile(
    r"\[!\[[^\]]*\]\([^)]+\)\]\(\s*(https?://[^\s)]+)[^)]*\)",
    re.IGNORECASE,
)
AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>", re.IGNORECASE)
HTML_ANCHOR_RE = re.compile(
    r"<a\b[^>]*\bhref=[\"'](https?://[^\"']+)[\"'][^>]*>.*?</a>",
    re.IGNORECASE | re.DOTALL,
)
ALL_URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.IGNORECASE)
EMBED_RE = re.compile(
    r"<(?:iframe|object|embed|script)\b[^>]*geogebra\.org|"
    r"(?:GGBApplet|deployggb|material_id|ggbBase64)",
    re.IGNORECASE,
)
GENERIC_LABELS = {
    "geogebra",
    "link",
    "here",
    "click here",
    "链接",
    "这里",
    "点击",
    "点击这里",
}
SEARCH_OUTCOMES = {"found_selected", "searched_no_suitable_resource", "not_applicable"}


def _normalise_url(value: str) -> str:
    value = value.strip().rstrip(".,;:!?，。；：！？")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    return urlunsplit((parsed.scheme.lower(), host, parsed.path.rstrip("/"), "", parsed.fragment))


def _is_geogebra_url(value: str) -> bool:
    try:
        return (urlsplit(value).hostname or "").lower() in ALLOWED_HOSTS
    except ValueError:
        return False


def _validate_url(value: str) -> tuple[str, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        return value, [f"Invalid GeoGebra URL: {exc}"], warnings
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https":
        errors.append("GeoGebra URL must use https.")
    if host not in ALLOWED_HOSTS:
        errors.append("GeoGebra URL must use geogebra.org or www.geogebra.org exactly.")
    if parsed.username or parsed.password or parsed.port:
        errors.append("GeoGebra URL may not contain credentials or a custom port.")
    if not RESOURCE_PATH_RE.fullmatch(parsed.path.rstrip("/") or "/"):
        errors.append("GeoGebra link must target a specific public resource under /m/<resource-id>.")
    if parsed.query:
        warnings.append("GeoGebra URL contains a query string; use the canonical resource URL.")
    return _normalise_url(value), errors, warnings


def _markdown_links(text: str) -> tuple[list[dict[str, str]], list[str], list[str]]:
    links: list[dict[str, str]] = []
    errors: list[str] = []
    warnings: list[str] = []
    recognised: list[tuple[int, int]] = []
    for match in MARKDOWN_IMAGE_LINK_RE.finditer(text):
        if _is_geogebra_url(match.group(1)):
            errors.append("GeoGebra may not be linked through an image; use labelled text only.")
        recognised.append(match.span())
    for match in MARKDOWN_LINK_RE.finditer(text):
        url = match.group(2)
        label = re.sub(r"\s+", " ", match.group(1)).strip()
        if not _is_geogebra_url(url):
            if "geogebra" in label.lower() or "geogebra" in url.lower():
                errors.append(
                    "A link presented as a GeoGebra resource must point directly to geogebra.org."
                )
            continue
        recognised.append(match.span())
        normalised, url_errors, url_warnings = _validate_url(url)
        errors.extend(url_errors)
        warnings.extend(url_warnings)
        if len(label) < 5 or label.lower() in GENERIC_LABELS or label == url:
            warnings.append(
                "GeoGebra link label should tell the learner what to manipulate or observe."
            )
        links.append({"label": label, "url": normalised})
    for match in AUTOLINK_RE.finditer(text):
        if _is_geogebra_url(match.group(1)):
            recognised.append(match.span())
            errors.append("GeoGebra autolinks are forbidden; use a labelled Markdown hyperlink.")
    for match in HTML_ANCHOR_RE.finditer(text):
        if _is_geogebra_url(match.group(1)):
            recognised.append(match.span())
            errors.append("GeoGebra links must use ordinary Markdown syntax, not HTML anchors.")
    for match in ALL_URL_RE.finditer(text):
        if not _is_geogebra_url(match.group(0)):
            continue
        if not any(start <= match.start() and match.end() <= end for start, end in recognised):
            errors.append("Bare GeoGebra URLs are forbidden; use a labelled Markdown hyperlink.")
    if EMBED_RE.search(text):
        errors.append("GeoGebra embedding, applet scripts, and embed endpoints are forbidden.")
    return links, errors, warnings


def _selected_resources(value: dict[str, Any]) -> list[dict[str, Any]]:
    resources = value.get("selected_resources") or []
    if not isinstance(resources, list):
        raise MPresError("selected_resources must be a list.")
    if any(not isinstance(item, dict) for item in resources):
        raise MPresError("Every selected GeoGebra resource must be a mapping.")
    return list(resources)


def _valid_checked_utc(value: Any) -> bool:
    text = str(value or "").strip()
    if not text.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def validate_unit_geogebra_registry(
    registry_path: Path,
    section_path: Path,
    *,
    maximum_queries: int = 3,
    maximum_selected: int = 3,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not registry_path.is_file():
        return {"success": False, "errors": [f"Missing {registry_path}"], "warnings": []}
    if not section_path.is_file():
        return {"success": False, "errors": [f"Missing {section_path}"], "warnings": []}
    value = read_yaml(registry_path)
    if not isinstance(value, dict):
        return {"success": False, "errors": ["GeoGebra unit record must be a mapping."], "warnings": []}
    for field in ("presentation_id", "unit_id"):
        if not str(value.get(field, "")).strip():
            errors.append(f"GeoGebra unit record is missing {field}.")
    if str(value.get("site_scope", "")) != "geogebra.org":
        errors.append("GeoGebra site_scope must be geogebra.org.")
    relevant = value.get("relevant")
    attempted = value.get("search_attempted")
    if not isinstance(relevant, bool):
        errors.append("GeoGebra relevant must be true or false.")
    if not isinstance(attempted, bool):
        errors.append("GeoGebra search_attempted must be true or false.")
    rationale = str(value.get("rationale", "")).strip()
    if len(rationale) < 12:
        errors.append("GeoGebra relevance decision needs a short instructional rationale.")
    outcome = str(value.get("search_outcome", "")).strip()
    if outcome not in SEARCH_OUTCOMES:
        errors.append(
            "GeoGebra search_outcome must be found_selected, "
            "searched_no_suitable_resource, or not_applicable."
        )
    queries = value.get("search_queries") or []
    if not isinstance(queries, list):
        errors.append("GeoGebra search_queries must be a list.")
        queries = []
    if len(queries) > maximum_queries:
        errors.append(f"GeoGebra search exceeds the limit of {maximum_queries} queries.")
    for query in queries:
        if not isinstance(query, str) or not query.strip():
            errors.append("Every GeoGebra search query must be a non-empty string.")
        elif "site:geogebra.org" not in query.lower():
            errors.append(
                "Every GeoGebra web search query must explicitly use site:geogebra.org."
            )
    if relevant is False:
        if outcome != "not_applicable":
            errors.append("A non-relevant GeoGebra unit must use search_outcome: not_applicable.")
        if attempted is True or queries:
            warnings.append(
                "Unit is marked not relevant but records a search; prefer deciding relevance first."
            )
    elif relevant is True and attempted is not True:
        errors.append("A relevant GeoGebra unit must record a bounded search attempt.")
    elif relevant is True and outcome == "not_applicable":
        errors.append("A relevant GeoGebra unit may not use search_outcome: not_applicable.")
    if attempted is True and not queries:
        errors.append("A GeoGebra search attempt must record at least one query.")

    try:
        selected = _selected_resources(value)
    except MPresError as exc:
        errors.append(str(exc))
        selected = []
    if len(selected) > maximum_selected:
        errors.append(f"GeoGebra unit selects more than {maximum_selected} resources.")
    selected_by_url: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        embedded = item.get("embedded")
        if embedded is not False:
            errors.append("Every selected GeoGebra resource must declare embedded: false.")
        for field in (
            "title",
            "url",
            "author",
            "verification_status",
            "verified_title",
            "verified_author",
            "verified_activity",
            "verified_utc",
            "concept",
            "intended_use",
            "link_text",
        ):
            if not str(item.get(field, "")).strip():
                errors.append(f"Selected GeoGebra resource is missing {field}.")
        if item.get("verification_status") != "verified":
            errors.append(
                "A selected GeoGebra resource must use verification_status: verified."
            )
        if item.get("verified_utc") and not _valid_checked_utc(item.get("verified_utc")):
            errors.append("GeoGebra verified_utc must be an ISO-8601 UTC timestamp ending in Z.")
        if "verified_resource" in item:
            errors.append(
                "Legacy verified_resource is not accepted; use verification_status: verified."
            )
        normalised, url_errors, url_warnings = _validate_url(str(item.get("url", "")))
        errors.extend(url_errors)
        warnings.extend(url_warnings)
        selected_by_url.setdefault(normalised, []).append(item)
        if str(item.get("link_text", "")).strip().lower() in GENERIC_LABELS:
            warnings.append("GeoGebra link_text should describe the intended learner action.")
    if selected and (relevant is not True or attempted is not True):
        errors.append("Selected GeoGebra resources require relevant: true and search_attempted: true.")
    if selected and outcome != "found_selected":
        errors.append("Selected GeoGebra resources require search_outcome: found_selected.")
    if not selected and outcome == "found_selected":
        errors.append("search_outcome: found_selected requires at least one selected resource.")

    links, link_errors, link_warnings = _markdown_links(section_path.read_text(encoding="utf-8"))
    errors.extend(link_errors)
    warnings.extend(link_warnings)
    source_by_url: dict[str, list[dict[str, str]]] = {}
    for link in links:
        source_by_url.setdefault(link["url"], []).append(link)
    missing_registry = sorted(set(source_by_url) - set(selected_by_url))
    missing_source = sorted(set(selected_by_url) - set(source_by_url))
    if missing_registry:
        errors.append("GeoGebra link is not selected in its registry: " + ", ".join(missing_registry))
    if missing_source:
        errors.append("Selected GeoGebra resources are not linked in section.md: " + ", ".join(missing_source))
    for url in sorted(set(source_by_url) & set(selected_by_url)):
        source_labels = {item["label"] for item in source_by_url[url]}
        registered_labels = {
            str(item.get("link_text", "")).strip() for item in selected_by_url[url]
        }
        if not source_labels <= registered_labels:
            errors.append(f"GeoGebra link text does not match any registry entry for {url}.")
    return {
        "schema_version": 1,
        "registry": str(registry_path),
        "section": str(section_path),
        "relevant": relevant,
        "search_attempted": attempted,
        "query_count": len(queries),
        "selected_count": len(selected),
        "links": links,
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
    }


def aggregate_unit_geogebra_records(
    unit_records: list[dict[str, Any]],
    *,
    presentation_id: str,
) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in unit_records:
        if not isinstance(record, dict):
            raise MPresError("Every GeoGebra unit record must be a mapping.")
        unit_id = str(record.get("unit_id", "")).strip()
        if not unit_id:
            raise MPresError("GeoGebra unit record is missing unit_id.")
        if unit_id in seen:
            raise MPresError(f"Duplicate GeoGebra unit record: {unit_id}")
        seen.add(unit_id)
        if record.get("presentation_id") != presentation_id:
            raise MPresError(f"GeoGebra unit {unit_id} belongs to another presentation.")
        units.append(record)
    return {
        "schema_version": 1,
        "presentation_id": presentation_id,
        "policy": {
            "site_scope": "geogebra.org",
            "usage": "markdown-hyperlinks-only",
            "embedding": "forbidden",
            "download": "forbidden",
            "essential_content_dependency": "forbidden",
        },
        "units": units,
    }


def validate_presentation_geogebra_registry(
    source_root: Path,
    presentation_text: str,
    *,
    maximum_selected_per_unit: int = 3,
) -> dict[str, Any]:
    registry_path = source_root / "GEOGEBRA-RESOURCES.yaml"
    errors: list[str] = []
    warnings: list[str] = []
    if not registry_path.is_file():
        return {
            "success": False,
            "errors": ["GEOGEBRA-RESOURCES.yaml is missing."],
            "warnings": [],
        }
    registry = read_yaml(registry_path)
    if not isinstance(registry, dict):
        return {
            "success": False,
            "errors": ["GEOGEBRA-RESOURCES.yaml must be a mapping."],
            "warnings": [],
        }
    policy = registry.get("policy") or {}
    if not isinstance(policy, dict):
        errors.append("GeoGebra aggregate policy must be a mapping.")
        policy = {}
    if policy.get("site_scope") != "geogebra.org":
        errors.append("GeoGebra aggregate policy site_scope must be geogebra.org.")
    if policy.get("usage") != "markdown-hyperlinks-only":
        errors.append("GeoGebra aggregate policy usage must be markdown-hyperlinks-only.")
    if policy.get("embedding") != "forbidden":
        errors.append("GeoGebra aggregate policy embedding must be forbidden.")
    units = registry.get("units") or []
    if not isinstance(units, list):
        errors.append("GeoGebra aggregate units must be a list.")
        units = []
    selected_by_url: dict[str, list[dict[str, Any]]] = {}
    selected_count_by_unit: dict[str, int] = {}
    for unit in units:
        if not isinstance(unit, dict):
            errors.append("Every GeoGebra aggregate unit must be a mapping.")
            continue
        unit_id = str(unit.get("unit_id", "")).strip()
        resources = unit.get("selected_resources") or []
        if not isinstance(resources, list):
            errors.append(f"GeoGebra selected_resources for {unit_id} must be a list.")
            continue
        selected_count_by_unit[unit_id] = len(resources)
        if len(resources) > maximum_selected_per_unit:
            errors.append(
                f"GeoGebra unit {unit_id} exceeds {maximum_selected_per_unit} selected links."
            )
        for resource in resources:
            if not isinstance(resource, dict):
                errors.append(f"GeoGebra selected resource in {unit_id} must be a mapping.")
                continue
            normalised, url_errors, url_warnings = _validate_url(str(resource.get("url", "")))
            errors.extend(url_errors)
            warnings.extend(url_warnings)
            if resource.get("embedded") is not False:
                errors.append(f"GeoGebra resource {normalised} does not declare embedded: false.")
            if resource.get("verification_status") != "verified":
                errors.append(
                    f"GeoGebra resource {normalised} is selected without verification_status: verified."
                )
            for field in ("verified_title", "verified_author", "verified_activity", "verified_utc"):
                if not str(resource.get(field, "")).strip():
                    errors.append(f"GeoGebra resource {normalised} is missing {field}.")
            if resource.get("verified_utc") and not _valid_checked_utc(resource.get("verified_utc")):
                errors.append(f"GeoGebra resource {normalised} has an invalid verified_utc.")
            selected_by_url.setdefault(normalised, []).append(resource)
    links, link_errors, link_warnings = _markdown_links(presentation_text)
    errors.extend(link_errors)
    warnings.extend(link_warnings)
    source_by_url: dict[str, list[dict[str, str]]] = {}
    for link in links:
        source_by_url.setdefault(link["url"], []).append(link)
    unregistered = sorted(set(source_by_url) - set(selected_by_url))
    unlinked = sorted(set(selected_by_url) - set(source_by_url))
    if unregistered:
        errors.append("GeoGebra link is not selected in its registry: " + ", ".join(unregistered))
    if unlinked:
        errors.append("Registered GeoGebra resources are not linked in presentation.md: " + ", ".join(unlinked))
    for url in sorted(set(source_by_url) & set(selected_by_url)):
        source_labels = {item["label"] for item in source_by_url[url]}
        registered_labels = {
            str(item.get("link_text", "")).strip() for item in selected_by_url[url]
        }
        if not source_labels <= registered_labels:
            errors.append(f"GeoGebra link text does not match any registry entry for {url}.")
    return {
        "schema_version": 1,
        "registry": str(registry_path),
        "registered_link_occurrences": sum(len(items) for items in selected_by_url.values()),
        "registered_unique_urls": len(selected_by_url),
        "source_links": links,
        "selected_count_by_unit": selected_count_by_unit,
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
    }


def validate_task_geogebra(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    stage: str = "author",
) -> dict[str, Any]:
    task = task_path(root, slug)
    if stage == "author":
        state = load_state(root, slug)
        presentation = get_presentation(state, presentation_id)
        role = (
            "deck-revision-author"
            if presentation.get("status") == "author_revision"
            else "author-coordinator"
        )
        base = task / "workers" / role / "drafts" / presentation_id
    elif stage == "release":
        base = release_workspace(root, slug, presentation_id)
    else:
        raise MPresError("GeoGebra validation stage must be author or release.")
    source = base / "source"
    presentation = source / "presentation.md"
    if not presentation.is_file():
        raise MPresError(f"Canonical Marp source is missing: {presentation}")
    task_policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    online = task_policy.get("online_resources", {}) if isinstance(task_policy, dict) else {}
    geogebra_policy = online.get("geogebra", {}) if isinstance(online, dict) else {}
    report = validate_presentation_geogebra_registry(
        source,
        presentation.read_text(encoding="utf-8"),
        maximum_selected_per_unit=int(geogebra_policy.get("max_selected_links_per_unit", 3) or 3),
    )
    report_path = base / "build" / f"geogebra-validation-{stage}.json"
    write_json_atomic(report_path, report)
    report["report_path"] = relative_display(report_path, root)
    return report
