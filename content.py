import os
import re
import json
import markdown

TRANSCRIPTS_DIR = os.path.join(os.path.dirname(__file__), 'transcripts')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

_data_cache = None


def _load():
    global _data_cache
    if _data_cache is None:
        with open(os.path.join(DATA_DIR, 'modules.json'), encoding='utf-8') as f:
            _data_cache = json.load(f)
    return _data_cache


def get_sections():
    """Training sections (Press Operator, Die Setter, etc.) sorted for display."""
    return sorted(_load().get('sections', []), key=lambda s: s.get('sort_order', 0))


def get_modules():
    """All modules across all sections, in sort order."""
    return sorted(_load().get('modules', []), key=lambda m: m.get('sort_order', 0))


def get_modules_by_section():
    """List of (section, [modules]) tuples, sections in display order.

    Only sections that actually have modules are returned, so partially built
    curricula don't show empty headers."""
    mods = get_modules()
    out = []
    for s in get_sections():
        sec_mods = [m for m in mods if m.get('section') == s['code']]
        if sec_mods:
            out.append((s, sec_mods))
    return out


def get_module(code):
    for m in get_modules():
        if m['code'] == code:
            return m
    return None


def get_check(module, num):
    """Return the check dict with the given num from a module, or None."""
    if not module:
        return None
    for c in module.get('checks', []):
        if c['num'] == int(num):
            return c
    return None


def render_lesson(module_code, lang='en'):
    mod = get_module(module_code)
    if not mod:
        return "<p>Module not found.</p>"

    files = mod.get('lesson_en' if lang == 'en' else 'lesson_es', [])
    if not files:
        files = mod.get('lesson_en', [])

    combined_md = []
    for rel_path in files:
        full_path = os.path.join(TRANSCRIPTS_DIR, rel_path)
        if not os.path.exists(full_path):
            continue
        with open(full_path, encoding='utf-8') as f:
            text = f.read()
        text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.DOTALL)
        combined_md.append(text)

    md_text = '\n\n'.join(combined_md)
    md_text = _clean_lesson_md(md_text)

    html = markdown.markdown(md_text, extensions=['extra', 'tables', 'nl2br'])
    return html


def _clean_lesson_md(text):
    lines = text.split('\n')
    cleaned = []
    skip = False

    for line in lines:
        if '> [YELLOW PERFORMANCE CHECK PAGE]' in line:
            skip = True
            while cleaned and cleaned[-1].startswith('## [Page'):
                cleaned.pop()
            continue

        if re.match(r'^## \[Page \d+\]', line):
            skip = False

        if not skip:
            m = re.match(r'^## \[Page (\d+)\]', line)
            if m:
                cleaned.append(
                    f'<hr class="page-break"><span class="page-num">— page {m.group(1)} —</span>'
                )
            else:
                cleaned.append(line)

    return '\n'.join(cleaned)
