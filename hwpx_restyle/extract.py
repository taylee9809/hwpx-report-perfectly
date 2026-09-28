"""원본 hwpx → 중간포맷(content.json + images/)

서식은 버리고 다음만 남긴다.
  - 문단: 스타일 이름, 텍스트, 글머리 그림, 쪽 나눔 여부
  - 표: 셀 격자(텍스트·병합)
  - 그림: 이미지 파일
  - 간지(절 목록), 장 제목, 절 제목(번호·제목 — 표나 글상자에 들어 있어도)
  - 구역 경계(가로/세로)
"""
import json
import os
import re
import zipfile
from collections import Counter

import lxml.etree as E

from .common import (NS, HP, CHAPTER_RE, t_text, para_text, all_text, top_tbl, heading_of, shapes_of,
                     toc_items, report_title)

BIG_PIC_W = 20000   # 이보다 넓은 그림은 본문 그림(figure), 좁으면 글머리 그림


def equation_of(eq):
    """수식 개체 → {'eq': 스크립트, 속성들}. 수식은 헤더 서식을 참조하지 않는 독립 개체라 그대로 옮긴다"""
    a = {k: v for k, v in eq.attrib.items() if k not in ('id', 'zOrder')}
    d = {'eq': (eq.findtext('hp:script', default='', namespaces=NS) or ''), 'attr': a}
    for tag in ('sz', 'pos', 'outMargin'):
        e = eq.find('hp:' + tag, NS)
        if e is not None:
            d[tag] = dict(e.attrib)
    return d


def section_files(z):
    names = [n for n in z.namelist() if re.match(r'Contents/section\d+\.xml$', n)]
    return sorted(names, key=lambda n: int(re.findall(r'\d+', n)[0]))


