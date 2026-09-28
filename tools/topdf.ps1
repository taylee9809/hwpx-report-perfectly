param([string]$src, [string]$pdf)
$hwp = New-Object -ComObject HWPFrame.HwpObject
$null = $hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
$hwp.XHwpWindows.Item(0).Visible = $false
$ok = $hwp.Open($src, "HWPX", "forceopen:true")
if (-not $ok) { Write-Output "OPEN FAIL $src"; $hwp.Quit(); exit 1 }
$pages = $hwp.PageCount
$null = $hwp.SaveAs($pdf, "PDF", "")
Write-Output "pages=$pages -> $pdf"
$hwp.Clear(1)
$hwp.Quit()
