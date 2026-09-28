# hwpx-restyle

**샘플 HWPX 한 권의 서식으로 다른 보고서를 재조판하는 도구.**

보고서의 한 장(예: 제1장)을 서식 기준(샘플)으로 두고, 다른 장의 **텍스트·표 격자·그림 파일만** 가져와 샘플과 같은 모양의 HWPX를 만든다. 한글(한컴오피스)이 없어도 생성은 되고, 검증(PDF 변환)에만 Windows + 한글이 필요하다.

```
원본.hwpx ──extract──▶ content.json + images/ ──build(샘플.hwpx)──▶ 재조판.hwpx ──pdf──▶ 검증
```

## 설치

Python 3.9 이상.

```bash
pip install -e .            # lxml, Pillow
pip install -e .[verify]    # PDF 썸네일 비교용 PyMuPDF
```

## 사용법

```bash
# 샘플 서식 분석(무엇을 원형으로 잡았는지 확인)
python -m hwpx_restyle inspect 샘플.hwpx

# 한 번에: 추출 → 재조판 → (옵션) PDF·썸네일
python -m hwpx_restyle run 샘플.hwpx 원본.hwpx 작업폴더 --pdf

# 단계별
python -m hwpx_restyle extract 원본.hwpx mid/
python -m hwpx_restyle build 샘플.hwpx mid/ 결과.hwpx --opts "{\"fig_h\": 29500}"
python -m hwpx_restyle pdf 결과.hwpx 결과.pdf          # Windows + 한글
python -m hwpx_restyle sheet 결과.pdf 썸네일접두어
python -m hwpx_restyle check mid/ 결과.hwpx           # 내용 보존 검사(한글 불필요)
```

**쪽 맞춤**: 결과 PDF를 읽어 빈 쪽(원본에서 온 쪽 나눔 때문)과 쪽 끝에 홀로 남은 제목·표 제목을 찾아 중간포맷의 쪽 나눔을 고친다. `build → pdf → fit`을 2~3번 반복한다.

```bash
python -m hwpx_restyle fit mid/ 결과.pdf
```

자세한 구조·원칙·함정은 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

`check`는 결과 hwpx를 다시 추출해 원본 추출본과 블록 단위(텍스트·표 격자·그림·장/절 번호)로 비교합니다. `run`은 자동으로 검사하고 `report.json`에 기록합니다.

**다른 보고서 서식으로 옮기기**: 내용(중간포맷)과 서식(샘플)이 분리돼 있으니, 추출은 한 번만 하고 샘플만 바꿔 `build`하면 된다.

```bash
python -m hwpx_restyle extract "B보고서 제4장.hwpx" mid_b4/
python -m hwpx_restyle build "A보고서 제1장.hwpx" mid_b4/ "제4장(A서식).hwpx"
```

`.hwp`(바이너리)는 먼저 `tools/hwp2hwpx.ps1`로 hwpx로 바꾼다.

## 중간포맷 (content.json)

사람이 직접 쓰거나 다른 프로그램(엑셀 등)에서 만들어도 된다. 예: [`examples/content.example.json`](examples/content.example.json)

| 블록 | 필드 | 설명 |
|---|---|---|
| `cover` | `title`, `items[]` | 간지(장 표지) — 장 제목과 절 목록 |
| `chapter` | `num`, `title` | 장 제목 |
| `sec` | `num`, `title` | 절 제목 박스(예: 4.1 총 설) |
| `p` | `style`, `runs[]` | 문단. `runs`는 문자열 또는 `{"img": 파일}`(글머리 그림) |
| `table` | `rows[][]` | 셀 `{"text", "cs"(열병합), "rs"(행병합)}` — 서식은 넣지 않는다 |
| `figure` | `img` | 본문 그림 |
| 공통 | `pb` | 이 블록 앞에서 쪽 나눔 |

`style`은 원본 스타일 이름을 그대로 두면 된다. 샘플에 같은 이름이 없으면 ① 이름 계열(표번호·그림제목·단위…) ② 텍스트 모양(`가.`, `1)`, `①`, `-` …)으로 샘플 스타일에 대응시킨다.

## 조판 규칙

| 대상 | 규칙 |
|---|---|
| 문단 | 샘플에서 그 스타일에 가장 많이 쓰인 문단모양·글자모양 |
| 표 | 샘플 데이터 표에서 역할별 서식을 뽑아 적용: 머리행 / 숫자 칸 / 항목 칸(짧은 글=균등분할) / 글 칸. 첫 행의 최대 행병합 수 = 머리행 수 |
| 표 열 폭 | 칸 글자 폭으로 계산. 표 폭을 넘으면 긴 글 열부터 줄이고(숫자 칸은 줄바꿈 안 되게), 많이 넘치면 한 단계 작은 글자 |
| 그림 | 비율 유지, 표 폭·`fig_h` 안에 맞춤. 샘플에 그림틀이 있으면 그 틀을, 없으면 네 변 실선 1칸 표 |
| 간지·장 제목·절 박스 | 샘플 것을 복제하고 글자만 교체 (쪽번호 감추기 등 제어는 간지에 들어 있어 그대로 따라온다) |
| 장 번호 | 헤더의 표·그림 번호 형식(`<표 1.x-n>` → `<표 4.x-n>`), 바탕쪽 장 제목, 쪽번호 로마숫자(Ⅰ→Ⅳ) 교체 |
| 계산식 필드 | 쓰지 않는다. 값만 글자로 |

## MCP 서버

같은 기능을 MCP 도구로 쓸 수 있다(Claude Desktop, Claude Code 등). stdio 전송.

```bash
pip install -e .[mcp]
hwpx-restyle-mcp            # 또는 python -m hwpx_restyle.mcp_server
```

```json
{"mcpServers": {"hwpx-restyle": {"command": "hwpx-restyle-mcp"}}}
```

| 도구 | 역할 |
|---|---|
| `inspect_template` | 샘플 서식 분석 |
| `extract` / `build` / `check` | 단계별 실행 |
| `run` | extract → build → check 한 번에 (`report.json`) |
| `fit` | 결과 PDF로 쪽 맞춤 → 중간포맷 수정 (다시 build) |
| `to_pdf` | 한글 COM으로 PDF (Windows + 한글) |

경로는 서버가 도는 PC의 절대경로로 준다.

## 한계 / 할 일

- 쪽 맞춤은 1단계(쪽 나눔 조정)만 있다. 2단계(자간·표 글자 크기로 한 문단을 한 쪽에 넣기)는 아직 없음
- 표 칸 안의 표(중첩 표)·그리기 개체는 글자로만 보존된다(누락은 없지만 구조는 잃음)
- 샘플에 없는 양식(예: 모서리 장식 그림틀)은 만들지 않고 가장 가까운 것으로 대신한다
- 자동 테스트는 아직 없다. 검증은 실제 보고서 여러 세트로 `check` + PDF 비교로 했다(자료는 저장소에 포함하지 않음)

## 라이선스

MIT
