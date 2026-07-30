# GEO 本地 Demo：API(8011) + 静态工作台(5176) + 可选诊断中心(5174)
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/start_local_geo_demo.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/start_local_geo_demo.ps1 -WithDiagnosticCenter

param(
  [switch]$WithDiagnosticCenter
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$GeoStatic = Join-Path $Root "frontend\public\deal-sniper-prototype"
$Frontend = Join-Path $Root "frontend"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { $VenvPython = "python" }

function Test-Port([int]$Port) {
  return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Ensure-GeoDemoHtml {
  $path = Join-Path $GeoStatic "geo-demo.html"
  $html = @"
<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>GEO 本地入口</title>
<style>
  body{font-family:"Segoe UI","PingFang SC",sans-serif;max-width:720px;margin:48px auto;padding:0 16px;color:#1e2330}
  a{color:#7c3aed} code{background:#f5f0ff;padding:2px 6px;border-radius:4px}
  li{margin:10px 0}
</style></head><body>
<h1>GEO 本地入口</h1>
<p>端口已错开，请收藏本页。</p>
<ul>
  <li><a href="/geo/dashboard.html?tenant_id=1&api_key=geo-demo-local-key&api_origin=http://127.0.0.1:8011">GEO 内容工作台（5176）</a></li>
  <li><a href="http://127.0.0.1:5174/diagnostic-center/">诊断中心（5174）</a></li>
  <li>API：<code>http://127.0.0.1:8011</code></li>
</ul>
<p>说明见仓库 <code>docs/LOCAL_GEO_DEMO.md</code>。</p>
</body></html>
"@
  Set-Content -Path $path -Value $html -Encoding UTF8
}

Ensure-GeoDemoHtml

if (-not (Test-Port 8011)) {
  Write-Host "Starting GEO API on :8011 ..."
  Start-Process -FilePath $VenvPython -ArgumentList @(
    "-m","uvicorn","app.geo_main:app","--host","127.0.0.1","--port","8011"
  ) -WorkingDirectory $Root -WindowStyle Minimized
  Start-Sleep -Seconds 3
} else {
  Write-Host "GEO API already on :8011"
}

if (-not (Test-Port 5176)) {
  Write-Host "Starting GEO static on :5176 ..."
  Start-Process -FilePath $VenvPython -ArgumentList @(
    "-m","http.server","5176","--bind","127.0.0.1"
  ) -WorkingDirectory $GeoStatic -WindowStyle Minimized
  Start-Sleep -Seconds 1
} else {
  Write-Host "GEO static already on :5176"
}

if ($WithDiagnosticCenter) {
  if (-not (Test-Port 5174)) {
    Write-Host "Starting diagnostic-center on :5174 ..."
    Start-Process -FilePath "npm" -ArgumentList @("run","dev:diagnostic-center") -WorkingDirectory $Frontend -WindowStyle Minimized
  } else {
    Write-Host "diagnostic-center already on :5174"
  }
}

Write-Host ""
Write-Host "GEO workbench:  http://127.0.0.1:5176/geo/dashboard.html?tenant_id=1&api_key=geo-demo-local-key&api_origin=http://127.0.0.1:8011"
Write-Host "GEO entry page: http://127.0.0.1:5176/geo-demo.html"
Write-Host "Diagnostic:     http://127.0.0.1:5174/diagnostic-center/  (use -WithDiagnosticCenter)"
Write-Host "API health:     http://127.0.0.1:8011/api/v1/geo/content-health"
Write-Host "Docs:           docs/LOCAL_GEO_DEMO.md"
