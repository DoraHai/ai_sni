# GEO 本地 Demo：API + 静态台 + 可选 Vue / 诊断中心
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/start_local_geo_demo.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/start_local_geo_demo.ps1 -WithVue
#   powershell -ExecutionPolicy Bypass -File scripts/start_local_geo_demo.ps1 -WithVue -WithDiagnosticCenter
#   powershell -ExecutionPolicy Bypass -File scripts/start_local_geo_demo.ps1 -WithVue -SeedDemo

param(
  [switch]$WithVue,
  [switch]$WithDiagnosticCenter,
  [switch]$SeedDemo,
  [switch]$WithMainApi
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
  body{font-family:"Segoe UI","PingFang SC",sans-serif;max-width:760px;margin:48px auto;padding:0 16px;color:#1e2330}
  a{color:#7c3aed} code{background:#f5f0ff;padding:2px 6px;border-radius:4px}
  li{margin:10px 0} .warn{color:#b45309}
</style></head><body>
<h1>GEO 本地入口（可交付 Demo）</h1>
<p>端口错开；收藏本页。静态页必须带 <code>/geo/</code> 前缀。</p>
<ul>
  <li><strong>Vue 运营台</strong>：<a href="http://127.0.0.1:5173/geo/overview">http://127.0.0.1:5173/geo/overview</a>（需 <code>-WithVue</code>）</li>
  <li><strong>Vue 任务列表</strong>：<a href="http://127.0.0.1:5173/geo/tasks">/geo/tasks</a></li>
  <li><strong>静态工作台</strong>：<a href="/geo/dashboard.html?tenant_id=1&api_key=geo-demo-local-key&api_origin=http://127.0.0.1:8011">/geo/dashboard.html</a></li>
  <li class="warn">错误入口（404）：<code>/dashboard.html</code>（无 geo 前缀）</li>
  <li>GEO API：<code>http://127.0.0.1:8011</code> · 主站 API：<code>http://127.0.0.1:8000</code></li>
  <li>诊断中心：<a href="http://127.0.0.1:5174/diagnostic-center/">5174</a>（可选）</li>
</ul>
<p>交付清单：<code>docs/GEO_DELIVERY_CHECKLIST.md</code> · 联调：<code>docs/LOCAL_GEO_DEMO.md</code></p>
</body></html>
"@
  Set-Content -Path $path -Value $html -Encoding UTF8
}

Ensure-GeoDemoHtml

# Main API (Vue vite proxy default → 8000)
if ($WithMainApi -or $WithVue) {
  if (-not (Test-Port 8000)) {
    Write-Host "Starting main API on :8000 ..."
    Start-Process -FilePath $VenvPython -ArgumentList @(
      "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000"
    ) -WorkingDirectory $Root -WindowStyle Minimized
    Start-Sleep -Seconds 3
  } else {
    Write-Host "Main API already on :8000"
  }
}

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

if ($WithVue) {
  if (-not (Test-Port 5173)) {
    Write-Host "Starting Vue (vite) on :5173 ..."
    Start-Process -FilePath "npm" -ArgumentList @("run","dev") -WorkingDirectory $Frontend -WindowStyle Minimized
    Start-Sleep -Seconds 4
  } else {
    Write-Host "Vue already on :5173"
  }
}

if ($WithDiagnosticCenter) {
  if (-not (Test-Port 5174)) {
    Write-Host "Starting diagnostic-center on :5174 ..."
    Start-Process -FilePath "npm" -ArgumentList @("run","dev:diagnostic-center") -WorkingDirectory $Frontend -WindowStyle Minimized
  } else {
    Write-Host "diagnostic-center already on :5174"
  }
}

if ($SeedDemo) {
  Write-Host "Seeding demo data (verify ≥3 facts) ..."
  & $VenvPython -m scripts.seed_geo_demo --tenant-id 1 --verify-facts
}

Write-Host ""
Write-Host "=== GEO local demo ready ==="
Write-Host "Vue overview:   http://127.0.0.1:5173/geo/overview          (use -WithVue)"
Write-Host "Vue tasks:      http://127.0.0.1:5173/geo/tasks"
Write-Host "Static board:   http://127.0.0.1:5176/geo/dashboard.html?tenant_id=1&api_key=geo-demo-local-key&api_origin=http://127.0.0.1:8011"
Write-Host "Entry page:     http://127.0.0.1:5176/geo-demo.html"
Write-Host "API health:     http://127.0.0.1:8011/api/v1/geo/content-health"
Write-Host "Accept M1:      python scripts/accept_geo_m1.py"
Write-Host "Accept delivery:python scripts/accept_geo_delivery.py"
Write-Host "Checklist:      docs/GEO_DELIVERY_CHECKLIST.md"
