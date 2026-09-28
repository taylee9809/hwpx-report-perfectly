"""중간포맷을 블록 구간으로 잘라 새 중간폴더를 만든다(한글 멈춤 원인 찾기용).
  python tools/bisect_mid.py 원본mid 출력mid 시작 끝   (간지·장 제목은 항상 포함)
"""
import json, os, shutil, sys
src, dst, a, b = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
d = json.load(open(os.path.join(src, 'content.json'), encoding='utf8'))
bl = d['blocks']
keep = [x for x in bl[:5] if x['t'] in ('cover', 'chapter')]
part = [x for x in bl[a:b] if x['t'] not in ('cover', 'chapter')]
d['blocks'] = keep + part
os.makedirs(dst, exist_ok=True)
if not os.path.exists(os.path.join(dst, 'images')):
    shutil.copytree(os.path.join(src, 'images'), os.path.join(dst, 'images'))
json.dump(d, open(os.path.join(dst, 'content.json'), 'w', encoding='utf8'), ensure_ascii=False)
print(len(bl), '→', len(d['blocks']), [x['t'] for x in d['blocks']].count('section'), 'sections')
