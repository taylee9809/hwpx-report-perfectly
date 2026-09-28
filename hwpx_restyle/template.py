"""샘플(서식 기준) hwpx 분석 → 조판에 쓸 원형(prototype) 모음"""
import os
import re
import zipfile
from collections import Counter, defaultdict

import lxml.etree as E

from .common import (NS, HP, CHAPTER_RE, TOTAL_RE, para_text, all_text, is_num, top_tbl,
                     heading_of, shapes_of, toc_items, level_of, NUM_TITLE, report_title)

# 텍스트 모양으로 문단 종류 판별 → 샘플에서 같은 종류에 쓰인 스타일로 대응
PATTERNS = [
    ('note', re.compile(r'^\s*(주|자료)\s*\)|^\s*※')),
    ('unit', re.compile(r'^\(?단위\s*[:：]')),
    ('tcont', re.compile(r'^<\s*표\s*계속\s*>|^〈\s*표\s*계속')),
    ('tcap', re.compile(r'^[<〈]\s*표\s*[\d.\-]+\s*[>〉]')),
    ('fcap', re.compile(r'^[<〈]\s*그림\s*[\d.\-]+\s*[>〉]')),
    ('h1', re.compile(r'^\d+\.\s+\S')),
    ('h2', re.compile(r'^\d+\.\d+\s+\S')),
    ('h3', re.compile(r'^\d+\.\d+\.\d+\s')),
    ('h4', re.compile(r'^[가-힣]\.\s')),
    ('h5', re.compile(r'^\d+\)\s')),
    ('h6', re.compile(r'^[가-힣]\)\s')),
    ('h7', re.compile(r'^\(\d+\)\s')),
    ('h8', re.compile(r'^[①-⑳]')),
    ('dash', re.compile(r'^[-–·]\s')),
    ('bullet', re.compile(r'^[◦○•▪■□◎∙]')),
]
NAME_KEYS = ['표번호', '표제목', '그림제목', '그림번호', '단위', '주)', '주,', '표상단', '표상부', '표머리',
             '표내용', '표숫자', '표가운데', '표좌정렬', '표옆', '표문단']


PAGE_CTRLS = ('header', 'footer', 'newNum', 'pageHiding', 'pageNumCtrl', 'pageNum')


def light(color, limit=0.8):
    """'#RRGGBB' 밝기(0~1)가 limit 이상인가"""
    try:
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    except (ValueError, TypeError):
        return False
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 >= limit


def norm_name(name):
    """스타일 이름 비교용: 앞 접두어(@, w_, %, 숫자 아닌 기호)·공백·# 제거"""
    s = re.sub(r'^(?:[@%★☆]+|[wW]_)+', '', name.strip())
    return re.sub(r'[\s#\-_]+', '', s)


def kind_of(text):
    s = text.strip()
    if not s:
        return 'empty'
    for k, r in PATTERNS:
        if r.match(s):
            return k
    return 'body'


def section_files(z):
    names = [n for n in z.namelist() if re.match(r'Contents/section\d+\.xml$', n)]
    return sorted(names, key=lambda n: int(re.findall(r'\d+', n)[0]))


