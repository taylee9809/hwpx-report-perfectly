"""재조판 결과가 원본 내용을 빠짐없이 담았는지 검사(한글 불필요).

원본 추출본(content.json)과, 재조판 hwpx를 다시 추출한 것을 블록 단위로 비교한다.
서식은 보지 않고 텍스트·표 격자·그림 수·장/절 번호만 본다.
"""
import json
import os
import re
import tempfile
from collections import Counter

from .extract import extract


def norm(s):
    return re.sub(r'[\s　 ]+', '', s or '')


def sig(b):
    t = b['t']
    if t == 'p':
        return ('p', norm(''.join(x for x in b['runs'] if isinstance(x, str))),
                sum(1 for x in b['runs'] if isinstance(x, dict)))
    if t == 'table':
        return ('table', tuple(tuple((norm(c['text']), c.get('cs', 1), c.get('rs', 1),
                                      sum(1 for ps in (c.get('runs') or []) for x in ps if isinstance(x, dict)))
                                     for c in r) for r in b['rows']))
    if t in ('sec', 'chapter'):
        return (t, b['num'], norm(b['title']))
    if t == 'cover':
        return ('cover', tuple(norm(x) for x in b['items']))
    if t == 'section':
        return ('section', b.get('landscape', False))
    return (t,)


def check(mid, rebuilt):
    a = json.load(open(os.path.join(mid, 'content.json'), encoding='utf8'))['blocks']
    with tempfile.TemporaryDirectory() as d:
        extract(rebuilt, d)
        b = json.load(open(os.path.join(d, 'content.json'), encoding='utf8'))['blocks']
    # 빈 문단은 비교에서 뺀다(간지 뒤 빈 문단 생략 등)
    fa = [sig(x) for x in a if not (x['t'] == 'p' and not sig(x)[1] and not sig(x)[2])]
    fb = [sig(x) for x in b if not (x['t'] == 'p' and not sig(x)[1] and not sig(x)[2])]
    ca, cb = Counter(fa), Counter(fb)
    missing = list((ca - cb).elements())
    extra = list((cb - ca).elements())
    order_ok = fa == fb
    return {
        'blocks_original': len(fa), 'blocks_rebuilt': len(fb), 'same_order': order_ok,
        'missing': [str(x)[:120] for x in missing[:20]], 'missing_n': len(missing),
        'extra': [str(x)[:120] for x in extra[:20]], 'extra_n': len(extra),
        'types_original': dict(Counter(x[0] for x in fa)), 'types_rebuilt': dict(Counter(x[0] for x in fb)),
    }
