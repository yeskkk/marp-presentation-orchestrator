from __future__ import annotations

import mimetypes
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from mpres.browser import browser_launch_options
from mpres.util import MPresError, copy_source_tree, executable, local_marp_binary, run_command

SYNTHETIC_ORIGIN = "http://mpres.invalid"
SLIDE_SELECTOR = (
    "section[data-marpit-scope], .marpit > section, "
    "svg[data-marpit-svg] > foreignObject > section, svg[data-marpit-svg] section"
)


def _marp_html_command(root: Path, source: Path, output: Path, policy: dict[str, Any]) -> list[str]:
    binary = local_marp_binary(root)
    if binary is None:
        raise MPresError("Marp CLI is not installed.")
    if binary.suffix.lower() == ".js":
        command = [executable("node") or "node", str(binary)]
    else:
        command = [str(binary)]
    command.extend(
        [
            str(source / "presentation.md"),
            "--allow-local-files",
            "--html",
            "--theme-set",
            str(source / "theme.css"),
            "--output",
            str(output),
        ]
    )
    browser = str(((policy.get("marp") or {}).get("browser", "auto")) or "auto")
    if browser != "auto":
        command.extend(["--browser", browser])
    return command


_LAYOUT_SCRIPT = r"""
() => {
  const candidates = [
    ...document.querySelectorAll('section[data-marpit-scope]'),
    ...document.querySelectorAll('.marpit > section'),
    ...document.querySelectorAll('svg[data-marpit-svg] > foreignObject > section'),
    ...document.querySelectorAll('svg[data-marpit-svg] section')
  ];
  const slides = [...new Set(candidates)];
  function stableSlideId(slide, index) {
    const walker = document.createTreeWalker(slide, NodeFilter.SHOW_COMMENT);
    let node;
    while ((node = walker.nextNode())) {
      const match = String(node.nodeValue || '').match(/slide-id:\s*([^\s]+)/i);
      if (match) return match[1];
    }
    return slide.id || `slide-${index + 1}`;
  }
  return slides.map((slide, index) => {
    const style = getComputedStyle(slide);
    const tolerance = 1;
    const overflowX = Math.max(0, slide.scrollWidth - slide.clientWidth);
    const overflowY = Math.max(0, slide.scrollHeight - slide.clientHeight);
    const slideRect = slide.getBoundingClientRect();
    const outOfBounds = [];
    for (const child of Array.from(slide.children)) {
      const childStyle = getComputedStyle(child);
      if (childStyle.display === 'none' || childStyle.visibility === 'hidden') continue;
      const rect = child.getBoundingClientRect();
      const outside = {
        left: Math.max(0, slideRect.left - rect.left),
        top: Math.max(0, slideRect.top - rect.top),
        right: Math.max(0, rect.right - slideRect.right),
        bottom: Math.max(0, rect.bottom - slideRect.bottom)
      };
      if (Math.max(outside.left, outside.top, outside.right, outside.bottom) > tolerance) {
        outOfBounds.push({
          tag: child.tagName,
          id: child.id || null,
          className: String(child.className || ''),
          outside
        });
      }
    }
    return {
      index: index + 1,
      id: stableSlideId(slide, index),
      clientWidth: slide.clientWidth,
      clientHeight: slide.clientHeight,
      scrollWidth: slide.scrollWidth,
      scrollHeight: slide.scrollHeight,
      computedWidth: style.width,
      computedHeight: style.height,
      overflowX,
      overflowY,
      outOfBounds,
      overflow: overflowX > tolerance || overflowY > tolerance || outOfBounds.length > 0,
      textLength: (slide.innerText || '').trim().length
    };
  });
}
"""


