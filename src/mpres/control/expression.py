"""Small program-generated contract; no duplicated per-slide self-certification."""
from __future__ import annotations
import re


def discipline(settings: dict, task_text: str = '') -> str | None:
    explicit=settings.get('teaching',{}).get('discipline','auto')
    if explicit!='auto':return explicit
    title=settings.get('title','')+' '+task_text[:1200]
    return 'mathematics' if re.search(r'线性代数|高等数学|微积分|概率论|数学|linear algebra|calculus|mathematics',title,re.I) else None


def contract(kind: str, channel: str | None = None, *, source_sha256: str | None = None) -> dict:
    return {'version':1,'source_sha256':source_sha256,'scope':'all_student_visible_text_of_selected_deck',
        'dimensions':['optional_useful_titles','disciplinary_language','independent_sentence_line_starts','clear_natural_connected_prose'],
        'role':channel or kind,'title_required':False,'per_page_self_reports_required':False,
        'review_boundary':'All five channels retain their own responsibilities; identify concrete additional problems, never filter them merely because they differ from the initial repair focus.',
        'precedence':'The current confirmed repair scope and current feedback supersede older focus-only instructions. Historical plan briefs are context, not authority to restore superseded authenticity/proof/polishing restrictions. Explicit scope, runtime, permissions and teaching choices remain binding.'}
