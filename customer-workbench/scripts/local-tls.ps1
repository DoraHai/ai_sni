param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$targetDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
if (-not $targetDirectory.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Certificate output must stay under TEMP' }
[IO.Directory]::CreateDirectory($targetDirectory) | Out-Null
$key = [Security.Cryptography.RSA]::Create(2048)
try {
  $request = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=UI12-loopback', $key, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
  $names = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
  $names.AddIpAddress([Net.IPAddress]::Parse('127.0.0.1'))
  $request.CertificateExtensions.Add($names.Build())
  $certificate = $request.CreateSelfSigned([DateTimeOffset]::UtcNow.AddMinutes(-1), [DateTimeOffset]::UtcNow.AddHours(12))
  try {
    [IO.File]::WriteAllText([IO.Path]::Combine($targetDirectory,'cert.pem'), $certificate.ExportCertificatePem())
    [IO.File]::WriteAllText([IO.Path]::Combine($targetDirectory,'key.pem'), $key.ExportPkcs8PrivateKeyPem())
  } finally { $certificate.Dispose() }
} finally { $key.Dispose() }
