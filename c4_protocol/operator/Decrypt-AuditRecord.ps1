<#
.SYNOPSIS
    Decrypts the verification_record from a C4 Protocol audit report.

.DESCRIPTION
    Operator-side utility. Takes a fake audit report JSON (or just the base64
    verification_record blob) and decrypts it using the operator's P-256 private key.

    The encrypted blob format is:
        [Ephemeral SPKI public key (91 bytes)][IV (16 bytes)][AES ciphertext]

    The shared secret is derived via ECDH, then SHA-256 hashed to get the AES key.

.PARAMETER InputFile
    Path to a JSON file containing the audit report with verification_record field.

.PARAMETER Blob
    The base64 verification_record string directly.

.PARAMETER PrivateKeyFile
    Path to a DER file containing the P-256 private key (PKCS8 format).

.EXAMPLE
    .\Decrypt-AuditRecord.ps1 -InputFile report.json -PrivateKeyFile operator_private.der
    .\Decrypt-AuditRecord.ps1 -Blob "base64..." -PrivateKeyFile operator_private.der
#>
[CmdletBinding()]
param(
    [Parameter(ParameterSetName='File')]
    [string]$InputFile,

    [Parameter(ParameterSetName='Blob')]
    [string]$Blob,

    [Parameter(Mandatory)]
    [string]$PrivateKeyFile
)

# Resolve encrypted blob
if ($InputFile) {
    $report = Get-Content -Path $InputFile -Raw | ConvertFrom-Json
    $Blob = $report.verification_record
    if (-not $Blob) {
        Write-Error "No verification_record field found in input file."
        return
    }
}
if (-not $Blob) {
    Write-Error "Provide -InputFile or -Blob"
    return
}

# Load private key
$privKeyBytes = [System.IO.File]::ReadAllBytes((Resolve-Path $PrivateKeyFile))
$ecdh = [System.Security.Cryptography.ECDiffieHellman]::Create()
$ecdh.ImportPkcs8PrivateKey($privKeyBytes, [ref]$null)

# Parse combined blob
$combined = [Convert]::FromBase64String($Blob)

# Ephemeral public key is SPKI format (91 bytes for P-256)
$ephPubKeyLen = 91
$ivLen = 16

$ephPubKeyBytes = $combined[0..($ephPubKeyLen - 1)]
$iv = $combined[$ephPubKeyLen..($ephPubKeyLen + $ivLen - 1)]
$ciphertext = $combined[($ephPubKeyLen + $ivLen)..($combined.Length - 1)]

# Import ephemeral public key and derive shared secret
$ephKey = [System.Security.Cryptography.ECDiffieHellman]::Create()
$ephKey.ImportSubjectPublicKeyInfo($ephPubKeyBytes, [ref]$null)
$sharedSecret = $ecdh.DeriveKeyMaterial($ephKey.PublicKey)

# SHA-256 hash of shared secret = AES key
$sha = [System.Security.Cryptography.SHA256]::Create()
$aesKey = $sha.ComputeHash($sharedSecret)

# Decrypt with AES-256-CBC
$aes = [System.Security.Cryptography.Aes]::Create()
$aes.Key = $aesKey
$aes.IV = $iv
$aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
$aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7

$decryptor = $aes.CreateDecryptor()
$plainBytes = $decryptor.TransformFinalBlock($ciphertext, 0, $ciphertext.Length)

$plaintext = [System.Text.Encoding]::UTF8.GetString($plainBytes)

# Clean up
$ecdh.Dispose()
$ephKey.Dispose()
$sha.Dispose()
$aes.Dispose()
$decryptor.Dispose()

# Output — try to parse as JSON for pretty display
try {
    $parsed = $plaintext | ConvertFrom-Json
    $parsed | ConvertTo-Json -Depth 10
} catch {
    $plaintext
}
