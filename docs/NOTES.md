# HWPX 구조 메모 · 함정

## 파일 구성
- `Contents/header.xml`: 글꼴, charPr(글자모양), paraPr(문단모양), borderFill(테두리·채움), style, numbering(표·그림 번호 형식)
- `Contents/section0.xml`: 본문. 첫 문단 첫 run에 `hp:secPr`(용지·여백·바탕쪽 참조)가 있어야 한다
- `Contents/masterpageN.xml`: 바탕쪽(머리글 장 제목, 쪽번호 `Ⅳ -`)
- `Contents/content.hpf`: 매니페스트. BinData 이미지를 `opf:item`으로 등록해야 한글이 읽는다
- `mimetype`은 무압축으로 zip 첫 항목에 둔다

## 단위
- HWPUNIT = 1/7200 inch. A4 폭 59528, 높이 84188
- 그림 `orgSz`와 `imgDim` = 픽셀 × 7200 / dpi (dpi 144면 ×50, 96이면 ×75)
- `curSz`와 `sz` = 표시 크기. `scaMatrix` e1 = cur/org

## 함정
- `hp:t` 정규식은 `<hp:t(?:\s[^>]*)?>`로 쓴다. `<hp:t` 로 쓰면 `<hp:tc`, `<hp:tbl`도 같이 잡힌다
- `hp:t` 안에 `<hp:fwSpace/>`(전각 공백), `<hp:lineBreak/>` 같은 자식이 있다. 텍스트는 자식의 tail까지 이어 붙여야 한다
- `hp:linesegarray`(줄 배치 캐시)는 생략해도 한글이 다시 계산한다
- 표를 `treatAsChar=1`(글자처럼 취급)로 두면 쪽에서 나뉘지 않는다. 표가 너무 길면 원본처럼 `<표 계속>`으로 나눠야 한다
- 표 행을 삭제할 때는 rowCnt, tbl 높이, rowAddr와 함께 **삭제 행을 덮는 세로 병합 셀의 rowSpan**까지 줄여야 한다. 안 하면 한글이 죽는다(0x800706BE)
- 셀 글자색·강조는 charPr 상속이라, 값만 바꾸면 강조가 엉뚱한 칸에 남는다
- lxml `attrib.update(**kw)`는 안 된다 → `el.set` 반복(common.sa)
- 한글 COM `SaveAs(path, "PDF", "")`는 동작하고, PowerShell에서 HAction FileSaveAs_S는 실패한다

## 스타일 체계 예시 (하수도정비 기본계획 보고서 계열)
`@제목장`(장), 1×2 표(절 박스 `4.1 | 총 설`), `1.1--`(4.2.1), `@가.`, `@1)`, `@가)`, `@①` + 각 `…내용`,
`@표번호-N`(빈 문단, 번호는 numbering 자동 `<표 4.N-k>`), `@표제목`, `@단위--`, `@주)`,
표 셀 `@표상단`(머리행·회색) `@표숫자`(오른쪽) `@표가운데` `@표좌정렬`(균등분할), `@그림제목-N`, 간지 `@_간지장`
