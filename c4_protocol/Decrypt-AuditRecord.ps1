<#
.SYNOPSIS
    Decrypts the verification_record from a C4 Protocol audit report.

.DESCRIPTION
    Operator-side utility. Takes a fake audit report JSON (or just the base64
    verification_record blob) and decrypts it using the operator's RSA private key.

    The encrypted blob format is:
        [RSA-encrypted AES key (256 bytes)][IV (16 bytes)][AES ciphertext]

.PARAMETER InputFile
    Path to a JSON file containing the audit report with verification_record field.

.PARAMETER Blob
    The base64 verification_record string directly.

.PARAMETER PrivateKeyFile
    Path to an XML file containing the RSA private key.

.PARAMETER PrivateKeyXml
    RSA private key as XML string.

.EXAMPLE
    .\Decrypt-AuditRecord.ps1 -InputFile report.json -PrivateKeyFile key.xml
    .\Decrypt-AuditRecord.ps1 -Blob "base64..." -PrivateKeyXml "<RSAKeyValue>..."
#>
[CmdletBinding()]
param(
    [Parameter(ParameterSetName='File')]
    [string]$InputFile,

    [Parameter(ParameterSetName='Blob')]
    [string]$Blob,

    [Parameter()]
    [string]$PrivateKeyFile,

    [Parameter()]
    [string]$PrivateKeyXml
)

# Resolve private key
if ($PrivateKeyFile) {
    $PrivateKeyXml = Get-Content -Path $PrivateKeyFile -Raw
}
if (-not $PrivateKeyXml) {
    Write-Error "Provide -PrivateKeyFile or -PrivateKeyXml"
    return
}

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

# Decrypt
$combined = [Convert]::FromBase64String($Blob)

$rsa = [System.Security.Cryptography.RSA]::Create()
$rsa.FromXmlString($PrivateKeyXml)

# RSA key size in bytes (e.g., 2048-bit key = 256 bytes)
$keySize = $rsa.KeySize / 8

$encryptedKey = $combined[0..($keySize - 1)]
$iv = $combined[$keySize..($keySize + 15)]
$ciphertext = $combined[($keySize + 16)..($combined.Length - 1)]

$aesKey = $rsa.Decrypt($encryptedKey, [System.Security.Cryptography.RSAEncryptionPadding]::OaepSHA256)

$aes = [System.Security.Cryptography.Aes]::Create()
$aes.KeySize = 256
$aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
$aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
$aes.Key = $aesKey
$aes.IV = $iv

$decryptor = $aes.CreateDecryptor()
$plainBytes = $decryptor.TransformFinalBlock($ciphertext, 0, $ciphertext.Length)

$plaintext = [System.Text.Encoding]::UTF8.GetString($plainBytes)

# Clean up
$rsa.Dispose()
$aes.Dispose()
$decryptor.Dispose()

# Output — try to parse as JSON for pretty display
try {
    $parsed = $plaintext | ConvertFrom-Json
    $parsed | ConvertTo-Json -Depth 10
} catch {
    $plaintext
}
