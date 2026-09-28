# .hwp -> .hwpx 변환 (한글 COM 필요)
param([string]$src, [string]$dst)
$hwp = New-Object -ComObject HWPFrame.HwpObject
$null = $hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
$hwp.XHwpWindows.Item(0).Visible = $false
if (-not $hwp.Open($src, "", "forceopen:true")) { Write-Output "OPEN FAIL $src"; $hwp.Quit(); exit 1 }
$null = $hwp.SaveAs($dst, "HWPX", "")
Write-Output "pages=$($hwp.PageCount) -> $dst"
$hwp.Clear(1)
$hwp.Quit()
