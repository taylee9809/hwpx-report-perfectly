"""python -m hwpx_restyle <명령> ...

  inspect  <샘플.hwpx>                       샘플 서식 분석 결과 출력
  extract  <원본.hwpx> <중간폴더>              원본 → content.json + images/
  build    <샘플.hwpx> <중간폴더> <출력.hwpx> [--opts JSON]
  run      <샘플.hwpx> <원본.hwpx> <작업폴더>   extract + build (+ --pdf 면 PDF·썸네일)
  pdf      <입력.hwpx> <출력.pdf>              한글 COM 으로 PDF (Windows + 한글 필요)
  sheet    <입력.pdf> <접두어>                 쪽 썸네일 모음 PNG
  check    <중간폴더> <재조판.hwpx>             내용 보존 검사(텍스트·표·그림·제목)
  fit      <중간폴더> <재조판.pdf>              쪽 맞춤: 빈 쪽·홀로 남은 제목을 찾아 쪽 나눔 조정
"""
import argparse
import json
import os
import subprocess
import sys

from .extract import extract
from .build import build
from .template import Template
from .check import check

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools')


def to_pdf(src, pdf):
    ps = os.path.join(TOOLS, 'topdf.ps1')
    r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps,
                        os.path.abspath(src), os.path.abspath(pdf)], capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def sheet(pdf, prefix, per=12, cols=6, dpi=28):
    import fitz
    from PIL import Image
    d = fitz.open(pdf)
    outs = []
    for s in range(0, len(d), per):
        ims = []
        for i in range(s, min(len(d), s + per)):
            pm = d[i].get_pixmap(dpi=dpi)
            ims.append(Image.frombytes('RGB', (pm.width, pm.height), pm.samples))
        w, h = ims[0].size
        rows = (len(ims) + cols - 1) // cols
        sh = Image.new('RGB', (cols * (w + 6), rows * (h + 6)), 'gray')
        for k, im in enumerate(ims):
            sh.paste(im, ((k % cols) * (w + 6), (k // cols) * (h + 6)))
        fn = '%s_%03d.png' % (prefix, s + 1)
        sh.save(fn)
        outs.append(fn)
    return len(d), outs


def main(argv=None):
    for st in (sys.stdout, sys.stderr):        # Windows 콘솔 한글 깨짐 방지
        try:
            st.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog='hwpx_restyle', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['inspect', 'extract', 'build', 'run', 'pdf', 'sheet', 'check', 'fit'])
    ap.add_argument('args', nargs='+')
    ap.add_argument('--opts', default='{}', help='빌드 옵션 JSON (fig_h, fig_w, small_font_ratio, running_title)')
    ap.add_argument('--pdf', action='store_true', help='run: 결과를 PDF·썸네일로도 만든다')
    a = ap.parse_args(argv)
    opts = json.loads(a.opts)
    if a.cmd == 'inspect':
        print(json.dumps(Template(a.args[0]).summary(), ensure_ascii=False, indent=1))
    elif a.cmd == 'extract':
        print(extract(*a.args[:2]))
    elif a.cmd == 'build':
        summ, warn = build(*a.args[:3], opts=opts)
        print('\n'.join(sorted(set(warn))) or '경고 없음')
    elif a.cmd == 'run':
        tpl, src, work = a.args[:3]
        os.makedirs(work, exist_ok=True)
        mid = os.path.join(work, 'mid')
        print('extract', extract(src, mid))
        out = os.path.join(work, 'rebuilt.hwpx')
        summ, warn = build(tpl, mid, out, opts=opts)
        chk = check(mid, out)
        print('check: 누락 %d, 추가 %d, 순서동일 %s' % (chk['missing_n'], chk['extra_n'], chk['same_order']))
        json.dump({'template': summ, 'warnings': sorted(set(warn)), 'check': chk},
                  open(os.path.join(work, 'report.json'), 'w', encoding='utf8'), ensure_ascii=False, indent=1)
        print('build ->', out, '| 경고', len(set(warn)))
        if a.pdf:
            print(to_pdf(src, os.path.join(work, 'original.pdf')))
            print(to_pdf(out, os.path.join(work, 'rebuilt.pdf')))
            for n in ['original', 'rebuilt']:
                pdf = os.path.join(work, n + '.pdf')
                if os.path.exists(pdf):
                    print(n, sheet(pdf, os.path.join(work, 'sheet_' + n))[0], 'pages')
    elif a.cmd == 'pdf':
        print(to_pdf(*a.args[:2]))
    elif a.cmd == 'fit':
        from .fit import fit
        print(json.dumps(fit(*a.args[:2]), ensure_ascii=False, indent=1))
    elif a.cmd == 'check':
        print(json.dumps(check(*a.args[:2]), ensure_ascii=False, indent=1))
    elif a.cmd == 'sheet':
        print(sheet(*a.args[:2]))


if __name__ == '__main__':
    sys.exit(main())
