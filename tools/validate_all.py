"""work/samples/<세트>/ 폴더마다: '제1장*' = 샘플, 나머지 = 재조판 대상.
각 대상을 샘플 서식으로 재조판하고(PDF·썸네일 포함) work/out/<세트>/<대상>/ 에 둔다.
요약은 work/out/summary.json

  python tools/validate_all.py [세트번호 ...]
"""
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sets = sys.argv[1:] or sorted(os.listdir(os.path.join(ROOT, 'work', 'samples')))
summary = {}
for s in sets:
    d = os.path.join(ROOT, 'work', 'samples', s)
    files = sorted(glob.glob(os.path.join(d, '*.hwpx')))
    tpl = next((f for f in files if os.path.basename(f).startswith('제1장')), None)
    if not tpl:
        summary[s] = '샘플(제1장*) 없음'
        continue
    for f in files:
        if f == tpl:
            continue
        name = os.path.splitext(os.path.basename(f))[0][:20]
        work = os.path.join(ROOT, 'work', 'out', s, name)
        r = subprocess.run([sys.executable, '-m', 'hwpx_restyle', 'run', tpl, f, work, '--pdf'],
                           cwd=ROOT, capture_output=True, text=True, encoding='utf8')
        summary['%s/%s' % (s, name)] = (r.stdout + r.stderr).strip().splitlines()[-6:]
        print(s, name, r.returncode)
json.dump(summary, open(os.path.join(ROOT, 'work', 'out', 'summary.json'), 'w', encoding='utf8'),
          ensure_ascii=False, indent=1)
