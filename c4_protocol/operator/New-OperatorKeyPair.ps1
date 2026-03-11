<#
.SYNOPSIS
    Generates an RSA key pair for C4 Protocol encrypted output.

.DESCRIPTION
    Creates a 2048-bit RSA key pair and saves:
    - Public key XML  → embed in the implant's $PublicKeyXml variable
    - Private key XML → keep on operator machine for decryption

.PARAMETER OutputDir
    Directory to write key files. Defaults to current directory.

.PARAMETER KeySize
    RSA key size in bits. Default 2048.

.EXAMPLE
    .\New-OperatorKeyPair.ps1
    .\New-OperatorKeyPair.ps1 -OutputDir ./keys -KeySize 4096
#>
[CmdletBinding()]
param(
    [string]$OutputDir = '.',
    [int]$KeySize = 2048
)

$rsa = [System.Security.Cryptography.RSA]::Create($KeySize)

$pubXml  = $rsa.ToXmlString($false)
$privXml = $rsa.ToXmlString($true)

$rsa.Dispose()

$pubFile  = Join-Path $OutputDir "operator_public_key.xml"
$privFile = Join-Path $OutputDir "operator_private_key.xml"

Set-Content -Path $pubFile  -Value $pubXml  -NoNewline
Set-Content -Path $privFile -Value $privXml -NoNewline

Write-Host "Public key:  $pubFile" -ForegroundColor Green
Write-Host "Private key: $privFile" -ForegroundColor Yellow
Write-Host ""
Write-Host "Embed the public key XML in the implant's `$PublicKeyXml variable."
Write-Host "Keep the private key for Decrypt-AuditRecord.ps1."
