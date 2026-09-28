"""쪽 맞춤: 재조판 결과 PDF를 읽어 어색한 쪽 배치를 찾고, 중간포맷의 쪽 나눔(pb)을 고친다.

규칙(사용자 결정: 스타일보다 쪽 배치 우선)
  1. 원본에서 온 쪽 나눔 때문에 앞 쪽이 절반 넘게 비면 → 그 쪽 나눔을 없앤다
     (장 제목·1수준 제목·간지 뒤는 유지)
  2. 쪽 끝에 표 제목·단위·표 번호만 홀로 남으면 → 그 제목 블록에 쪽 나눔을 건다(표와 함께 다음 쪽)
  3. 제목(절·항) 문단이 쪽 끝에 홀로 남으면 → 같은 처리

사용: python -m hwpx_restyle fit <중간폴더> <재조판.pdf>  → 중간폴더/content.json 을 고치고 보고
반복: build → pdf → fit 를 변화가 없을 때까지(보통 2~3회)
"""
import json
import os
import re

from .template import kind_of

CAPTION_KINDS = ('tcap', 'fcap', 'unit', 'tcont')
HEAD_KINDS = ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8')


def norm(s):
    return re.sub(r'[\s　 ]+', '', s or '')


def block_key(b):
    """PDF 에서 블록을 찾을 때 쓸 글자 열쇠(앞 16자)"""
    t = b['t']
    if t == 'p':
        s = ''.join(x for x in b['runs'] if isinstance(x, str))
    elif t == 'table':
        s = ''.join(c['text'] for r in b['rows'][:2] for c in r if c['text'])
    elif t in ('sec', 'chapter'):
        s = b['title']
    else:
        return None
    s = norm(s)
    return s[:16] if len(s) >= 4 else None


def page_info(pdf):
    """쪽마다 (본문 글자 이어붙인 것, 채움 비율, 마지막 줄 글자)"""
    import fitz
    d = fitz.open(pdf)
    out = []
    for pg in d:
        H = pg.rect.height
        top, bot = H * 0.10, H * 0.92          # 머리말·꼬리말 영역 제외
        lines = []
        for x0, y0, x1, y1, txt, *_ in pg.get_text('blocks'):
            if y0 >= top and y1 <= bot and txt.strip():
                lines.append((y0, y1, txt))
        imgs = [r for r in (i['bbox'] for i in pg.get_image_info()) if r[1] >= top and r[3] <= bot]
        ys = [l[1] for l in lines] + [r[3] for r in imgs]
        fill = (max(ys) - top) / (bot - top) if ys else 0.0
        lines.sort()
        text = norm(''.join(l[2] for l in lines))
        last = norm(lines[-1][2]) if lines else ''
        out.append({'text': text, 'fill': round(fill, 2), 'last': last})
    return out


def locate(blocks, pages):
    """블록 → 시작 쪽 번호(찾을 수 있는 것만). 순서대로 앞에서부터 찾는다."""
    where = {}
    pi = 0
    for i, b in enumerate(blocks):
        k = block_key(b)
        if not k:
            continue
        for j in range(pi, min(len(pages), pi + 6)):
            if k in pages[j]['text']:
                where[i] = j
                pi = j
                break
    return where


def fit(mid, pdf, empty_limit=0.5):
    path = os.path.join(mid, 'content.json')
    doc = json.load(open(path, encoding='utf8'))
    blocks = doc['blocks']
    pages = page_info(pdf)
    where = locate(blocks, pages)
    changes = []
    for i, b in enumerate(blocks):
        if i not in where:
            continue
        pg = where[i]
        # 규칙 1: 쪽 나눔 때문에 앞 쪽이 많이 빔
        if b.get('pb') and pg > 0 and b['t'] not in ('chapter', 'cover', 'section'):
            is_top = b['t'] == 'sec' and b['num'].count('.') <= 1 and not b['num'].endswith('.')
            if not is_top and pages[pg - 1]['fill'] < empty_limit:
                b['pb'] = False
                changes.append('쪽 나눔 해제: %d쪽이 %.0f%%만 참 → [%s] %s' %
                               (pg, pages[pg - 1]['fill'] * 100, b['t'], block_key(b)))
    # 규칙 2·3: 쪽 끝에 홀로 남은 제목·표 제목
    for i, b in enumerate(blocks):
        if b['t'] not in ('p', 'sec') or b.get('pb'):
            continue
        k = block_key(b)
        if not k or i not in where:
            continue
        pg = where[i]
        kind = kind_of(''.join(x for x in b['runs'] if isinstance(x, str))) if b['t'] == 'p' else 'h2'
        is_cap = kind in CAPTION_KINDS or 'Title' in b.get('style', '') or '표제목' in b.get('style', '') \
            or '표번호' in b.get('style', '') or '그림제목' in b.get('style', '')
        if not (is_cap or kind in HEAD_KINDS or b['t'] == 'sec'):
            continue
        last = pages[pg]['last']
        # 이 블록이 쪽 마지막 줄이고, 다음 블록(표·그림·본문)이 다음 쪽에서 시작
        nxt = next((j for j in range(i + 1, min(len(blocks), i + 6)) if j in where), None)
        if last.startswith(k[:8]) and nxt is not None and where[nxt] > pg:
            # 캡션 묶음(번호·제목·단위)은 맨 앞 것에 건다
            j = i
            while j > 0 and blocks[j - 1]['t'] == 'p' and kind_of(
                    ''.join(x for x in blocks[j - 1]['runs'] if isinstance(x, str))) in CAPTION_KINDS + ('empty',) \
                    and ('표' in blocks[j - 1].get('style', '') or not ''.join(
                        x for x in blocks[j - 1]['runs'] if isinstance(x, str)).strip()):
                j -= 1
            blocks[j]['pb'] = True
            changes.append('다음 쪽으로: %d쪽 끝에 홀로 남은 [%s] %s' % (pg + 1, b['t'], k))
    if changes:
        json.dump(doc, open(path, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    near_empty = [i + 1 for i, p in enumerate(pages) if p['fill'] < 0.35 and i > 1]
    return {'pages': len(pages), 'changes': changes, 'near_empty_pages': near_empty[:40],
            'located': '%d/%d' % (len(where), sum(1 for b in blocks if block_key(b)))}
