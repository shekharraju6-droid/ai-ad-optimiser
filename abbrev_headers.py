from pathlib import Path
import re

p = Path('frontend/mis.html')
text = p.read_text(encoding='utf-8')

replacements = [
    ('<th class="text-right">Application Submitted</th>', '<th class="text-right num">Apps</th>'),
    ('<th class="text-right">Cost Per Application</th>', '<th class="text-right num">CPA</th>'),
    ('<th class="text-right">Target Application</th>', '<th class="text-right num">Target</th>'),
    ('<th class="text-right">Spend</th>', '<th class="text-right num">Spend</th>'),
    ('<th class="text-center">Campaign Status</th>', '<th class="text-center">Status</th>'),
    ('<th class="text-right">Media Budget Received</th>', '<th class="text-right num">Budget</th>'),
    ('<th class="text-right">Remaining Budget</th>', '<th class="text-right num">Remaining</th>'),
    ('<th class="text-right">Lead</th>', '<th class="text-right num">Lead</th>'),
    ('<th class="text-right">CPL</th>', '<th class="text-right num">CPL</th>'),
    ('<th class="text-right">Amount Received</th>', '<th class="text-right num">Amount</th>'),
    ('<th class="text-right" style="white-space:nowrap">Application Submitted</th>', '<th class="text-right num" style="white-space:nowrap">Apps</th>'),
    ('<th class="text-right">CPA</th>', '<th class="text-right num">CPA</th>'),
    ('<th class="text-right">Target</th>', '<th class="text-right num">Target</th>'),
]

for old, new in replacements:
    if old in text:
        text = text.replace(old, new)
        print(f'Replaced: {old[:60]}... -> {new[:60]}...')

# Add num class to numeric td cells that don't have it
def add_num_to_numeric_td(m):
    cls = m.group(1)
    if 'num' not in cls:
        cls = cls + ' num'
    return '<td class="%s">' % cls.strip()

text = re.sub(r'<td class="(text-right[^"]*)"\>', add_num_to_numeric_td, text)

# Remove dsu-table4-wrap wrappers, keep only report-table-container
text = re.sub(r'<div class="dsu-table4-wrap">\s*<div class="report-table-container">', '<div class="report-table-container">', text)
text = re.sub(r'\s*</div>\s*<!--\s*dsu-table4-wrap\s*-->', '</div>', text)
# Also handle closing where </div> after </table> closes wrapper then another closes dsu-table4-wrap
# Simpler: just remove dsu-table4-wrap class from any div
p.write_text(text, encoding='utf-8')
print('Done.')
print('dsu-table4-wrap count:', text.count('dsu-table4-wrap'))
print('report-table-container count:', text.count('report-table-container'))
