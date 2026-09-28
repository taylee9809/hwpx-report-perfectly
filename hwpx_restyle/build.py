"""중간포맷(content.json + images/) + 샘플 hwpx → 새 hwpx

서식은 전부 샘플에서 가져온다. 샘플에 없는 요소는 샘플에 있는 가장 가까운 것으로 대신한다.
"""
import copy
import json
import os
import re
import zipfile
from collections import defaultdict

import lxml.etree as E
from PIL import Image

from .common import NS, HP, ROMAN, SPECIAL, TOC_LINE, TOTAL_RE, is_num, sa, level_of, para_text
from .template import Template

Image.MAX_IMAGE_PIXELS = None

DEFAULTS = {
    'fig_w': None,          # 그림 최대 폭(HWPUNIT). None이면 표 폭
    'fig_h': 29500,         # 그림 최대 높이. A4 한 쪽에 그림 2개 + 제목
    'small_font_ratio': 1.15,   # 필요 폭/표 폭이 이보다 크면 한 단계 작은 글자
    'running_title': None,  # 바탕쪽 장 제목(없으면 장 제목)
    'report_title': None,   # 머리말 보고서 제목(없으면 원본 문서의 것)
    'total_fill': '#F2F2F2',  # 샘플에 합계 행 채움이 없을 때 쓸 옅은 색
    'force_portrait': False,  # (진단용) 가로 구역도 세로로
    'float_rows': 15,       # 이 행 수 이상인 표는 글자처럼 취급 끔(쪽 남은 자리부터 이어짐)
}


def loose(s):
    """공백 무시 비교용 정규식: '총   설' ~ '총설'"""
    s = re.sub(r'\s+', '', s)
    return r'[\s　]*'.join(re.escape(c) for c in s)


def _segments(p):
    """문단 글자를 (노드, 속성, 글자) 조각으로. 특수문자 자식(fwSpace 등)은 편집 불가 조각."""
    segs = []
    for t in p.findall('hp:run/hp:t', NS):
        segs.append((t, 'text', t.text or ''))
        for c in t:
            segs.append((None, None, SPECIAL.get(c.tag.split('}')[1], '')))
            segs.append((c, 'tail', c.tail or ''))
    return segs


def retext(el, old_num, new_num, old_title, new_title):
    """el(문단·표·도형) 안 글자에서 번호와 제목만 바꾼다. 글자 조각(run) 서식은 유지."""
    for p in el.iter(HP + 'p'):
        if not p.findall('hp:run/hp:t', NS):
            continue
        if old_num is not None and new_num is not None:
            pats = [(old_num, new_num)]
            if old_num.isdigit() and new_num.isdigit():
                pats.insert(0, ('%02d' % int(old_num), '%02d' % int(new_num)))
            done = False
            for node, attr, txt in _segments(p):
                if done or node is None or not txt:
                    continue
                for o, n in pats:
                    rx = r'(?<![\d.])%s(?![\d])' % re.escape(o)
                    if re.search(rx, txt):
                        setattr(node, attr, re.sub(rx, n, txt, count=1))
                        done = True
                        break
        if old_title and new_title is not None:
            segs = _segments(p)
            full = ''.join(x[2] for x in segs)
            m = re.search(loose(old_title), full)
            if not m:
                continue
            a, b = m.span()
            pos, first = 0, True
            for node, attr, txt in segs:
                lo, hi = pos, pos + len(txt)
                pos = hi
                if node is None or hi <= a or lo >= b:
                    continue
                left = txt[:max(0, a - lo)]
                right = txt[b - lo:] if b < hi else ''
                setattr(node, attr, left + (new_title if first else '') + right)
                first = False
    return el