class Template:
    def __init__(self, path):
        self.path = path
        self.z = zipfile.ZipFile(path)
        self.H = E.fromstring(self.z.read('Contents/header.xml'))
        self.sections = [(n, E.fromstring(self.z.read(n))) for n in section_files(self.z)]
        self.S = self.sections[0][1]
        self.P = [p for _, S in self.sections for p in S.iterfind('hp:p', NS)]
        self.style_id = {e.get('name'): e.get('id') for e in self.H.iterfind('.//hh:style', NS)}
        self.style_name = {v: k for k, v in self.style_id.items()}
        self.style_def = {e.get('name'): (e.get('paraPrIDRef'), e.get('charPrIDRef'))
                          for e in self.H.iterfind('.//hh:style', NS)}
        self.parapr = {e.get('id'): e for e in self.H.iterfind('.//hh:paraPr', NS)}
        self.charpr = {e.get('id'): e for e in self.H.iterfind('.//hh:charPr', NS)}
        self.borderfill = {e.get('id'): e for e in self.H.iterfind('.//hh:borderFill', NS)}
        self.report_title = report_title(self.z, [S for _, S in self.sections])
        self._structure()
        self._paragraph_protos()
        self._table_proto()
        self._figure_proto()
        self._pic_protos()
        self._small_chars()

    def sname(self, p):
        return self.style_name.get(p.get('styleIDRef'), '바탕글')

    # ------------------------------------------------------------ 구조(구역·간지·장·절)
    def _structure(self):
        # 구역 정의(secPr): 방향별
        self.secpr = {}
        for _, S in self.sections:
            first = S.find('hp:p', NS)
            run = next((r for r in first.iterfind('hp:run', NS) if r.find('hp:secPr', NS) is not None), None)
            if run is None:
                continue
            land = run.find('hp:secPr/hp:pagePr', NS).get('landscape') == 'NARROWLY'
            self.secpr.setdefault(land, run)
        self.cover = None
        self.chapter = None      # (문단, 번호, 제목)
        self.headings = {}       # 수준 → (문단, 번호, 제목)
        self.special = set()     # 간지·장·절 제목 문단(본문 통계에서 뺀다)
        self.heading_style = defaultdict(Counter)   # 문단형 제목의 스타일(수준별)
        for p in self.P:
            if self.chapter is None and not self.headings and self.cover is None and len(toc_items(p)) >= 1:
                self.cover = p
                self.special.add(p)
                continue
            txt = para_text(p).strip()
            m = CHAPTER_RE.match(txt)
            if m and len(txt) < 60 and top_tbl(p) is None:
                if self.chapter is None:
                    self.chapter = (p, m.group(1), m.group(2).strip())
                self.special.add(p)
                continue
            for el in p.findall('hp:run/hp:tbl', NS) + shapes_of(p):
                h = heading_of(el)
                if not h:
                    continue
                self.special.add(p)
                if h['t'] == 'chapter' and self.chapter is None:
                    self.chapter = (p, h['num'], h['title'])
                elif h['t'] == 'sec':
                    self.headings.setdefault(level_of(h['num']), (p, h['num'], h['title']))
            if p not in self.special and top_tbl(p) is None:
                m = NUM_TITLE.match(txt) or re.match(r'^(\d+\.)\s+(\S.*)$', txt)
                if m and len(txt) < 60:
                    self.heading_style[level_of(m.group(1))][self.sname(p)] += 1
        self.chap_num = self.chapter[1] if self.chapter else None
        self.chap_title = self.chapter[2] if self.chapter else None
        self.cover_paras = []
        if self.cover is not None and self.chapter is not None:
            for p in self.sections[0][1].iterfind('hp:p', NS):
                if p is self.chapter[0]:
                    break
                self.cover_paras.append(p)
            if self.cover not in self.cover_paras:
                self.cover_paras = [self.cover]
        elif self.cover is not None:
            self.cover_paras = [self.cover]
        self.special.update(self.cover_paras)
        # 쪽 관련 조판 부호(머리말·꼬리말·쪽번호 새로·감추기): 간지·장 제목 밖에 있는 것
        own = set(self.cover_paras) | {self.cover, self.chapter[0] if self.chapter else None}
        self.page_ctrls = []     # (장 제목 앞인가, ctrl)
        before = True
        for p in self.sections[0][1].iterfind('hp:p', NS):
            if self.chapter and p is self.chapter[0]:
                before = False
            if p in own:
                continue
            for c in p.findall('hp:run/hp:ctrl', NS):
                if any(ch.tag.split('}')[1] in PAGE_CTRLS for ch in c):
                    self.page_ctrls.append((before and self.chapter is not None, c))

    # ------------------------------------------------------------ 문단
    def _paragraph_protos(self):
        self.pcount = defaultdict(Counter)      # 스타일 → (paraPr, charPr)
        self.ecount = defaultdict(Counter)      # 빈 문단
        self.kind_style = defaultdict(Counter)  # 텍스트 종류 → 스타일
        self.body_len = Counter()
        for p in self.P:
            if top_tbl(p) is not None or p in self.special or p.find('hp:run/hp:secPr', NS) is not None:
                continue
            name = self.sname(p)
            txt = para_text(p)
            runs = [r for r in p.iterfind('hp:run', NS) if r.find('hp:t', NS) is not None]
            r0 = runs[-1] if runs else p.find('hp:run', NS)
            cp = r0.get('charPrIDRef') if r0 is not None else self.style_def[name][1]
            if txt.strip():
                k = kind_of(txt)
                self.pcount[name][(p.get('paraPrIDRef'), cp)] += 1
                self.kind_style[k][name] += 1
                if k == 'body' and not any(x in name for x in NAME_KEYS):
                    self.body_len[name] += len(txt)
            elif p.find('.//hp:pic', NS) is None and not shapes_of(p):
                self.ecount[name][(p.get('paraPrIDRef'), cp)] += 1
        self.body_style = (self.body_len.most_common(1) or [('바탕글', 0)])[0][0]

    def para_proto(self, name):
        if self.pcount[name]:
            return self.pcount[name].most_common(1)[0][0]
        return self.style_def[name]

    def empty_proto(self, name):
        if self.ecount[name]:
            return self.ecount[name].most_common(1)[0][0]
        return self.para_proto(name)

    def resolve_style(self, name, text=''):
        """원본 스타일명 → 샘플에 있는 스타일명"""
        if name in self.style_id:
            return name
        key = norm_name(name)                  # '@가.' ~ '가.', 'w_1.1.1' ~ '1.1.1'
        same = [n for n in self.style_id if norm_name(n) == key]
        if key and same:
            used = [n for n in same if self.pcount[n]]
            return (used or same)[0]
        for key in NAME_KEYS:                  # 이름 계열이 같은 스타일
            if key in name:
                cands = [n for n in self.style_id if key in n]
                used = [n for n in cands if self.pcount[n]]
                if used or cands:
                    return (used or cands)[0]
        k = kind_of(text)                      # 텍스트 모양으로
        if k not in ('body', 'empty') and self.kind_style[k]:
            return self.kind_style[k].most_common(1)[0][0]
        return self.body_style

    def heading_para_style(self, level):
        if self.heading_style[level]:
            return self.heading_style[level].most_common(1)[0][0]
        k = self.kind_style.get('h%d' % level)
        if k:
            return k.most_common(1)[0][0]
        return self.body_style

    # ------------------------------------------------------------ 표
    def _table_proto(self):
        data = []
        for p in self.P:
            if p in self.special:
                continue
            for t in p.findall('hp:run/hp:tbl', NS):
                if len(list(t.iter(HP + 'tc'))) >= 4 and t.find('.//hp:pic', NS) is None and heading_of(t) is None:
                    data.append((p, t))
        self.has_tables = bool(data)
        if not data:
            self.tbl = None
            self.roles = {}
            self.tbl_w = 48000
            self.row_h = 1500
            self.tbl_anchor = (self.style_id.get(self.body_style, '0'),) + self.para_proto(self.body_style)
            return
        self.tbl_anchor = Counter((p.get('styleIDRef'), p.get('paraPrIDRef'), p.find('hp:run', NS).get('charPrIDRef'))
                                  for p, t in data).most_common(1)[0][0]
        self.tbl = max(data, key=lambda x: len(list(x[1].iter(HP + 'tc'))))[1]
        self.tbl_w = Counter(int(t.find('hp:sz', NS).get('width')) for p, t in data).most_common(1)[0][0]
        roles = defaultdict(Counter)
        heights = Counter()
        for p, t in data:
            first = t.find('hp:tr', NS)
            nhead = max(int(tc.find('hp:cellSpan', NS).get('rowSpan')) for tc in first.iterfind('hp:tc', NS))
            if nhead >= int(t.get('rowCnt')):
                nhead = 1
            total_rows = set()
            for tc in t.iter(HP + 'tc'):
                if TOTAL_RE.match(all_text(tc).strip()) and int(tc.find('hp:cellAddr', NS).get('colAddr')) <= 2:
                    total_rows.add(int(tc.find('hp:cellAddr', NS).get('rowAddr')))
            for tc in t.iter(HP + 'tc'):
                row = int(tc.find('hp:cellAddr', NS).get('rowAddr'))
                col = int(tc.find('hp:cellAddr', NS).get('colAddr'))
                q = tc.find('hp:subList/hp:p', NS)
                r = q.find('hp:run', NS)
                txt = all_text(tc).strip()
                key = (q.get('styleIDRef'), q.get('paraPrIDRef'), r.get('charPrIDRef') if r is not None else '0',
                       tc.get('borderFillIDRef'))
                if row < nhead:
                    roles['head'][key] += 1
                elif row in total_rows and tc.find('hp:cellSpan', NS).get('rowSpan') == '1':
                    if self.fill_of(tc.get('borderFillIDRef')):
                        roles['total_num' if (txt and is_num(txt)) else 'total_label'][key] += 1
                    if txt and is_num(txt):
                        roles['num'][key] += 1
                elif txt and is_num(txt):
                    roles['num'][key] += 1
                elif txt and col == 0 and len(txt) <= 4:
                    roles['label_short'][key] += 1
                elif txt and col == 0:
                    roles['label'][key] += 1
                elif txt:
                    roles['text'][key] += 1
                else:
                    roles['empty'][key] += 1
                if row >= nhead and tc.find('hp:cellSpan', NS).get('rowSpan') == '1' and txt \
                        and len(tc.findall('hp:subList/hp:p', NS)) == 1 and len(txt) <= 10:
                    heights[int(tc.find('hp:cellSz', NS).get('height'))] += 1   # 한 줄짜리 짧은 칸
        fb = {'label_short': 'label', 'label': 'text', 'text': 'label', 'num': 'text', 'empty': 'num', 'head': 'text'}
        self.roles = {}
        for k in ['head', 'num', 'text', 'label', 'label_short', 'empty']:
            c = roles[k] or roles[fb[k]] or roles['text'] or roles['num'] or roles['head']
            self.roles[k] = c.most_common(1)[0][0]
        # 합계 행: 샘플에 채움 있는 합계 행이 있으면 그 서식, 없으면 None(빌드 때 옅은 채움을 만든다)
        for k in ['total_num', 'total_label']:
            self.roles[k] = roles[k].most_common(1)[0][0] if roles[k] else None
        # 합계 행 색: 샘플 합계 행 채움 중 옅은 색(밝기 0.8 이상)만 인정
        self.total_color = None
        for k in ['total_num', 'total_label']:
            c = self.fill_of(self.roles[k][3]) if self.roles[k] else None
            if c and light(c):
                self.total_color = c
                break
        # 행 높이: 한 줄짜리 짧은 칸에서 가장 흔한 높이(크면 가장 작은 정상값). 내용이 넘치면 한글이 늘린다
        ok = {h: c for h, c in heights.items() if h > 600}
        if not ok:
            self.row_h = 1500
        else:
            common = max(ok, key=ok.get)
            self.row_h = common if common <= 2600 else min(ok)
        # 한 줄 높이 = 글자 크기 × 줄 간격 + 셀 위아래 여백. 샘플 값이 이보다 크면 줄인다(넘치면 한글이 늘림)
        try:
            _, pp, cp, _ = self.roles['num']
            size = int(self.charpr[cp].get('height'))
            ls = self.parapr[pp].find('.//hh:lineSpacing', NS)
            pct = int(ls.get('value')) if ls is not None and ls.get('type') == 'PERCENT' else 160
            tc = self.tbl.find('.//hp:tc', NS)
            m = tc.find('hp:cellMargin', NS) if tc.get('hasMargin') == '1' else self.tbl.find('hp:inMargin', NS)
            natural = int(size * pct / 100) + int(m.get('top')) + int(m.get('bottom'))
            self.row_h = min(self.row_h, max(natural, 800))
        except (KeyError, AttributeError, TypeError, ValueError):
            pass

    def fill_of(self, bf_id):
        e = self.borderfill.get(bf_id)
        w = e.find('.//hc:winBrush', NS) if e is not None else None
        c = w.get('faceColor') if w is not None else None
        return None if c in (None, 'none', '#FFFFFF', '#ffffff') else c

    def align(self, para_id):
        e = self.parapr.get(para_id)
        a = e.find('hh:align', NS) if e is not None else None
        return a.get('horizontal') if a is not None else 'JUSTIFY'

    # ------------------------------------------------------------ 그림
    def _figure_proto(self):
        """샘플에 그림틀(그림 1개 + 글자 없는 표)이 있으면 그걸, 없으면 None"""
        self.frame = None
        for p in self.P:
            t = top_tbl(p)
            if t is not None and p not in self.special and len(list(t.iter(HP + 'pic'))) == 1 \
                    and len(all_text(t).strip()) < 5:
                self.frame = p
                break
        self.box_bf = None
        for i, e in self.borderfill.items():
            if all(e.find('hh:' + s, NS).get('type') == 'SOLID'
                   for s in ['leftBorder', 'rightBorder', 'topBorder', 'bottomBorder']) and \
                    e.find('.//hc:winBrush', NS) is None:
                self.box_bf = i
                break

    def _pic_protos(self):
        pics = [x for x in self.S.iter(HP + 'pic')] + [x for _, S in self.sections[1:] for x in S.iter(HP + 'pic')]
        # 원형은 묶음(그룹)에 속하지 않고 위치·크기 요소가 있는 독립 그림만
        pics = [x for x in pics if x.get('groupLevel', '0') == '0' and x.find('hp:sz', NS) is not None
                and x.find('hp:pos', NS) is not None and x.find('hp:imgRect', NS) is not None
                and x.find('hp:renderingInfo', NS) is not None]
        body = [x for p in self.P if p not in self.special for x in p.findall('hp:run/hp:pic', NS)
                if x in pics and 0 < int(x.find('hp:curSz', NS).get('width') or 0) < 20000]
        std = E.parse(os.path.join(os.path.dirname(__file__), 'pic_proto.xml')).getroot()
        self.pic_any = pics[0] if pics else std
        self.pic_inline = body[0] if body else self.pic_any
        h = int(body[0].find('hp:curSz', NS).get('height')) if body else 1000
        self.inline_h = h if 300 < h < 3000 else 1000

    # ------------------------------------------------------------ 작은 글자(넓은 표)
    def _small_chars(self):
        self.smaller = {}
        for k, e in self.charpr.items():
            fr = e.find('hh:fontRef', NS).attrib
            cands = [o for o in self.charpr.values()
                     if int(o.get('height')) < int(e.get('height')) and o.find('hh:fontRef', NS).attrib == fr
                     and o.get('textColor') == e.get('textColor') and int(o.get('height')) >= 800]
            if cands:
                self.smaller[k] = max(cands, key=lambda o: int(o.get('height'))).get('id')

    def summary(self):
        sn = self.style_name
        return {
            'report_title': self.report_title,
            'sections': len(self.sections), 'secpr_orientations': ['가로' if k else '세로' for k in self.secpr],
            'cover': self.cover is not None, 'chapter': self.chap_num, 'chapter_title': self.chap_title,
            'chapter_kind': None if not self.chapter else ('도형/표' if (top_tbl(self.chapter[0]) is not None or shapes_of(self.chapter[0])) else '문단'),
            'headings': {lv: '%s %s (%s)' % (n, t, '표' if top_tbl(p) is not None else '도형') for lv, (p, n, t) in sorted(self.headings.items())},
            'heading_para_styles': {lv: c.most_common(1)[0][0] for lv, c in sorted(self.heading_style.items())},
            'has_tables': self.has_tables, 'table_width': self.tbl_w, 'row_height': self.row_h,
            'table_roles': {k: (sn.get(v[0]), v[3]) if v else None for k, v in self.roles.items()},
            'total_color': self.total_color,
            'figure_frame': self.frame is not None, 'box_borderfill': self.box_bf,
            'page_ctrls': [('앞:' if b else '') + ch.tag.split('}')[1] for b, c in self.page_ctrls for ch in c],
            'body_style': self.body_style,
            'kind_styles': {k: v.most_common(1)[0][0] for k, v in self.kind_style.items() if v},
        }
