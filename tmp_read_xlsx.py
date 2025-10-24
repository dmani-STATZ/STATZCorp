import zipfile, xml.etree.ElementTree as ET, sys
path = r"contracts/Samples/MasterLog_20251024113137.xlsx"
try:
    zf = zipfile.ZipFile(path)
except Exception as e:
    print("ERR: cannot open", e)
    sys.exit(1)
# Read workbook and relationships
wb = ET.fromstring(zf.read('xl/workbook.xml'))
ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
rels = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
nsr={'r':'http://schemas.openxmlformats.org/package/2006/relationships'}
# Gather sheets
sheets=[]
for sh in wb.find('m:sheets',ns):
    sheets.append((sh.attrib.get('name'), sh.attrib.get('sheetId'), sh.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')))
print('Sheets:', [s[0] for s in sheets])
# Map rel id to target
rid_to_target = {rel.attrib['Id']: rel.attrib['Target'] for rel in rels.findall('r:Relationship', nsr)}
# Helper to read shared strings
shared=[]
if 'xl/sharedStrings.xml' in zf.namelist():
    sst = ET.fromstring(zf.read('xl/sharedStrings.xml'))
    for si in sst.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
        text_parts = []
        for t in si.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'):
            text_parts.append(t.text or '')
        shared.append(''.join(text_parts))

# Read first sheet
first = sheets[0]
ws_path = 'xl/' + rid_to_target.get(first[2])
ws = ET.fromstring(zf.read(ws_path))
# rows
sheetData = ws.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData')
rows = sheetData.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row')

def get_cell_value(c):
    v = c.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
    if v is None:
        return ''
    val = v.text
    t = c.attrib.get('t')
    if t == 's':
        idx = int(val)
        return shared[idx] if idx < len(shared) else ''
    return val

# First row header
header_vals = []
if rows:
    for c in rows[0].findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
        header_vals.append(get_cell_value(c))
print('Header columns (first sheet):')
print('|'.join(header_vals))
# First 5 data rows
print('Sample rows:')
for r in rows[1:6]:
    vals=[get_cell_value(c) for c in r.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c')]
    print('|'.join(vals))