def _inspect_with_playwright(html_path: Path, asset_root: Path, *, timeout: int) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise MPresError(
            "Playwright is unavailable. Re-run bootstrap or install the playwright package."
        ) from exc

    timeout_ms = max(1, timeout) * 1000
    page_errors: list[str] = []
    failed_requests: list[dict[str, str]] = []
    blocked_external_requests: list[str] = []
    console_messages: list[dict[str, str]] = []
    html_text = html_path.read_text(encoding="utf-8", errors="replace")
    base_tag = '<base href="http://mpres.invalid/">'
    lowered = html_text.lower()
    head_index = lowered.find("<head")
    if head_index >= 0:
        head_close = lowered.find(">", head_index)
        if head_close >= 0:
            html_text = html_text[: head_close + 1] + base_tag + html_text[head_close + 1 :]
        else:
            html_text = base_tag + html_text
    else:
        html_text = base_tag + html_text

    def local_file_for(url: str) -> Path | None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != "mpres.invalid":
            return None
        relative = unquote(parsed.path.lstrip("/"))
        candidate = (asset_root / relative).resolve()
        try:
            candidate.relative_to(asset_root.resolve())
        except ValueError:
            return None
        return candidate

    try:
        with sync_playwright() as playwright:
            options, executable, source = browser_launch_options(playwright)
            browser = playwright.chromium.launch(**options)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 900})
                page = context.new_page()
                readiness_timeout_ms = min(timeout_ms, 10000)
                page.set_default_timeout(readiness_timeout_ms)
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.on(
                    "requestfailed",
                    lambda request: failed_requests.append(
                        {"url": request.url, "failure": request.failure or "unknown"}
                    ),
                )
                page.on(
                    "console",
                    lambda message: console_messages.append(
                        {"type": message.type, "text": message.text}
                    )
                    if message.type in {"warning", "error"}
                    else None,
                )

                def route_request(route: Any) -> None:
                    url = route.request.url
                    parsed = urlsplit(url)
                    if parsed.scheme in {"data", "blob", "about"}:
                        route.continue_()
                        return
                    if parsed.scheme == "file":
                        candidate = Path(unquote(parsed.path)).resolve()
                        try:
                            candidate.relative_to(asset_root.resolve())
                        except ValueError:
                            blocked_external_requests.append(url)
                            route.abort("blockedbyclient")
                            return
                    elif parsed.netloc == "mpres.invalid":
                        candidate = local_file_for(url)
                    else:
                        blocked_external_requests.append(url)
                        route.abort("blockedbyclient")
                        return
                    if candidate is None or not candidate.is_file():
                        route.abort("failed")
                        return
                    content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                    route.fulfill(status=200, content_type=content_type, body=candidate.read_bytes())

                context.route("**/*", route_request)
                page.set_content(
                    html_text,
                    wait_until="domcontentloaded",
                    timeout=min(timeout_ms, 15000),
                )
                page.wait_for_selector(
                    SLIDE_SELECTOR,
                    state="attached",
                    timeout=readiness_timeout_ms,
                )
                page.evaluate(
                    """async () => {
                      if (document.fonts && document.fonts.ready) await document.fonts.ready;
                      if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
                        await window.MathJax.startup.promise;
                      }
                      const images = [...document.images];
                      await Promise.all(images.map(img => img.complete ? Promise.resolve() :
                        new Promise(resolve => {
                          img.addEventListener('load', resolve, {once:true});
                          img.addEventListener('error', resolve, {once:true});
                        })));
                      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                    }"""
                )
                slides = page.evaluate(_LAYOUT_SCRIPT)
                math_renderer = page.evaluate(
                    r"""() => {
                      const candidates = [
                        ...document.querySelectorAll('section[data-marpit-scope]'),
                        ...document.querySelectorAll('.marpit > section'),
                        ...document.querySelectorAll('svg[data-marpit-svg] > foreignObject > section'),
                        ...document.querySelectorAll('svg[data-marpit-svg] section')
                      ];
                      const sections = [...new Set(candidates)];
                      return sections.map((slide, index) => {
                        const id = slide.id || `slide-${index + 1}`;
                        const rendered = slide.querySelectorAll('mjx-container, .MathJax, .katex, math[xmlns]').length;
                        const errors = [...slide.querySelectorAll('merror, .MathJax_Error, .katex-error')]
                          .map(node => (node.textContent || '').trim()).filter(Boolean);
                        const text = (slide.innerText || '');
                        const leaked = [...text.matchAll(/(?:\\begin\{|\\end\{|\\frac\{|\\sqrt\{|\$\$|\\\[|\\\])/g)]
                          .map(match => match[0]).slice(0, 20);
                        return {id, rendered_math_nodes: rendered, renderer_errors: errors, leaked_markers: leaked};
                      });
                    }"""
                )
                browser_version = browser.version
                context.close()
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise MPresError("Temporary Marp HTML did not expose a supported slide DOM within 10 seconds; check the pinned Marp/inspector contract.") from exc
    except MPresError:
        raise
    except Exception as exc:
        raise MPresError(f"Temporary Marp HTML inspection failed: {type(exc).__name__}: {exc}") from exc

    overflow_slides = [row for row in slides if row.get("overflow")]
    id_counts: dict[str, int] = {}
    for row in slides:
        slide_id = str(row.get("id") or "")
        id_counts[slide_id] = id_counts.get(slide_id, 0) + 1
    duplicate_ids = sorted(slide_id for slide_id, count in id_counts.items() if count > 1)
    errors: list[str] = []
    if not slides:
        errors.append("Temporary Marp HTML contains no inspectable slide sections.")
    if duplicate_ids:
        errors.append("Temporary Marp HTML contains duplicate slide IDs: " + ", ".join(duplicate_ids))
    if overflow_slides:
        errors.append(
            "Detected HTML slide overflow on slide(s): "
            + ", ".join(str(row.get("id") or row.get("index")) for row in overflow_slides[:20])
        )
    if page_errors:
        errors.append(f"Temporary Marp HTML raised {len(page_errors)} page error(s).")
    if failed_requests:
        errors.append(f"Temporary Marp HTML had {len(failed_requests)} failed local request(s).")
    if blocked_external_requests:
        errors.append(
            f"Temporary Marp HTML attempted {len(blocked_external_requests)} external request(s)."
        )
    return {
        "schema_version": 1,
        "browser_executable": str(executable),
        "browser_source": source,
        "browser_version": browser_version,
        "slide_count": len(slides),
        "slides": slides,
        "math_renderer": math_renderer,
        "overflow_slide_count": len(overflow_slides),
        "overflow_slides": overflow_slides,
        "duplicate_slide_ids": duplicate_ids,
        "page_errors": page_errors,
        "failed_requests": failed_requests,
        "blocked_external_requests": blocked_external_requests,
        "console_messages": console_messages,
        "errors": errors,
        "warnings": [],
        "success": not errors,
        "inspection_policy": "author mechanical self-check; no screenshots or model vision",
    }


