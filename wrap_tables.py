from pathlib import Path
import re

p = Path('frontend/mis.html')
text = p.read_text(encoding='utf-8')

# 1. Remove all colgroup blocks
text = re.sub(r'<colgroup>.*?</colgroup>\s*', '', text, flags=re.S)

# 2. Remove table-layout:fixed;width:100% inline styles from dsu-table / dsu-table7
text = re.sub(
    r'(<table class="dsu-table(?:7)?")[^>]*style="[^"]*(?:table-layout:fixed|width:100%)[^"]*"[^>]*>',
    r'\1>',
    text,
    flags=re.S
)

# 3. Wrap every dsu-table / dsu-table7 in report-table-container (but not if already wrapped)
def wrap_table(m):
    before = text[:m.start()]
    # check if already inside report-table-container by looking at last 40 chars before match
    if before.rstrip().endswith('>'):
        last_tag_start = before.rfind('<', max(0, len(before)-80))
        last_tag = before[last_tag_start:m.start()]
        if 'report-table-container' in last_tag:
            return m.group(0)
    return '<div class="report-table-container">\n' + m.group(0)

text = re.sub(r'<table class="dsu-table(?:7)?"[^>]*>', wrap_table, text, flags=re.S)

# 4. Close the wrapper after each table that we opened
# We opened a div just before <table>; close after </table> if the div was added.
# Simple heuristic: after every </table> that follows a dsu-table, if the preceding open was wrapped, close it.
# Since we wrapped ALL dsu-table opens, close all corresponding closes.
text = re.sub(r'(</table>\s*)', r'\1\n</div>\n', text)

p.write_text(text, encoding='utf-8')
print('Mechanical table wrapping done.')
print('colgroup count:', text.count('<colgroup'))
print('table-layout fixed count:', len(re.findall(r'table-layout:fixed', text)))
print('report-table-container count:', text.count('report-table-container'))
print('table open count:', len(re.findall(r'<table class="dsu-table', text)))
print('table close count:', text.count('</table>'))
