"""The user's project-wide Gaia/lead presentation contract (not author CSS)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mpres.control.quality import Quality, asset_boundary
from mpres.source_policy import (POLICY_VERSION, THEME_PATH, inspect_markdown,
                                inspect_source, install_theme, theme_bytes)
from mpres.util import MPresError
from test_relational_control import compact_root, prepare, register
from test_revision_quality import good_source, revision

ROOT = Path(__file__).resolve().parents[2]


def test_user_theme_typography_and_colours_are_not_old_defaults():
    css = theme_bytes().decode()
    for expected in ("'Arial', 'Microsoft YaHei'", 'font-size: 24px', 'line-height: 1.6',
                     'font-size: 36px', 'font-size: 30px', 'font-size: 26px',
                     '#2c3e50', '#34495e', '#2980b9', '#e74c3c', '#3498db'):
        assert expected in css
    assert 'font-size: 52px' not in css
    assert 'justify-content: safe center' in css
    assert 'box-sizing: border-box' in css
    assert 'position: relative' in css


def test_user_utility_palette_is_preserved_without_opening_markup():
    css = theme_bytes().decode()
    for name in ('.columns', '.center', '.small', '.warning', '.success', '.formula',
                 '.quote-large', '.quote-middle'):
        assert name in css
    for source in ('<div class="columns">x</div>', '<span class="small">x</span>',
                   '<!-- _class: small -->', '---\nstyle: "p {font-size:12px}"\n---\nx'):
        assert not inspect_markdown(source)['success']


def test_offline_theme_does_not_request_gaia_web_fonts():
    import re
    css = theme_bytes().decode()
    without_comments = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    assert not re.search(r'@import|url\s*\(', without_comments, flags=re.I)
    assert '--theme gaia' not in css


def test_tables_images_and_math_have_separate_structural_rules():
    css = theme_bytes().decode()
    assert 'border-collapse: collapse' in css
    assert 'border: 2px solid #8195a5' in css
    assert 'padding: 10px 16px' in css
    assert 'section p:has(> img:only-child)' in css
    assert 'flex-shrink: 0' in css
    import re
    assert not re.search(r'(?m)^[^/\n]*\bsvg\b[^\n]*\{', css)


def test_theme_copy_matches_canonical_bytes():
    assert (ROOT / 'themes/mathist-academic.css').read_bytes() == theme_bytes()


def test_new_theme_passes_real_source_and_asset_checks(compact_root):
    service = prepare(compact_root)
    source = good_source(service)
    assert inspect_source(source)['success']
    assert asset_boundary(source)['success']
    assert not (source / 'theme.css').stat().st_mode & 0o222


def test_old_theme_gate_is_never_reused(compact_root):
    service = prepare(compact_root)
    aid = revision(service)
    q = Quality(service.task)
    old = q.inspect(aid)
    with service.store.transaction() as c:
        detail = json.loads(old['detail_json'])
        detail['source_policy_version'] = 3
        c.execute('UPDATE gate_runs SET detail_json=? WHERE id=?', (json.dumps(detail), old['id']))
    with pytest.raises(MPresError, match='predates'):
        q.require_pass(aid, 'source')
    new = q.inspect(aid)
    assert new['id'] != old['id'] and new['state'] == 'passed'
    assert json.loads(new['detail_json'])['source_policy_version'] == POLICY_VERSION == 4


def test_old_artifact_is_preserved_and_new_edit_gets_new_project_theme(compact_root):
    service = prepare(compact_root)
    source = good_source(service)
    original = (source / 'presentation.md').read_bytes()
    # An old snapshot is evidence, not an editable stylesheet migration target.
    legacy = b'/* @theme mathist-academic */\nsection { font-size: 30px; }\n'
    (source / 'theme.css').chmod(0o644)
    (source / 'theme.css').write_bytes(legacy)
    with pytest.raises(MPresError, match='Custom/modified'):
        install_theme(source)
    assert (source / 'theme.css').read_bytes() == legacy
    assert (source / 'presentation.md').read_bytes() == original
    new = service.task / 'content' / 'new-edit'; new.mkdir()
    (new / 'presentation.md').write_bytes(original)
    install_theme(new)
    assert inspect_source(new)['success']
    assert (new / 'theme.css').read_bytes() == theme_bytes()


def test_actual_v7_formula_table_fixture_uses_only_legal_markdown(tmp_path):
    from mpres.control.files import copy_tree
    from mpres.geometry import build
    target = tmp_path / 'source'
    copy_tree(ROOT / 'tests/fixtures/project-theme', target, read_only=False)
    build(target / 'assets/intersection.plot.json')
    install_theme(target)
    report = inspect_source(target)
    assert report['success'], report
    assert '| $x+y=4$ | $3+1=4$ | 成立 |' in (target / 'presentation.md').read_text()


def test_smoke_fixture_is_checked_by_the_same_real_contract(tmp_path, monkeypatch):
    import mpres.toolchain as t
    import fitz
    from types import SimpleNamespace
    monkeypatch.setattr(t, 'installed_marp_version', lambda r: {
        'expected': '4.5.0', 'actual': '4.5.0', 'returncode': 0, 'matches': True})
    checked = []
    def inspect(root, source, **kw):
        report = inspect_source(source)
        assert report['success'], report
        checked.append(report)
        return {'success': True, 'errors': [], 'slide_count': 3}
    def run(cmd, **kw):
        pdf = Path(cmd[cmd.index('--output')+1])
        doc = fitz.open()
        for _ in range(3): doc.new_page()
        doc.save(pdf); doc.close()
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(t, 'inspect_marp_html_layout', inspect)
    monkeypatch.setattr(t, '_marp_command', lambda r: ['explicit-test-double'])
    monkeypatch.setattr(t, 'run_command', run)
    assert t.smoke_toolchain(tmp_path)['success']
    assert len(checked) == 1
