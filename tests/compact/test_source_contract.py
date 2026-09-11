"""Regression contract for the v6 HTML/CSS failures, without PDF model vision."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from mpres.source_policy import (inspect_markdown,inspect_source,install_theme,theme_bytes,
                                render_options,require_source)
from mpres.math_inspection import inspect_math_source
from mpres.marp_source import lint_deck, parse_deck
from mpres.util import MPresError
from test_relational_control import compact_root,prepare,register
from test_revision_quality import HEADER,SLIDE,good_source,revision


@pytest.mark.parametrize('body',[
 '<div>unsafe block</div>', 'inline <span>unsafe</span>', '<svg><line/></svg>\n**raw** $p$',
 '<!-- _class: core compact -->', '<!-- _style: font-size:12px -->',
 '<!-- slide-id: s1 --><style>section{}</style>', '<!-- author says all requirements met -->',
 '![w:200 diagram](a.svg)','![bg diagram](a.svg)',r'$\small x$', r'$\style{position:absolute}{x}$',
 r'$\newcommand{\fit}{\tiny} x$',
])
def test_forbidden_source_forms_cannot_enter_renderer(body):
    report=inspect_markdown(HEADER+body)
    assert not report['success'],body


@pytest.mark.parametrize('front',[
 'style: section { font-size: 10px; }','backgroundColor: red','_class: compact',
 'theme: other','math: katex','paginate: false','size: 4:3','marp: false',
 'theme: mathist-academic\ntheme: other',
])
def test_frontmatter_cannot_change_global_layout(front):
    report=inspect_markdown('---\n'+front+'\n---\n# page')
    assert not report['success'],front


@pytest.mark.parametrize('body',[
 '<!-- slide-id: x1 -->\n<!-- _class: core -->\n# title\n\n$x<y$ and $x<foo>$',
 '```html\n<div style="color:red">literal code</div>\n```',
 '````html\n```\n<style>literal</style>\n```\n````',
 '    <script>literal indented code</script>',
 '`<span>literal inline code</span>`',
 r'$\mathbf{x}=\begin{bmatrix}1\\2\end{bmatrix}$',
 'A < B and 1 < 2.\n\n|A|B|\n|-|-|\n|1|2|',
 '<https://example.org> and &lt;div&gt;',
])
def test_real_markdown_and_math_are_not_false_positive_html(body):
    report=inspect_markdown(HEADER+body)
    assert report['success'],report


def test_external_svg_reference_not_inline_svg(tmp_path):
    (tmp_path/'assets').mkdir();(tmp_path/'assets/a.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (tmp_path/'presentation.md').write_text(HEADER+SLIDE+'\n![coordinate diagram][fig]\n\n[fig]: assets/a.svg')
    assert inspect_source(tmp_path)['success']
    assert lint_deck(tmp_path,process_records=False)['success']


def test_modified_theme_or_extra_stylesheet_rejected(compact_root):
    service=prepare(compact_root);source=good_source(service)
    (source/'theme.css').chmod(0o644)
    (source/'theme.css').write_text('section svg { position:absolute; top:142px; right:68px }')
    with pytest.raises(MPresError,match='Custom stylesheet'):require_source(source)
    (source/'theme.css').write_bytes(theme_bytes())
    (source/'extra.css').write_text('section {font-size:3px}')
    assert not inspect_source(source)['success']


def test_forbidden_submission_keeps_attempt_and_artifacts_unchanged(compact_root):
    service=prepare(compact_root);register(service)
    attempt=service.bind(service.jobs()[0]['id'],'h1');service.started(attempt['id'],'host-receipt')
    source=good_source(service);(source/'presentation.md').write_text(HEADER+SLIDE+'\n<span>x</span>')
    with pytest.raises(MPresError,match='source contract'):
        service.submit(attempt['id'],{'summary':'draft'},source=source)
    assert service.attempt(attempt['id'])['state']=='running'
    assert service.store.rows('SELECT * FROM artifacts')==[]
    assert service.store.rows('SELECT * FROM findings')==[]


def test_omitted_theme_is_installed_in_snapshot_without_editing_author_source(compact_root):
    service=prepare(compact_root);register(service)
    attempt=service.bind(service.jobs()[0]['id'],'h1');service.started(attempt['id'],'host')
    source=good_source(service);(source/'theme.css').unlink()
    before=(source/'presentation.md').read_bytes()
    result=service.submit(attempt['id'],{'summary':'Fixed source'},source=source)
    path=service.task/service.store.rows('SELECT path FROM artifacts WHERE id=?',(result['artifact_id'],))[0]['path']
    assert (path/'theme.css').read_bytes()==theme_bytes()
    assert not ((path/'theme.css').stat().st_mode & 0o222)
    assert not (source/'theme.css').exists()
    assert (source/'presentation.md').read_bytes()==before
    assert service.submit(attempt['id'],{'summary':'Fixed source'},source=source)['already_submitted']


def test_actual_v6_css_failure_pattern_is_rejected_before_marp_lookup(tmp_path):
    from mpres.rendering import _marp_command
    (tmp_path/'presentation.md').write_text(HEADER+SLIDE+'''
<svg><path d="M0 0 L20 20"/></svg>
**图示对应：**$p$ 是一个特解；$v$ 是齐次方向。
''')
    (tmp_path/'theme.css').write_text('section.gate-repair-l04-s03 svg { position:absolute; top:142px; right:68px; }')
    with pytest.raises(MPresError,match='source contract'):
        _marp_command(tmp_path,tmp_path,tmp_path/'out.pdf',{})
    assert not (tmp_path/'out.pdf').exists()


def test_lint_treats_html_and_images_in_code_as_literal(compact_root):
    service=prepare(compact_root);source=good_source(service)
    (source/'presentation.md').write_text(HEADER+SLIDE+'\n```html\n<script>example</script>\n![not-image](missing.png)\n```')
    report=lint_deck(source,process_records=False)
    assert report['success'],report['errors']


def test_nested_math_correct_but_crossed_environments_wrong(tmp_path):
    p=tmp_path/'presentation.md'
    p.write_text(HEADER+SLIDE+r'\n$$\begin{aligned}x&=\begin{bmatrix}1\\2\end{bmatrix}\end{aligned}$$')
    report=inspect_math_source(tmp_path)
    assert report['success'],report
    p.write_text(p.read_text().replace(r'\end{bmatrix}\end{aligned}',r'\end{aligned}\end{bmatrix}'))
    assert not inspect_math_source(tmp_path)['success']


def test_render_options_cannot_use_source_theme_or_auto_config():
    options=render_options()
    assert '--no-html' in options and '--html' not in options
    assert '--no-config-file' in options
    assert Path(options[options.index('--theme-set')+1]).read_bytes()==theme_bytes()


def test_new_policy_does_not_reuse_old_successful_gate(compact_root):
    from mpres.control.quality import Quality
    service=prepare(compact_root);aid=revision(service);quality=Quality(service.task)
    old=quality.inspect(aid)
    with service.store.transaction() as c:
        data=json.loads(old['detail_json']);data.pop('source_policy_version')
        c.execute('UPDATE gate_runs SET detail_json=? WHERE id=?',(json.dumps(data),old['id']))
    with pytest.raises(MPresError,match='predates'):quality.require_pass(aid,'source')
    new=quality.inspect(aid)
    assert new['id']!=old['id'] and new['state']=='passed'
    assert quality.require_pass(aid,'source')['id']==new['id']


def test_dom_numeric_ids_and_math_ids_map_to_same_source(compact_root):
    from mpres.html_layout import canonical_report_ids
    service=prepare(compact_root);source=good_source(service)
    report={'success':True,'errors':[],'slides':[{'index':1,'id':'1'}],
            'math_renderer':[{'id':'1','rendered_math_nodes':1}]}
    result=canonical_report_ids(report,source)
    assert result['slides'][0]['id']==result['math_renderer'][0]['id']=='p01-l01-s1'
    result=canonical_report_ids({'success':True,'slides':[]},source)
    assert result['success'] is False


def test_source_cli_is_usable_outside_task(compact_root,capsys):
    from mpres.control.cli import main
    service=prepare(compact_root);source=good_source(service)
    assert main(['--root',str(compact_root),'source','check',str(source)])==0
    (source/'presentation.md').write_text(HEADER+'<div>bad</div>')
    assert main(['--root',str(compact_root),'source','check',str(source)])==2


def test_slide_breaks_and_references_follow_markdown(tmp_path):
    (tmp_path/'assets').mkdir()
    (tmp_path/'assets/a.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    body = HEADER + SLIDE + '''

![diagram][global]

````markdown
```
---
<div>literal</div>
```
````

---

<!-- slide-id: next-page -->
<!-- _class: support -->
# End

[global]: assets/a.svg
'''
    p=tmp_path/'presentation.md';p.write_text(body)
    deck=parse_deck(p)
    assert len(deck.slides)==2
    assert deck.slides[0].image_paths==['assets/a.svg']
    assert inspect_source(tmp_path)['success']
    assert lint_deck(tmp_path,process_records=False)['success']


def test_metadata_inside_code_does_not_approve_slide(tmp_path):
    p=tmp_path/'presentation.md'
    p.write_text(HEADER+'# Literal example\n\n```html\n<!-- slide-id: fake -->\n<!-- _class: core -->\n```\n')
    assert inspect_source(tmp_path)['success']  # Legal literal HTML example.
    report=lint_deck(tmp_path,process_records=False)
    assert not report['success']
    assert any('Missing <!-- slide-id' in e for e in report['errors'])


def test_math_examples_in_long_or_indented_code_not_inspected(tmp_path):
    p=tmp_path/'presentation.md'
    p.write_text(HEADER+SLIDE+'''

````markdown
```
$frac{1}{2}$
$$\\begin{matrix}
```
````

    $$\\begin{matrix}

``$frac{1}{2}$``
''')
    assert inspect_math_source(tmp_path)['success']
    assert lint_deck(tmp_path,process_records=False)['success']