def wmf_size(path):
    """WMF(placeable) / EMF 머리에서 크기 → ((px), (HWPUNIT))"""
    import struct
    with open(path, 'rb') as f:
        head = f.read(88)
    if len(head) >= 22 and struct.unpack('<I', head[:4])[0] == 0x9AC6CDD7:
        l, t, r, b, inch = struct.unpack('<hhhhH', head[6:16])
        w, h = abs(r - l), abs(b - t)
        inch = inch or 1440
        return (w * 96 // inch, h * 96 // inch), (w * 7200 // inch, h * 7200 // inch)
    if len(head) >= 40 and struct.unpack('<I', head[:4])[0] == 1:      # EMF: rclFrame(0.01mm)
        l, t, r, b = struct.unpack('<iiii', head[24:40])
        w, h = abs(r - l), abs(b - t)
        return (w * 96 // 2540, h * 96 // 2540), (w * 7200 // 2540, h * 7200 // 2540)
    return None


class Builder:
    def __init__(self, template_path, mid, opts=None):
        self.T = Template(template_path)
        self.mid = mid
        self.o = dict(DEFAULTS, **(opts or {}))
        self.doc = json.load(open(os.path.join(mid, 'content.json'), encoding='utf8'))
        self._id = 1500000000
        self.bin = []
        self.img_ids = {}
        hpf = self.T.z.read('Contents/content.hpf').decode('utf8')
        nums = [int(x) for x in re.findall(r'<opf:item id="image(\d+)"', hpf)]
        self.next_img = max(nums or [0]) + 1
        self.warn = []
        self.chap = next((b for b in self.doc['blocks'] if b['t'] == 'chapter'), None)
        self.chapter_el = None
        self.new_bf = {}        # (원본 bf, 색) → 새 bf id
        self.new_bf_xml = []

    # ------------------------------------------------------------ 공통
    def nid(self):
        self._id += 1
        return str(self._id)

    def p(self, style_id, para, pb=False):
        return E.Element(HP + 'p', id='2147483648', paraPrIDRef=para, styleIDRef=style_id,
                         pageBreak='1' if pb else '0', columnBreak='0', merged='0')

    @staticmethod
    def text_run(p, cp, s):
        """줄바꿈·탭은 글자가 아니라 요소로 넣는다(날것 탭 문자는 한글 조판을 멈추게 한다)"""
        r = E.SubElement(p, HP + 'run', charPrIDRef=cp)
        t = E.SubElement(r, HP + 't')
        parts = re.split(r'([\n\t])', s)
        t.text = parts[0]
        for i in range(1, len(parts), 2):
            if parts[i] == '\n':
                el = E.SubElement(t, HP + 'lineBreak')
            else:
                el = E.SubElement(t, HP + 'tab', width='4000', leader='0', type='1')
            el.tail = parts[i + 1]
        return r

    def clone(self, p, pb):
        q = copy.deepcopy(p)
        q.set('pageBreak', '1' if pb else '0')
        for r in q.findall('hp:run', NS):          # 샘플의 구역 정의는 떼어낸다(구역 시작에서 따로 붙임)
            for c in list(r):
                if c.tag == HP + 'secPr' or (c.tag == HP + 'ctrl' and c.find('hp:colPr', NS) is not None):
                    r.remove(c)
        self.renumber(q)
        return q

    def renumber(self, q):
        for el in q.iter():
            if el.tag in (HP + 'tbl', HP + 'pic', HP + 'container', HP + 'rect', HP + 'ellipse',
                          HP + 'polygon', HP + 'line', HP + 'curve', HP + 'arc') and el.get('id') not in (None, '', '0'):
                el.set('id', self.nid())

    # ------------------------------------------------------------ 그림
    def reg_img(self, fn):
        if fn not in self.img_ids:
            k = 'image%d' % self.next_img
            self.next_img += 1
            self.img_ids[fn] = k
            self.bin.append((k, 'BinData/%s.%s' % (k, fn.rsplit('.', 1)[1].lower()), fn))
        return self.img_ids[fn]

    def img_size(self, fn):
        """(픽셀 크기, HWPUNIT 원래 크기)"""
        path = os.path.join(self.mid, 'images', fn)
        try:
            im = Image.open(path)
            dpi = im.info.get('dpi') or (96, 96)
            try:
                dx, dy = float(dpi[0]) or 96, float(dpi[1]) or 96
            except (TypeError, ValueError):
                dx = dy = 96
            if dx < 20 or dy < 20:
                dx = dy = 96
            return im.size, (round(im.size[0] * 7200 / dx), round(im.size[1] * 7200 / dy))
        except Exception:
            pass
        wmf = wmf_size(path)
        if wmf:
            return wmf
        sz = self.doc.get('image_sizes', {}).get(fn)
        if sz:
            return (sz[0] * 96 // 7200, sz[1] * 96 // 7200), tuple(sz)
        self.warn.append('그림 크기를 알 수 없음(4:3 가정): ' + fn)
        return (400, 300), (30000, 22500)

    def fit(self, fn, maxw, maxh):
        _, (ow, oh) = self.img_size(fn)
        s = min(maxw / ow, maxh / oh)
        return max(1, int(ow * s)), max(1, int(oh * s))

    def pic(self, fn, w, h, tmpl):
        (px, py), (ow, oh) = self.img_size(fn)
        pic = copy.deepcopy(tmpl)
        sa(pic, id=self.nid(), instid=self.nid(), textWrap='TOP_AND_BOTTOM')
        for tag, kw in [('hp:offset', dict(x=0, y=0)), ('hp:orgSz', dict(width=ow, height=oh)),
                        ('hp:curSz', dict(width=w, height=h)),
                        ('hp:rotationInfo', dict(centerX=w // 2, centerY=h // 2)),
                        ('hp:imgClip', dict(left=0, right=ow, top=0, bottom=oh)),
                        ('hp:imgDim', dict(dimwidth=ow, dimheight=oh)), ('hp:sz', dict(width=w, height=h)),
                        ('hp:pos', dict(treatAsChar=1, vertRelTo='PARA', horzRelTo='PARA', vertAlign='TOP',
                                        horzAlign='LEFT', vertOffset=0, horzOffset=0))]:
            el = pic.find(tag, NS)
            if el is not None:
                sa(el, **kw)
        ri = pic.find('hp:renderingInfo', NS)
        sa(ri.find('hc:transMatrix', NS), e1=1, e2=0, e3=0, e4=0, e5=1, e6=0)
        sa(ri.find('hc:scaMatrix', NS), e1='%.6f' % (w / ow), e2=0, e3=0, e4=0, e5='%.6f' % (h / oh), e6=0)
        pic.find('hc:img', NS).set('binaryItemIDRef', self.reg_img(fn))
        rect = pic.find('hp:imgRect', NS)
        for i, (x, y) in enumerate([(0, 0), (ow, 0), (ow, oh), (0, oh)]):
            sa(rect.find('hc:pt%d' % i, NS), x=x, y=y)
        sc = pic.find('hp:shapeComment', NS)
        if sc is not None:
            sc.text = '그림입니다.\n원본 그림의 이름: %s\n원본 그림의 크기: 가로 %dpixel, 세로 %dpixel' % (fn, px, py)
        return pic

    def equation(self, d):
        eq = E.Element(HP + 'equation', id=self.nid(), zOrder='0')
        for k, v in d.get('attr', {}).items():
            eq.set(k, v)
        for k, v in [('numberingType', 'EQUATION'), ('textWrap', 'TOP_AND_BOTTOM'), ('textFlow', 'BOTH_SIDES'),
                     ('lock', '0'), ('dropcapstyle', 'None'), ('version', 'Equation Version 60'),
                     ('baseLine', '85'), ('textColor', '#000000'), ('baseUnit', '1000'), ('lineMode', 'CHAR'),
                     ('font', 'HYhwpEQ')]:
            if eq.get(k) is None:
                eq.set(k, v)
        E.SubElement(eq, HP + 'sz', d.get('sz') or dict(width='3000', widthRelTo='ABSOLUTE', height='1500',
                                                         heightRelTo='ABSOLUTE', protect='0'))
        pos = dict(d.get('pos') or {})
        pos.update(treatAsChar='1')
        for k, v in [('affectLSpacing', '0'), ('flowWithText', '1'), ('allowOverlap', '0'), ('holdAnchorAndSO', '0'),
                     ('vertRelTo', 'PARA'), ('horzRelTo', 'COLUMN'), ('vertAlign', 'TOP'), ('horzAlign', 'LEFT'),
                     ('vertOffset', '0'), ('horzOffset', '0')]:
            pos.setdefault(k, v)
        E.SubElement(eq, HP + 'pos', pos)
        E.SubElement(eq, HP + 'outMargin', d.get('outMargin') or dict(left='56', right='56', top='0', bottom='0'))
        E.SubElement(eq, HP + 'script').text = d['eq']
        return eq

    def put_runs(self, p, cp, runs):
        """문자열·{'img'}·{'eq'} 조각을 문단 p 에 넣는다"""
        T = self.T
        if not runs:
            E.SubElement(p, HP + 'run', charPrIDRef=cp)
        for x in runs:
            if isinstance(x, str):
                self.text_run(p, cp, x)
            elif 'eq' in x:
                r = E.SubElement(p, HP + 'run', charPrIDRef=cp)
                r.append(self.equation(x))
                E.SubElement(r, HP + 't')
            elif 'img' in x and T.pic_inline is not None:
                (px, py), _ = self.img_size(x['img'])
                h = T.inline_h
                E.SubElement(p, HP + 'run', charPrIDRef=cp).append(
                    self.pic(x['img'], max(1, int(h * px / py)), h, T.pic_inline))

    # ------------------------------------------------------------ 문단
    def b_p(self, b):
        T = self.T
        text = ''.join(x for x in b['runs'] if isinstance(x, str))
        name = T.resolve_style(b['style'], text)
        if name != b['style']:
            self.warn.append('스타일 대체: %s → %s' % (b['style'], name))
        empty = not text.strip() and not any(isinstance(x, dict) for x in b['runs'])
        pp, cp = T.empty_proto(name) if empty else T.para_proto(name)
        p = self.p(T.style_id[name], pp, b.get('pb'))
        self.put_runs(p, cp, b['runs'])
        return [p]

    # ------------------------------------------------------------ 장·절·간지
    def b_chapter(self, b):
        T = self.T
        if T.chapter is None:
            self.warn.append('샘플에 장 제목 양식이 없어 문단으로 대신')
            return self.b_p({'style': T.heading_para_style(1), 'runs': ['제%s장 %s' % (b['num'], b['title'])],
                             'pb': b.get('pb')})
        p, on, ot = T.chapter
        el = retext(self.clone(p, b.get('pb')), on, b['num'], ot, b['title'])
        self.chapter_el = el
        return [el]

    def b_sec(self, b):
        T = self.T
        lv = level_of(b['num'])
        if lv in T.headings:
            p, on, ot = T.headings[lv]
            return [retext(self.clone(p, b.get('pb')), on, b['num'], ot, b['title'])]
        style = T.heading_para_style(lv)
        self.warn.append('샘플에 %d수준 제목 개체가 없어 문단(%s)으로 대신' % (lv, style))
        return self.b_p({'style': style, 'runs': ['%s %s' % (b['num'], b['title'])], 'pb': b.get('pb')})

    def b_cover(self, b):
        T = self.T
        if not T.cover_paras:
            self.warn.append('샘플에 간지가 없어 간지 생략')
            return []
        out = [self.clone(q, q.get('pageBreak') == '1') for q in T.cover_paras]
        for p in out:
            if self.chap:
                retext(p, T.chap_num, self.chap['num'], T.chap_title, self.chap['title'])
        # 절 목록 교체: 목록 문단 중 첫 것을 원형으로
        items = [q for p in out for q in p.iter(HP + 'p') if TOC_LINE.match(para_text(q).strip())]
        if items:
            tmpl = items[0]
            parent = tmpl.getparent()
            at = parent.index(tmpl)
            for q in items:
                q.getparent().remove(q)
            for i, s_ in enumerate(b['items']):
                q = copy.deepcopy(tmpl)
                ts = q.findall('hp:run/hp:t', NS)
                for t in ts:
                    for c in list(t):
                        t.remove(c)
                    t.text = ''
                if ts:
                    ts[0].text = s_
                parent.insert(at + i, q)
        return out

    # ------------------------------------------------------------ 표
    @staticmethod
    def text_w(s):
        return sum(560 if ord(ch) < 0x1100 else 1000 for ch in s)

    def b_table(self, b):
        T = self.T
        if T.tbl is None:
            self.warn.append('샘플에 표가 없어 표 생략')
            return []
        rows = b['rows']
        occ, cells, nc = set(), [], 0
        cell_runs = {}
        for r, row in enumerate(rows):
            c = 0
            for cell in row:
                while (r, c) in occ:
                    c += 1
                cs, rs = cell.get('cs', 1), cell.get('rs', 1)
                occ |= {(r + i, c + j) for i in range(rs) for j in range(cs)}
                cells.append((r, c, cs, rs, cell['text']))
                cell_runs[(r, c)] = cell.get('runs')
                c += cs
                nc = max(nc, c)
        nr = len(rows)
        if not cells:
            return []
        nhead = max([x[3] for x in cells if x[0] == 0] or [1])
        if nr > 1 and nhead >= nr:
            nhead = 1
        num_cols = {c for (r, c, cs, rs, t) in cells if r >= nhead and cs == 1 and is_num(t)}
        first_num = min(num_cols) if num_cols else nc

        pad = 2 * int(T.tbl.find('hp:inMargin', NS).get('left')) + 400
        need = [1500.0] * nc
        for (r, c, cs, rs, t) in cells:
            if cs == 1 and t:
                need[c] = max(need[c], max(self.text_w(x) for x in t.split('\n')) + pad)
        for (r, c, cs, rs, t) in cells:
            if cs > 1 and t:
                w = max(self.text_w(x) for x in t.split('\n')) + pad
                s = sum(need[c:c + cs])
                if s < w:
                    for k in range(c, c + cs):
                        need[k] += (w - s) / cs
        W = T.tbl_w
        tot = sum(need)
        if tot <= W:
            widths = [x * W / tot for x in need]
        else:
            lo, hi = 0.0, max(need)
            for _ in range(40):
                cap = (lo + hi) / 2
                if sum(min(x, cap) for x in need) > W:
                    hi = cap
                else:
                    lo = cap
            widths = [min(x, lo) for x in need]
            rest = W - sum(widths)
            widths = [x + rest * x / sum(widths) for x in widths]
        widths = [int(x) for x in widths]
        widths[-1] += W - sum(widths)
        small = tot > W * self.o['small_font_ratio']

        sid, spp, scp = T.tbl_anchor
        p = self.p(sid, spp, b.get('pb'))
        run = E.SubElement(p, HP + 'run', charPrIDRef=scp)
        src = T.tbl
        tbl = E.SubElement(run, HP + 'tbl', dict(src.attrib))
        sa(tbl, id=self.nid(), rowCnt=nr, colCnt=nc, repeatHeader=1, pageBreak='CELL', textWrap='TOP_AND_BOTTOM')
        for tag in ['sz', 'pos', 'outMargin', 'inMargin']:
            tbl.append(copy.deepcopy(src.find('hp:' + tag, NS)))
        # 긴 표는 글자처럼 취급을 끈다: 쪽 남은 자리부터 시작해 다음 쪽으로 이어진다
        if nr >= self.o['float_rows']:
            sa(tbl.find('hp:pos', NS), treatAsChar=0, flowWithText=1, allowOverlap=0, vertRelTo='PARA',
               horzRelTo='PARA', vertAlign='TOP', horzAlign='LEFT', vertOffset=0, horzOffset=0)
        else:
            sa(tbl.find('hp:pos', NS), treatAsChar=1)
        RH = T.row_h
        sa(tbl.find('hp:sz', NS), width=W, height=RH * nr)
        src_tc = src.find('.//hp:tc', NS)
        by_row = defaultdict(list)
        for x in cells:
            by_row[x[0]].append(x)
        # 합계 행: 앞쪽 항목 칸이 계·합계·소계·총계
        total_rows = {r for (r, c, cs, rs, t) in cells if r >= nhead and c < max(first_num, 1) and TOTAL_RE.match(t)}
        for r in range(nr):
            tr = E.SubElement(tbl, HP + 'tr')
            for (rr, c, cs, rs, t) in by_row[r]:
                if r < nhead:
                    role = 'head'
                elif not t:
                    role = 'empty'
                elif is_num(t) and cs == 1:
                    role = 'num'
                elif c < first_num and len(t) <= 4 and '\n' not in t and rs == 1:
                    role = 'label_short'
                elif c < first_num:
                    role = 'label'
                else:
                    role = 'text'
                st, pp, cp, bf = T.roles[role]
                if r in total_rows and not (rs > 1 and c < first_num and not TOTAL_RE.match(t)):
                    # 합계 행: 칸 테두리는 그대로, 채움만 옅은 색(샘플 합계색이 옅으면 그 색)
                    bf = self.filled_bf(bf, T.total_color or self.o['total_fill'])
                elif r >= nhead and T.fill_of(bf) and not (c < first_num and role.startswith('label')):
                    # 일반 내용 칸은 흰 바탕(샘플 숫자 칸에 색이 있어도)
                    bf = self.filled_bf(bf, '#FFFFFF')
                if len(t) > 4 and T.align(pp) == 'DISTRIBUTE':       # 긴 글에 균등 분할 금지
                    for alt in ('text', 'label', 'head'):
                        if T.align(T.roles[alt][1]) != 'DISTRIBUTE':
                            st, pp, cp = T.roles[alt][:3]
                            break
                if small:
                    cp = T.smaller.get(cp, cp)
                tc = E.SubElement(tr, HP + 'tc', dict(src_tc.attrib))
                tc.set('borderFillIDRef', bf)
                sl = E.SubElement(tc, HP + 'subList', dict(src_tc.find('hp:subList', NS).attrib))
                sl.set('vertAlign', 'CENTER')
                paras = cell_runs.get((r, c)) or [[line] for line in (t.split('\n') if t else [''])]
                for runs in paras:
                    q = E.SubElement(sl, HP + 'p', id='2147483648', paraPrIDRef=pp, styleIDRef=st,
                                     pageBreak='0', columnBreak='0', merged='0')
                    self.put_runs(q, cp, runs or [''])
                E.SubElement(tc, HP + 'cellAddr', colAddr=str(c), rowAddr=str(r))
                E.SubElement(tc, HP + 'cellSpan', colSpan=str(cs), rowSpan=str(rs))
                E.SubElement(tc, HP + 'cellSz', width=str(sum(widths[c:c + cs])), height=str(RH * rs))
                E.SubElement(tc, HP + 'cellMargin', dict(src_tc.find('hp:cellMargin', NS).attrib))
        E.SubElement(run, HP + 't')
        return [p]

    def filled_bf(self, base, color):
        """base 테두리에 채움 color 를 더한 borderFill(헤더에 새로 추가)"""
        key = (base, color)
        if key in self.new_bf:
            return self.new_bf[key]
        T = self.T
        e = copy.deepcopy(T.borderfill[base])
        nid = str(max(int(i) for i in T.borderfill) + 1 + len(self.new_bf))
        e.set('id', nid)
        for fb in e.findall('hc:fillBrush', NS):
            e.remove(fb)
        fb = E.SubElement(e, '{%s}fillBrush' % NS['hc'])
        E.SubElement(fb, '{%s}winBrush' % NS['hc'], faceColor=color, hatchColor='#FF000000', alpha='0')
        self.new_bf[key] = nid
        self.new_bf_xml.append(E.tostring(e, encoding='unicode'))
        return nid

    # ------------------------------------------------------------ 그림
    def b_figure(self, b):
        T = self.T
        if T.pic_any is None:
            self.warn.append('샘플에 그림 개체가 없어 그림 생략: ' + b['img'])
            return []
        if T.frame is not None:
            return [self.figure_in_frame(b)]
        return [self.figure_in_box(b)]

    def figure_in_frame(self, b):
        p = self.clone(self.T.frame, b.get('pb'))
        old = next(p.iter(HP + 'pic'))
        tc = next(a for a in old.iterancestors() if a.tag == HP + 'tc')
        cw = int(tc.find('hp:cellSz', NS).get('width'))
        ow = int(old.find('hp:curSz', NS).get('width'))
        oh = int(old.find('hp:curSz', NS).get('height'))
        w, h = self.fit(b['img'], min(ow, cw) if ow > 0 else cw, self.o['fig_h'])
        old.getparent().replace(old, self.pic(b['img'], w, h, old))
        dh = h - oh
        row = int(tc.find('hp:cellAddr', NS).get('rowAddr'))
        tbl = next(a for a in tc.iterancestors() if a.tag == HP + 'tbl')
        for c in tbl.iter(HP + 'tc'):
            if int(c.find('hp:cellAddr', NS).get('rowAddr')) == row:
                sz = c.find('hp:cellSz', NS)
                sz.set('height', str(max(100, int(sz.get('height')) + dh)))
        tsz = tbl.find('hp:sz', NS)
        tsz.set('height', str(max(100, int(tsz.get('height')) + dh)))
        return p

    def figure_in_box(self, b):
        T = self.T
        W = self.o['fig_w'] or T.tbl_w
        m = 283
        w, h = self.fit(b['img'], W - 2 * m, self.o['fig_h'])
        if T.tbl is None:                       # 샘플에 표도 없으면 가운데 문단에 그림만
            st = T.style_id.get(T.body_style, '0')
            pp, cp = T.para_proto(T.body_style)
            p = self.p(st, pp, b.get('pb'))
            r = E.SubElement(p, HP + 'run', charPrIDRef=cp)
            r.append(self.pic(b['img'], w, h, T.pic_any))
            return p
        sid, spp, scp = T.tbl_anchor
        p = self.p(sid, spp, b.get('pb'))
        run = E.SubElement(p, HP + 'run', charPrIDRef=scp)
        src = T.tbl
        tbl = E.SubElement(run, HP + 'tbl', dict(src.attrib))
        bf = T.box_bf or src.get('borderFillIDRef')
        sa(tbl, id=self.nid(), rowCnt=1, colCnt=1, borderFillIDRef=bf, repeatHeader=0, cellSpacing=0)
        for tag in ['sz', 'pos', 'outMargin', 'inMargin']:
            tbl.append(copy.deepcopy(src.find('hp:' + tag, NS)))
        sa(tbl.find('hp:pos', NS), treatAsChar=1)
        sa(tbl.find('hp:inMargin', NS), left=m, right=m, top=m, bottom=m)
        sa(tbl.find('hp:sz', NS), width=W, height=h + 2 * m)
        tr = E.SubElement(tbl, HP + 'tr')
        src_tc = src.find('.//hp:tc', NS)
        tc = E.SubElement(tr, HP + 'tc', dict(src_tc.attrib))
        tc.set('borderFillIDRef', bf)
        sl = E.SubElement(tc, HP + 'subList', dict(src_tc.find('hp:subList', NS).attrib))
        st, pp, cp, _ = T.roles['head']
        q = E.SubElement(sl, HP + 'p', id='2147483648', paraPrIDRef=pp, styleIDRef=st,
                         pageBreak='0', columnBreak='0', merged='0')
        r = E.SubElement(q, HP + 'run', charPrIDRef=cp)
        r.append(self.pic(b['img'], w, h, T.pic_any))
        E.SubElement(r, HP + 't')
        E.SubElement(tc, HP + 'cellAddr', colAddr='0', rowAddr='0')
        E.SubElement(tc, HP + 'cellSpan', colSpan='1', rowSpan='1')
        E.SubElement(tc, HP + 'cellSz', width=str(W), height=str(h + 2 * m))
        E.SubElement(tc, HP + 'cellMargin', left=str(m), right=str(m), top=str(m), bottom=str(m))
        E.SubElement(run, HP + 't')
        return p

    # ------------------------------------------------------------ 쪽 관련 조판 부호
    def page_ctrl_run(self, only_headers=False, before=None):
        T = self.T
        ctrls = []
        for b, c in T.page_ctrls:
            if before is not None and b != before:
                continue
            kinds = {ch.tag.split('}')[1] for ch in c}
            if only_headers and not kinds & {'header', 'footer'}:
                continue
            q = copy.deepcopy(c)
            if self.chap is not None:
                retext(q, T.chap_num, self.chap['num'], T.chap_title, self.chap['title'])
            self.retitle_report(q)
            ctrls.append(q)
        if not ctrls:
            return None
        run = E.Element(HP + 'run', charPrIDRef='0')
        for c in ctrls:
            run.append(c)
        return run

    def report_pair(self):
        old, new = self.T.report_title, self.doc.get('report_title')
        if self.o.get('report_title'):
            new = self.o['report_title']
        return (old, new) if old and new and old != new else (None, None)

    def retitle_report(self, el):
        old, new = self.report_pair()
        if old:
            retext(el, None, None, old, new)

    @staticmethod
    def attach(p, run):
        """문단 p 앞쪽(구역 정의 run 뒤)에 run 삽입"""
        i = 0
        for k, r in enumerate(p.findall('hp:run', NS)):
            if r.find('hp:secPr', NS) is not None:
                i = list(p).index(r) + 1
        run.set('charPrIDRef', (p.find('hp:run', NS).get('charPrIDRef') if p.find('hp:run', NS) is not None else '0'))
        p.insert(i, run)

    # ------------------------------------------------------------ 구역
    def secpr_run(self, landscape):
        T = self.T
        src = T.secpr.get(landscape)
        alt = T.secpr.get(not landscape)
        run = copy.deepcopy(src if src is not None else (alt if alt is not None else next(iter(T.secpr.values()))))
        for c in list(run):
            if not (c.tag == HP + 'secPr' or (c.tag == HP + 'ctrl' and c.find('hp:colPr', NS) is not None)):
                run.remove(c)
        if src is not None:
            return run
        run.find('hp:secPr/hp:pagePr', NS).set('landscape', 'NARROWLY' if landscape else 'WIDELY')
        self.warn.append('샘플에 %s 구역이 없어 방향만 바꿈' % ('가로' if landscape else '세로'))
        return run

    def sections_xml(self):
        gen = {'p': self.b_p, 'chapter': self.b_chapter, 'sec': self.b_sec, 'cover': self.b_cover,
               'table': self.b_table, 'figure': self.b_figure}
        blocks = list(self.doc['blocks'])
        if blocks and blocks[0]['t'] == 'cover':       # 간지 뒤 빈 문단 생략(다음 블록이 쪽 나눔을 이어받음)
            pb = False
            while len(blocks) > 1 and blocks[1]['t'] == 'p' and \
                    not any(isinstance(x, dict) or x.strip() for x in blocks[1]['runs']):
                pb = pb or blocks[1].get('pb', False)
                blocks.pop(1)
            if pb and len(blocks) > 1:
                blocks[1] = dict(blocks[1], pb=True)
        secs = [[False, []]]
        for b in blocks:
            if b['t'] == 'section':
                secs.append([b.get('landscape', False) and not self.o['force_portrait'], []])
                continue
            secs[-1][1].extend(gen[b['t']](b))
        out = []
        for i, (land, els) in enumerate(secs):
            if not els:
                els.append(self.p(self.T.style_id.get(self.T.body_style, '0'), '0'))
            if i == 0:
                target = self.chapter_el if self.chapter_el is not None else (els[1] if len(els) > 1 else els[0])
                jobs = [(els[0], self.page_ctrl_run(before=True)), (target, self.page_ctrl_run(before=False))]
            else:
                jobs = [(els[0], self.page_ctrl_run(only_headers=True))]
            for tgt, run in jobs:
                if run is not None and tgt is not None:
                    self.attach(tgt, run)
            first = els[0]
            first.insert(0, self.secpr_run(land))
            root = copy.deepcopy(self.T.S)
            for c in list(root):
                root.remove(c)
            for el in els:
                root.append(el)
            out.append(E.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True))
        return out

    # ------------------------------------------------------------ 장 번호 치환
    def chapter_fix(self, s, is_header):
        T = self.T
        if self.chap is None or T.chap_num is None:
            return s
        n, old = self.chap['num'], T.chap_num
        if is_header:
            return re.sub(r'(&lt;(?:표|그림)\s*)%s\.' % old, lambda m: m.group(1) + n + '.', s)
        root = E.fromstring(s.encode('utf8'))
        title = self.o['running_title'] or self.chap['title']
        retext(root, old, n, T.chap_title, title)
        ro, rn = self.report_pair()
        if ro:
            retext(root, None, None, ro, rn)
        out = E.tostring(root, encoding='unicode')
        if int(old) < len(ROMAN) and int(n) < len(ROMAN):
            out = re.sub(r'>%s(\s*-)' % ROMAN[int(old)], lambda m: '>' + ROMAN[int(n)] + m.group(1), out)
        head = s[:s.index('?>') + 2] if s.startswith('<?xml') else ''
        return head + out

    def master_swap(self, xml):
        """바탕쪽 XML의 장별 그림을 원본 문서의 것으로 교체"""
        import hashlib
        src = self.doc.get('master_images') or []
        if not src:
            return xml
        z = self.T.z
        hpf = dict(re.findall(r'<opf:item id="([^"]+)" href="([^"]+)"', z.read('Contents/content.hpf').decode('utf8')))

        def h(b):
            return hashlib.md5(b).hexdigest()
        src_hash = {h(open(os.path.join(self.mid, 'images', f), 'rb').read()): f for f in src}
        tpl_hash = set()
        root = E.fromstring(xml.encode('utf8'))
        pics = list(root.iter(HP + 'pic'))
        for pic in pics:
            ref = pic.find('.//hc:img', NS).get('binaryItemIDRef')
            if ref in hpf:
                tpl_hash.add(h(z.read(hpf[ref])))
        src_only = [f for hh, f in src_hash.items() if hh not in tpl_hash]
        if not src_only:
            return xml

        def ratio_of_file(f):
            (px, py), _ = self.img_size(f)
            return px / py if py else 1

        changed = False
        for pic in pics:
            img = pic.find('.//hc:img', NS)
            ref = img.get('binaryItemIDRef')
            if ref not in hpf:
                continue
            data = z.read(hpf[ref])
            if h(data) in src_hash:        # 두 문서 공통 장식 → 그대로
                continue
            try:
                import io
                im = Image.open(io.BytesIO(data))
                r0 = im.size[0] / im.size[1]
            except Exception:
                continue
            best = min(src_only, key=lambda f: abs(ratio_of_file(f) / r0 - 1))
            if abs(ratio_of_file(best) / r0 - 1) <= 0.15:
                img.set('binaryItemIDRef', self.reg_img(best))
                src_only.remove(best)
                changed = True
                self.warn.append('바탕쪽 그림 교체: %s → %s' % (ref, best))
                if not src_only:
                    break
        if not changed:
            return xml
        head = xml[:xml.index('?>') + 2] if xml.startswith('<?xml') else ''
        return head + E.tostring(root, encoding='unicode')

    def write(self, out):
        secs = self.sections_xml()
        z = self.T.z
        # 바탕쪽은 먼저 처리(그림을 새로 등록할 수 있어 매니페스트보다 앞서야 함)
        masters = {nm: self.master_swap(self.chapter_fix(z.read(nm).decode('utf8'), False)).encode('utf8')
                   for nm in z.namelist() if re.match(r'Contents/masterpage\d+\.xml$', nm)}
        hpf = z.read('Contents/content.hpf').decode('utf8')
        hpf = re.sub(r'<opf:item id="section\d+"[^>]*/>', '', hpf)
        hpf = re.sub(r'<opf:itemref idref="section\d+"[^>]*/>', '', hpf)
        items = ''.join('<opf:item id="%s" href="%s" media-type="image/%s" isEmbeded="1"/>'
                        % (k, h, h.rsplit('.', 1)[1]) for k, h, _ in self.bin)
        items += ''.join('<opf:item id="section%d" href="Contents/section%d.xml" media-type="application/xml"/>'
                         % (i, i) for i in range(len(secs)))
        hpf = hpf.replace('</opf:manifest>', items + '</opf:manifest>')
        refs = ''.join('<opf:itemref idref="section%d" linear="yes"/>' % i for i in range(len(secs)))
        hpf = hpf.replace('</opf:spine>', refs + '</opf:spine>')
        with zipfile.ZipFile(out, 'w') as o:
            written = set()
            for info in z.infolist():
                nm = info.filename
                if re.match(r'Contents/section\d+\.xml$', nm):
                    continue
                if nm == 'Contents/header.xml':
                    h = self.chapter_fix(z.read(nm).decode('utf8'), True)
                    if self.new_bf_xml:
                        h = h.replace('</hh:borderFills>', ''.join(self.new_bf_xml) + '</hh:borderFills>', 1)
                        h = re.sub(r'<hh:borderFills itemCnt="(\d+)"',
                                   lambda m: '<hh:borderFills itemCnt="%d"' % (int(m.group(1)) + len(self.new_bf_xml)), h, count=1)
                    h = re.sub(r'(<hh:head [^>]*secCnt=")\d+', lambda m: m.group(1) + str(len(secs)), h, count=1)
                    data = h.encode('utf8')
                elif nm in masters:
                    data = masters[nm]
                elif nm == 'Contents/content.hpf':
                    data = hpf.encode('utf8')
                else:
                    data = z.read(nm)
                o.writestr(info, data, compress_type=zipfile.ZIP_STORED if nm == 'mimetype' else zipfile.ZIP_DEFLATED)
                written.add(nm)
                if nm == 'Contents/header.xml':
                    for i, sx in enumerate(secs):
                        o.writestr('Contents/section%d.xml' % i, sx, compress_type=zipfile.ZIP_DEFLATED)
            for k, h, fn in self.bin:
                o.write(os.path.join(self.mid, 'images', fn), h, compress_type=zipfile.ZIP_STORED)
        return self.warn


def build(template, mid, out, opts=None):
    b = Builder(template, mid, opts)
    warn = b.write(out)
    return b.T.summary(), warn
