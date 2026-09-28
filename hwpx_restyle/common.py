import re
import lxml.etree as E

NS = {'hp': 'http://www.hancom.co.kr/hwpml/2011/paragraph',
      'hh': 'http://www.hancom.co.kr/hwpml/2011/head',
      'hc': 'http://www.hancom.co.kr/hwpml/2011/core',
      'opf': 'http://www.idpf.org/2007/opf/'}
HP = '{%s}' % NS['hp']
HC = '{%s}' % NS['hc']
SPECIAL = {'fwSpace': '　', 'nbSpace': ' ', 'tab': '\t', 'lineBreak': '\n', 'hyphen': '-'}
ROMAN = ['', 'Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ', 'Ⅵ', 'Ⅶ', 'Ⅷ', 'Ⅸ', 'Ⅹ', 'Ⅺ', 'Ⅻ']

# 장 제목: "제4장 처리구역별…", "제 4 장", "제４장"
CHAPTER_RE = re.compile(r'^\s*제[\s　]*(\d+)[\s　]*장[\s　]*(.*)$')
# 절 번호: "4.1", "4.10"
SEC_RE = re.compile(r'^\s*\d+\.\d+\s*$')
# 표 합계 행의 항목 칸: 계, 합계, 소계, 총계, 총 계, 합 계
TOTAL_RE = re.compile(r'^(?:총|합|소|누)?[\s\u3000]*계$')
# 표 안 숫자 칸
NUM_RE = re.compile(r'^[\s\-+△▲]*[\d,.]+\s*(%|‰|㎥|㎡|㎢|m|km|㎞|개소|개|인|명|세대|원|천원|백만원|억원|ha|mm|m/s|㎥/일)?\s*$'
                    r'|^[-–―]$|^[\d,.]+\s*[～~]\s*[\d,.]+$')


def t_text(t):
    s = t.text or ''
    for c in t:
        s += SPECIAL.get(c.tag.split('}')[1], '') + (c.tail or '')
    return s


def para_text(p):
    """문단(표·그림 내부 제외)의 텍스트"""
    return ''.join(t_text(t) for t in p.iterfind('hp:run/hp:t', NS))


def all_text(el):
    return ''.join(t_text(t) for t in el.iter(HP + 't'))


def is_num(s):
    s = s.replace('\n', '').strip()
    return bool(s) and bool(NUM_RE.match(s))


def top_tbl(p):
    """문단 바로 아래 run에 달린 표"""
    return p.find('hp:run/hp:tbl', NS)


def sa(el, **kw):
    for k, v in kw.items():
        el.set(k, str(v))


# ---------------------------------------------------------------- 제목 개체 판별
NUM_TOKEN = re.compile(r'^\d+(?:\.\d+)*\.?$')          # "1." "1.1" "1.1.1"
NUM_TITLE = re.compile(r'^(\d+(?:\.\d+)+\.?)\s+(\S.*)$')  # "1.1 개 요"
TOC_LINE = re.compile(r'^\d+(?:\.\d+)?\.?\s+\S')
SHAPE_TAGS = ('container', 'rect', 'ellipse', 'polygon', 'curve', 'arc')


def shapes_of(p):
    return [c for r in p.iterfind('hp:run', NS) for c in r if c.tag.split('}')[1] in SHAPE_TAGS]


def inner_paras(el):
    """el 안의 글자 문단(표 셀·글상자 문단) 텍스트 목록"""
    return [para_text(q).strip() for q in el.iter(HP + 'p') if para_text(q).strip()]


def level_of(num):
    return num.rstrip('.').count('.') + 1


def heading_of(el):
    """표·글상자가 장/절 제목이면 블록, 아니면 None"""
    tag = el.tag.split('}')[1]
    if tag == 'tbl':
        if el.find('.//hp:pic', NS) is not None or int(el.get('rowCnt')) > 1:
            return None
        cells = list(el.iter(HP + 'tc'))
        if len(cells) > 4:
            return None
        texts = [all_text(c).strip() for c in cells]
    else:
        texts = inner_paras(el)
    if not texts or len(' '.join(texts)) > 80:
        return None
    joined = ' '.join(t for t in texts if t)
    m = CHAPTER_RE.match(joined)
    if m:
        return {'t': 'chapter', 'num': m.group(1), 'title': m.group(2).strip()}
    nums = [t for t in texts if NUM_TOKEN.match(t)]
    rest = [t for t in texts if t and not NUM_TOKEN.match(t)]
    if len(nums) == 1 and rest and '.' in nums[0]:
        return {'t': 'sec', 'num': nums[0], 'title': ' '.join(rest)}
    if len(texts) == 1:
        m = NUM_TITLE.match(texts[0])
        if m and tag != 'tbl':
            return {'t': 'sec', 'num': m.group(1), 'title': m.group(2).strip()}
    return None


def toc_items(p):
    """문단에 달린 표·글상자 안의 절 목록(간지)"""
    items = []
    for el in p.findall('hp:run/hp:tbl', NS) + shapes_of(p):
        items += [t for t in inner_paras(el) if TOC_LINE.match(t) and len(t) < 60]
    return items


def report_title(z, section_roots):
    """머리말(header 조판 부호)·바탕쪽 글자 중 보고서 제목으로 보이는 가장 긴 글"""
    cands = []
    for n in z.namelist():
        if re.match(r'Contents/masterpage\d+\.xml$', n):
            M = E.fromstring(z.read(n))
            cands += [para_text(q).strip() for q in M.iter(HP + 'p')]
    for S in section_roots:
        for h in S.iter(HP + 'header'):
            cands += [para_text(q).strip() for q in h.iter(HP + 'p')]
    good = [c for c in cands if len(c) >= 6 and not CHAPTER_RE.match(c) and not re.match(r'^[\dⅠ-Ⅻ\s\-]+$', c)
            and not re.match(r'^장\s', c)]
    return max(good, key=len) if good else None