def inspect_marp_html_layout(
    root: Path,
    source: Path,
    *,
    policy: dict[str, Any],
    timeout: int = 1800,
    browser_runner: Callable[[Path, Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate disposable Marp HTML, inspect slide overflow, then delete the HTML.

    ``browser_runner`` exists for deterministic tests. Production always uses Playwright.
    """

    with tempfile.TemporaryDirectory(prefix="mpres-html-layout-") as raw:
        temp = Path(raw)
        source_copy = temp / "source"
        copy_source_tree(source, source_copy)
        output = temp / "deck.html"
        command = _marp_html_command(root, source_copy, output, policy)
        process = run_command(command, cwd=source_copy, timeout=timeout)
        if process.returncode != 0 or not output.is_file():
            return {
                "schema_version": 1,
                "command": command,
                "returncode": process.returncode,
                "stdout": process.stdout[-4000:],
                "stderr": process.stderr[-4000:],
                "temporary_html_retained": False,
                "errors": ["Marp could not generate temporary HTML for author layout inspection."],
                "warnings": [],
                "success": False,
            }
        if browser_runner is None:
            browser_report = _inspect_with_playwright(output, source_copy, timeout=timeout)
        else:
            browser_report = browser_runner(output, source_copy)
        return {
            **browser_report,
            "command": command,
            "returncode": process.returncode,
            "stdout": process.stdout[-4000:],
            "stderr": process.stderr[-4000:],
            "temporary_html_retained": False,
        }


def inspect_task_html_layout(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    stage: str,
    timeout: int = 1800,
) -> dict[str, Any]:
    from mpres.rendering import source_and_build_paths
    from mpres.util import read_yaml, relative_display, task_path, write_json_atomic

    source, build = source_and_build_paths(root, slug, presentation_id, stage)
    policy = read_yaml(task_path(root, slug) / "EXECUTION-POLICY.yaml") or {}
    if not isinstance(policy, dict):
        raise MPresError("EXECUTION-POLICY.yaml must be a mapping.")
    report = inspect_marp_html_layout(root, source, policy=policy, timeout=timeout)
    report.update(
        {
            "task_slug": slug,
            "presentation_id": presentation_id,
            "stage": stage,
            "source": relative_display(source / "presentation.md", root),
        }
    )
    build.mkdir(parents=True, exist_ok=True)
    report_path = build / f"html-layout-inspection-{stage}.json"
    write_json_atomic(report_path, report)
    report["report_path"] = relative_display(report_path, root)
    return report
