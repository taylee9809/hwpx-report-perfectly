"""hwpx-restyle MCP 서버 (stdio).

CLI(python -m hwpx_restyle …)와 같은 기능을 MCP 도구로 노출한다.
  pip install -e .[mcp]
  hwpx-restyle-mcp          # 또는 python -m hwpx_restyle.mcp_server

클라이언트 설정 예(Claude Desktop / Claude Code):
  {"mcpServers": {"hwpx-restyle": {"command": "hwpx-restyle-mcp"}}}

경로는 모두 서버가 도는 PC의 절대경로다. PDF 변환(to_pdf)만 Windows + 한글(한컴오피스)이 필요하다.
"""
import json
import os
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .build import build as _build
from .check import check as _check
from .extract import extract as _extract
from .template import Template

mcp = FastMCP(
    'hwpx-restyle',
    instructions='샘플 HWPX 한 권의 서식으로 다른 보고서(텍스트·표 격자·그림)를 재조판한다. '
                 '흐름: extract(원본) → build(샘플, 중간폴더) → check. 쪽 배치 확인은 to_pdf → fit → build 반복.',
)


def _abs(p):
    return os.path.abspath(os.path.expanduser(p))


@mcp.tool()
def inspect_template(template_hwpx: str) -> dict:
    """샘플 hwpx 서식 분석 결과(장·절 제목 양식, 표 역할별 서식, 그림틀, 바탕쪽 조판 부호 등)를 돌려준다."""
    return Template(_abs(template_hwpx)).summary()


@mcp.tool()
def extract(source_hwpx: str, mid_dir: str) -> dict:
    """원본 hwpx에서 서식을 버리고 내용만 중간포맷(mid_dir/content.json + images/)으로 뽑는다."""
    counts, n_img = _extract(_abs(source_hwpx), _abs(mid_dir))
    return {'blocks': dict(counts), 'images': n_img, 'content_json': os.path.join(_abs(mid_dir), 'content.json')}


@mcp.tool()
def build(template_hwpx: str, mid_dir: str, out_hwpx: str, opts: Optional[dict] = None) -> dict:
    """중간포맷을 샘플 서식으로 조판해 out_hwpx를 만든다.
    opts 예: {"fig_h": 29500, "report_title": "…", "running_title": "…", "total_fill": "#F2F2F2"}"""
    summ, warn = _build(_abs(template_hwpx), _abs(mid_dir), _abs(out_hwpx), opts=opts or {})
    return {'out': _abs(out_hwpx), 'warnings': sorted(set(warn)), 'template': summ}


@mcp.tool()
def check(mid_dir: str, rebuilt_hwpx: str) -> dict:
    """재조판 결과가 원본 내용(텍스트·표 격자·그림 수·장/절 번호)을 빠짐없이 담았는지 검사한다. 한글 불필요."""
    return _check(_abs(mid_dir), _abs(rebuilt_hwpx))


@mcp.tool()
def run(template_hwpx: str, source_hwpx: str, work_dir: str, opts: Optional[dict] = None) -> dict:
    """extract → build → check 를 한 번에. work_dir/mid, work_dir/rebuilt.hwpx, work_dir/report.json 생성."""
    work = _abs(work_dir)
    os.makedirs(work, exist_ok=True)
    mid = os.path.join(work, 'mid')
    counts, n_img = _extract(_abs(source_hwpx), mid)
    out = os.path.join(work, 'rebuilt.hwpx')
    summ, warn = _build(_abs(template_hwpx), mid, out, opts=opts or {})
    chk = _check(mid, out)
    report = {'template': summ, 'warnings': sorted(set(warn)), 'check': chk}
    with open(os.path.join(work, 'report.json'), 'w', encoding='utf8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return {'out': out, 'mid': mid, 'blocks': dict(counts), 'images': n_img,
            'warnings': report['warnings'], 'check': chk}


@mcp.tool()
def fit(mid_dir: str, rebuilt_pdf: str) -> dict:
    """쪽 맞춤: 결과 PDF를 읽어 빈 쪽·쪽 끝에 홀로 남은 제목을 찾고 중간포맷의 쪽 나눔(pb)을 고친다.
    고친 뒤 build 를 다시 해야 반영된다. 보통 build → to_pdf → fit 을 2~3회 반복."""
    from .fit import fit as _fit
    return _fit(_abs(mid_dir), _abs(rebuilt_pdf))


@mcp.tool()
def to_pdf(hwpx: str, pdf: str) -> str:
    """hwpx → PDF (Windows + 한글 COM 필요). 동시에 여러 개를 돌리면 한글이 멈추므로 하나씩 호출한다."""
    from .__main__ import to_pdf as _to_pdf
    return _to_pdf(_abs(hwpx), _abs(pdf))


def main():
    if sys.platform == 'win32':          # 한글 경로·메시지 깨짐 방지
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding='utf-8')
            except (AttributeError, ValueError):
                pass
    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
