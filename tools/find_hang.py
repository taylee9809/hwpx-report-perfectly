"""한글이 조판 중 멈추는 원인 블록을 이분 탐색으로 찾는다.
  python tools/find_hang.py 샘플.hwpx 중간폴더 시작 끝 [제한초=60]
각 단계: 구간을 반으로 → 각각 build + 한글 PDF(시간 제한) → 멈추는 쪽으로 계속.
둘 다 정상이면 '조합 문제'로 보고하고 멈춘다.
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from pdf_timeout import convert          # noqa: E402

tpl, mid, a, b = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
limit = int(sys.argv[5]) if len(sys.argv) > 5 else 60
work = os.path.join(os.path.dirname(os.path.abspath(mid)), 'find_hang')
os.makedirs(work, exist_ok=True)
doc = json.load(open(os.path.join(mid, 'content.json'), encoding='utf8'))
bl = doc['blocks']
keep = [x for x in bl[:5] if x['t'] in ('cover', 'chapter')]
img = os.path.join(work, 'images')
if not os.path.exists(img):
    shutil.copytree(os.path.join(mid, 'images'), img)


def hangs(lo, hi):
    d = dict(doc)
    d['blocks'] = keep + [x for x in bl[lo:hi] if x['t'] not in ('cover', 'chapter')]
    json.dump(d, open(os.path.join(work, 'content.json'), 'w', encoding='utf8'), ensure_ascii=False)
    out = os.path.join(work, 'r_%d_%d.hwpx' % (lo, hi))
    subprocess.run([sys.executable, '-m', 'hwpx_restyle', 'build', tpl, work, out], cwd=ROOT,
                   capture_output=True)
    res = convert(out, limit)
    print('  [%d,%d) %s' % (lo, hi, res), flush=True)
    return 'TIMEOUT' in res


lo, hi = a, b
print('시작 [%d,%d)' % (lo, hi), flush=True)
while hi - lo > 1:
    m = (lo + hi) // 2
    if hangs(lo, m):
        hi = m
    elif hangs(m, hi):
        lo = m
    else:
        print('두 반쪽 모두 정상 → 조합 문제 [%d,%d)' % (lo, hi), flush=True)
        break
else:
    print('원인 블록: %d' % lo, flush=True)
    print(json.dumps(bl[lo], ensure_ascii=False)[:1500], flush=True)