class Extractor:
    def __init__(self, src, out):
        self.z = zipfile.ZipFile(src)
        self.out = out
        os.makedirs(os.path.join(out, 'images'), exist_ok=True)
        H = E.fromstring(self.z.read('Contents/header.xml'))
        self.stn = {e.get('id'): e.get('name') for e in H.iterfind('.//hh:style', NS)}
        hpf = self.z.read('Contents/content.hpf').decode('utf8')
        self.href = dict(re.findall(r'<opf:item id="([^"]+)" href="([^"]+)"', hpf))
        self.saved = set()
        self.sizes = {}     # 그림 파일 → 원본 문서의 원래 크기(orgSz). 그림 형식을 못 읽을 때 비율용

    # -- 이미지
    def img(self, pic):
        ref = pic.find('.//hc:img', NS).get('binaryItemIDRef')
        path = self.href.get(ref)
        if path is None:
            return None
        fn = os.path.basename(path)
        org = pic.find('hp:orgSz', NS)
        if org is not None and fn not in self.sizes:
            self.sizes[fn] = [int(org.get('width')), int(org.get('height'))]
        if fn not in self.saved:
            self.saved.add(fn)
            with open(os.path.join(self.out, 'images', fn), 'wb') as f:
                f.write(self.z.read(path))
        return fn

    @staticmethod
    def pic_w(pic):
        return int(pic.find('hp:curSz', NS).get('width') or 0)

    def runs(self, p):
        out = []
        for r in p.iterfind('hp:run', NS):
            for c in r:
                tag = c.tag.split('}')[1]
                if tag == 't':
                    s = t_text(c)
                    if out and isinstance(out[-1], str):
                        out[-1] += s
                    elif s:
                        out.append(s)
                elif tag == 'pic' and self.pic_w(c) < BIG_PIC_W:
                    fn = self.img(c)
                    if fn:
                        out.append({'img': fn})
                elif tag == 'equation':
                    out.append(equation_of(c))
        return out

    def grid(self, tbl):
        rows = []
        for tr in tbl.iterfind('hp:tr', NS):
            row = []
            for tc in tr.iterfind('hp:tc', NS):
                sp = tc.find('hp:cellSpan', NS)
                paras = list(tc.find('hp:subList', NS).iterfind('hp:p', NS))
                txt = '\n'.join(all_text(q) for q in paras).strip()
                cell = {'text': txt}
                # 칸 안에 수식·작은 그림이 있으면 문단별 글자 조각도 보관
                # (칸 안에 표·그리기 개체가 있으면 아직 구조 보존을 못 하므로 글자로만 둔다)
                nested = any(tc.find('.//hp:' + t, NS) is not None for t in ('tbl', 'container', 'rect', 'ellipse', 'polygon'))
                if not nested and (tc.find('.//hp:equation', NS) is not None or tc.find('.//hp:pic', NS) is not None):
                    cell['runs'] = [self.runs(q) for q in paras]
                if sp.get('colSpan') != '1':
                    cell['cs'] = int(sp.get('colSpan'))
                if sp.get('rowSpan') != '1':
                    cell['rs'] = int(sp.get('rowSpan'))
                row.append(cell)
            rows.append(row)
        return rows

    def table_block(self, tbl):
        h = heading_of(tbl)
        if h:
            return h
        pics = list(tbl.iter(HP + 'pic'))
        if pics and len(all_text(tbl).strip()) < 5:
            fn = self.img(max(pics, key=self.pic_w))
            return {'t': 'figure', 'img': fn} if fn else None
        return {'t': 'table', 'rows': self.grid(tbl)}

    def para_blocks(self, p):
        style = self.stn.get(p.get('styleIDRef'), '바탕글')
        txt = para_text(p).strip()
        m = CHAPTER_RE.match(txt)
        if m and len(txt) < 60 and top_tbl(p) is None:
            return [{'t': 'chapter', 'num': m.group(1), 'title': m.group(2).strip()}]
        new = []
        runs = self.runs(p)
        has_text = any((isinstance(x, str) and x.strip()) or isinstance(x, dict) for x in runs)
        # 글상자 제목(장·절)
        for sh in shapes_of(p):
            h = heading_of(sh)
            if h:
                new.append(h)
        tbls = p.findall('hp:run/hp:tbl', NS)
        bigpics = [x for x in p.findall('hp:run/hp:pic', NS) if self.pic_w(x) >= BIG_PIC_W]
        if has_text or not (tbls or bigpics or new):
            new.insert(0, {'t': 'p', 'style': style, 'runs': runs})
        for t in tbls:
            b = self.table_block(t)
            if b:
                new.append(b)
        for x in bigpics:
            fn = self.img(x)
            if fn:
                new.append({'t': 'figure', 'img': fn})
        return new

    def run(self):
        blocks = []
        for si, name in enumerate(section_files(self.z)):
            S = E.fromstring(self.z.read(name))
            P = list(S.iterfind('hp:p', NS))
            if si > 0:
                pp = S.find('.//hp:pagePr', NS)
                blocks.append({'t': 'section', 'landscape': pp is not None and pp.get('landscape') == 'NARROWLY'})
            for i, p in enumerate(P):
                # 간지: 장 제목이 나오기 전, 절 목록을 품은 표·글상자
                if not any(b['t'] in ('chapter', 'sec') for b in blocks):
                    items = toc_items(p)
                    if len(items) >= 2:
                        blocks.append({'t': 'cover', 'items': items})
                        continue
                new = self.para_blocks(p)
                if p.get('pageBreak') == '1' and new:
                    new[0]['pb'] = True
                blocks.extend(new)
        # 간지가 있으면 장 제목 앞의 나머지(배경 그림·빈 문단)는 간지 장식이므로 버린다
        ci = next((i for i, b in enumerate(blocks) if b['t'] == 'chapter'), None)
        if ci is not None and any(b['t'] == 'cover' for b in blocks[:ci]):
            pb = blocks[ci].get('pb')
            blocks = [b for b in blocks[:ci] if b['t'] == 'cover'] + blocks[ci:]
        return blocks


def extract(src, out):
    ex = Extractor(src, out)
    blocks = ex.run()
    roots = [E.fromstring(ex.z.read(n)) for n in section_files(ex.z)]
    # 바탕쪽 그림(장 제목 배너·옆 탭 등). 샘플 바탕쪽의 장별 그림을 이것으로 바꿔 끼운다
    master = []
    for n in sorted(x for x in ex.z.namelist() if re.match(r'Contents/masterpage\d+\.xml$', x)):
        M = E.fromstring(ex.z.read(n))
        for pic in M.iter(HP + 'pic'):
            fn = ex.img(pic)
            if fn and fn not in master:
                master.append(fn)
    doc = {'source': os.path.basename(src), 'report_title': report_title(ex.z, roots),
           'image_sizes': ex.sizes, 'master_images': master, 'blocks': blocks}
    with open(os.path.join(out, 'content.json'), 'w', encoding='utf8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return Counter(b['t'] for b in blocks), len(ex.saved)
