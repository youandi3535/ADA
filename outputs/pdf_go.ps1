# ADA PDF - preview + dashboard reload in one (titanic default)
#
# Usage (from project root C:\IT\workspace_python\ADA):
#   .\outputs\pdf_go.ps1           # titanic (default)
#   .\outputs\pdf_go.ps1 telco     # telco (currently unused)
#
# (ASCII only on purpose: Windows PowerShell garbles non-ASCII .ps1 without BOM)

param([string]$sample = "titanic")

Write-Host "1/2  Rendering preview PDF ($sample) ..." -ForegroundColor Cyan
if ($sample -eq "telco") {
    docker exec -it ada-worker-output python -m outputs.dev_preview3
} else {
    docker exec -it ada-worker-output python -m outputs.dev_preview3 $sample
}

Write-Host "2/2  Restarting worker (dashboard reload) ..." -ForegroundColor Cyan
docker restart ada-worker-output | Out-Null

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  PDF : C:\IT\workspace_python\ADA\outputs\report_preview3_$sample.pdf"
Write-Host "  Site: press F5 in browser"
