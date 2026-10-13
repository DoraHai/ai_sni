param([string]$PackageRoot='D:\SNIPERS国内版\production-executor\Nord-local-20261013-3acb7371\GsnipersExecutionDesk-production-win-x64-0.1.0-3acb7371e676', [string]$ParentRoot=(Join-Path $env:LOCALAPPDATA 'GsnipersExecutionDesk-production-Nord-20261013'))
$ErrorActionPreference='Stop'
$PackageRoot=[IO.Path]::GetFullPath($PackageRoot)
$ParentRoot=[IO.Path]::GetFullPath($ParentRoot)
$manifestPath=Join-Path $PackageRoot 'manifest.json'
if ((Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'c027750c13f6e5de56d3b16c05cbe0fd0a85286f8189e60c91ea565b872485bf') {throw 'Frozen package manifest mismatch'}
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.source_commit -ne '3acb7371e6765f8ccd535d654f2ddcaaae9ba8ce') {throw 'Wrong frozen executor'}
foreach ($artifact in $manifest.artifacts) {
  $artifactPath=[IO.Path]::GetFullPath((Join-Path $PackageRoot $artifact.name))
  if (!$artifactPath.StartsWith($PackageRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {throw 'Invalid artifact path'}
  if ((Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $artifact.sha256) {throw ('Artifact mismatch: '+$artifact.name)}
}
$env:NODE_TLS_REJECT_UNAUTHORIZED='1'
Remove-Item Env:ELECTRON_RUN_AS_NODE,Env:MHT_DISTRIBUTION_DEVICE_TOKEN,Env:NODE_EXTRA_CA_CERTS -ErrorAction SilentlyContinue
& (Join-Path $PackageRoot 'node_modules/electron/dist/electron.exe') (Join-Path $PSScriptRoot 'setup.cjs') $PackageRoot $ParentRoot
exit $LASTEXITCODE
