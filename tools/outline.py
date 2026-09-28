"""hwpx 본문 최상위 문단 목록: 번호, 쪽나눔, 스타일, 제어, 표(행x열)/그림, 텍스트 앞부분
  python tools/outline.py 파일.hwpx [출력.txt]
"""
import sys
import zipfile
import lxml.etree as E
sys.path.insert(0, __file__.rsplit('tools', 1)[0])
from hwpx_restyle.common import NS, HP, para_text

z = zipfile.ZipFile(sys.argv[1])
H = E.fromstring(z.read('Contents/header.xml'))
stn = {e.get('id'): e.get('name') for e in H.iterfind('.//hh:style', NS)}
secs = sorted(n for n in z.namelist() if n.startswith('Contents/section'))
L = []
for sname in secs:
    S = E.fromstring(z.read(sname))
    L.append('##### ' + sname)
    for i, p in enumerate(S.iterfind('hp:p', NS)):
        ctr = [c.tag.split('}')[1] for r in p.iterfind('hp:run', NS) for c in r
               if c.tag.split('}')[1] not in ('t', 'tbl', 'pic')]
        ex = ''
        for t in p.findall('hp:run/hp:tbl', NS):
            ex += ' TBL%sx%s%s' % (t.get('rowCnt'), t.get('colCnt'), '+PIC' if t.find('.//hp:pic', NS) is not None else '')
        for t in p.findall('hp:run/hp:pic', NS):
            ex += ' PIC%s' % t.find('hp:curSz', NS).get('width')
        shapes = [c for r in p.iterfind('hp:run', NS) for c in r
                  if c.tag.split('}')[1] in ('container', 'rect', 'ellipse', 'polygon', 'line', 'curve')]
        stext = ''
        for c in shapes:
            ex += ' ' + c.tag.split('}')[1][:4].upper()
            stext += '[' + ' / '.join(para_text(q).strip() for q in c.iter(HP + 'p') if para_text(q).strip())[:50] + ']'
        L.append('%5d %s %-18s %-22s %-18s| %s' % (i, 'PB' if p.get('pageBreak') == '1' else '  ',
                 stn.get(p.get('styleIDRef'), '?')[:18], ','.join(ctr)[:22], ex[:18], para_text(p)[:60] + stext))
out = '\n'.join(L)
if len(sys.argv) > 2:
    open(sys.argv[2], 'w', encoding='utf8').write(out)
else:
    print(out)
