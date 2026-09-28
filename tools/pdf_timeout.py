"""한글 PDF 변환을 시간 제한을 두고 실행. 제한을 넘기면 창 없는 Hwp.exe 를 종료하고 TIMEOUT 보고.
  python tools/pdf_timeout.py 초 입력.hwpx [입력2.hwpx ...]   → 같은 이름 .pdf
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS = os.path.join(ROOT, 'tools', 'topdf.ps1')


def kill_windowless_hwp():
    subprocess.run(['powershell', '-NoProfile', '-Command',
                    "Get-Process Hwp* -ErrorAction SilentlyContinue | "
                    "Where-Object { -not $_.MainWindowTitle } | Stop-Process -Force"],
                   capture_output=True)


def convert(src, limit):
    pdf = os.path.splitext(src)[0] + '.pdf'
    if os.path.exists(pdf):
        os.remove(pdf)
    t0 = time.time()
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', PS,
                            os.path.abspath(src), os.path.abspath(pdf)],
                           capture_output=True, text=True, timeout=limit)
        out = [l for l in (r.stdout + r.stderr).splitlines() if 'pages=' in l or 'OPEN FAIL' in l]
        size = os.path.getsize(pdf) if os.path.exists(pdf) else 0
        return '%s | %ds | %s | pdf %d bytes' % (os.path.basename(src), time.time() - t0,
                                                   out[0] if out else 'no output', size)
    except subprocess.TimeoutExpired:
        kill_windowless_hwp()
        return '%s | TIMEOUT %ds' % (os.path.basename(src), limit)


if __name__ == '__main__':
    limit = int(sys.argv[1])
    for f in sys.argv[2:]:
        print(convert(f, limit), flush=True)
