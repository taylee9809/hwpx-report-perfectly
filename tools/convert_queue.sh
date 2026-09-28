#!/bin/sh
# 재조판 결과(버전 태그)를 한글로 하나씩 PDF 변환 + 썸네일. 원본 PDF가 없으면 원본도.
#   sh tools/convert_queue.sh v6 cross 7 1 6 4 2 3 5
export PYTHONIOENCODING=utf8 PYTHONUNBUFFERED=1
ver=$1; shift
conv(){ for try in 1 2; do out=$(python -m hwpx_restyle pdf "$1" "$2" 2>&1 | grep -E "pages=|OPEN FAIL" | head -1); sz=$(stat -c %s "$2" 2>/dev/null || echo 0); if [ "$sz" -gt 200000 ]; then echo "OK $(date +%H:%M) $out"; return; fi; echo "retry($try) $out size=$sz"; done; echo "FAIL $1"; }
for n in "$@"; do
  d=work/out/$n; [ "$n" = cross ] && d=work/out/cross_7to3
  conv $d/rebuilt_$ver.hwpx $d/rebuilt_$ver.pdf
  [ -f $d/rebuilt_$ver.pdf ] && python -m hwpx_restyle sheet $d/rebuilt_$ver.pdf $d/sheet_$ver >/dev/null
  if [ "$n" != cross ]; then
    tgt=$(ls work/samples/$n/*.hwpx | grep -v "/제1장")
    [ -f $d/original.pdf ] || conv "$tgt" $d/original.pdf
    [ -f $d/original.pdf ] && [ ! -f $d/sheet_original_001.png ] && python -m hwpx_restyle sheet $d/original.pdf $d/sheet_original >/dev/null
  fi
  echo "== $n done $(date +%H:%M)"
done
