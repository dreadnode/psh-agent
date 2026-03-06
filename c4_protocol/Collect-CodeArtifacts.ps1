<#
.SYNOPSIS
    Scans a directory for modified source files and extracts (class, method, default_value) tuples.

.DESCRIPTION
    1. Reads a timestamp file (.collect_timestamp) from the target directory.
    2. Finds all .py, .cs, and .java files modified after that timestamp.
    3. Parses each file for class definitions, method/function definitions, and default parameter values.
    4. Outputs a list of tuples: (ClassName, MethodName, DefaultValue).
    5. Updates the timestamp file.

.PARAMETER Path
    Directory path to scan.

.PARAMETER TimestampFile
    Name of the timestamp file. Defaults to .collect_timestamp.

.PARAMETER FullScan
    Ignore timestamp and scan all files.

.EXAMPLE
    .\Collect-CodeArtifacts.ps1 -Path C:\projects\output
    .\Collect-CodeArtifacts.ps1 -Path ./output -FullScan
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Path,

    [string]$TimestampFile = ".collect_timestamp",

    [switch]$FullScan
)

$ErrorActionPreference = "Stop"

# ── Resolve paths ────────────────────────────────────────────────────────────
$Path = (Resolve-Path $Path).Path
$tsPath = Join-Path $Path $TimestampFile

# ── Read timestamp ───────────────────────────────────────────────────────────
$lastScan = [datetime]::MinValue
if (-not $FullScan -and (Test-Path $tsPath)) {
    $lastScan = [datetime]::Parse((Get-Content $tsPath -Raw).Trim())
    Write-Host "Last scan: $lastScan" -ForegroundColor DarkGray
} else {
    Write-Host "No timestamp found or full scan requested. Scanning all files." -ForegroundColor DarkGray
}

# ── Find modified source files ───────────────────────────────────────────────
$extensions = @("*.py", "*.cs", "*.java")
$files = @(
    foreach ($ext in $extensions) {
        Get-ChildItem -Path $Path -Filter $ext -Recurse -File |
            Where-Object { $_.LastWriteTime -gt $lastScan }
    }
)

if ($files.Count -eq 0) {
    Write-Host "No modified source files found." -ForegroundColor Yellow
    return @()
}

Write-Host "Found $($files.Count) modified file(s)." -ForegroundColor Cyan

# ── Regex patterns per language ──────────────────────────────────────────────

# Python: class Foo:  /  def bar(self, x='value'):
$pyClassPattern    = '^\s*class\s+(\w+)'
$pyMethodPattern   = '^\s*def\s+(\w+)\s*\(([^)]*)\)'

# C#: class Foo {  /  void Bar(string x = "value")
$csClassPattern    = '^\s*(?:public|private|protected|internal|static|abstract|sealed|\s)*\s*class\s+(\w+)'
$csMethodPattern   = '^\s*(?:public|private|protected|internal|static|virtual|override|abstract|async|\s)*\s*\w+[\w<>\[\],\s]*?\s+(\w+)\s*\(([^)]*)\)'

# Java: class Foo {  — Java doesn't have default params, but we check for overloads with hardcoded values
# For Java we look for methods and extract any literal assignments in the body as a fallback,
# but primarily we look for the method signature pattern matching the encoding convention.
$javaClassPattern  = '^\s*(?:public|private|protected|static|abstract|final|\s)*\s*class\s+(\w+)'
$javaMethodPattern = '^\s*(?:public|private|protected|static|final|abstract|synchronized|\s)*\s*\w+[\w<>\[\],\s]*?\s+(\w+)\s*\(([^)]*)\)'

# ── Parse defaults from parameter lists ──────────────────────────────────────
function Get-DefaultValues {
    param([string]$ParamString, [string]$Language)

    $defaults = @()

    switch ($Language) {
        "python" {
            # Match: x='value' or x="value" or x = 'value'
            $matches_found = [regex]::Matches($ParamString, '(\w+)\s*=\s*[''"]([^''"]*)[''"]')
            foreach ($m in $matches_found) {
                $defaults += [PSCustomObject]@{
                    ParamName = $m.Groups[1].Value
                    DefaultValue = $m.Groups[2].Value
                }
            }
        }
        "csharp" {
            # Match: string x = "value" or int x = "value"
            $matches_found = [regex]::Matches($ParamString, '\w+[\w<>\[\],\s]*?\s+(\w+)\s*=\s*"([^"]*)"')
            foreach ($m in $matches_found) {
                $defaults += [PSCustomObject]@{
                    ParamName = $m.Groups[1].Value
                    DefaultValue = $m.Groups[2].Value
                }
            }
        }
        "java" {
            # Java has no default params. Look for string literals in the param list
            # that follow our encoding pattern: method called with a literal.
            # Fallback: we'll scan method bodies separately.
        }
    }

    return $defaults
}

# ── Scan for Java hardcoded values in method bodies ──────────────────────────
function Get-JavaBodyDefaults {
    param([string[]]$Lines, [int]$MethodLineIndex)

    $defaults = @()
    $braceDepth = 0
    $started = $false

    for ($i = $MethodLineIndex; $i -lt $Lines.Count; $i++) {
        foreach ($ch in $Lines[$i].ToCharArray()) {
            if ($ch -eq '{') { $braceDepth++; $started = $true }
            if ($ch -eq '}') { $braceDepth-- }
        }

        # Look for: variable = "literal"  or  = "literal"
        $bodyMatches = [regex]::Matches($Lines[$i], '(\w+)\s*=\s*"([^"]*)"')
        foreach ($m in $bodyMatches) {
            $defaults += [PSCustomObject]@{
                ParamName = $m.Groups[1].Value
                DefaultValue = $m.Groups[2].Value
            }
        }

        if ($started -and $braceDepth -le 0) { break }
    }

    return $defaults
}

# ── Main parse loop ──────────────────────────────────────────────────────────
$results = [System.Collections.Generic.List[PSCustomObject]]::new()

foreach ($file in $files) {
    $lines = @(Get-Content $file.FullName)
    $ext = $file.Extension.ToLower()

    # Select patterns based on extension
    switch ($ext) {
        ".py"   { $lang = "python";  $classPat = $pyClassPattern;   $methodPat = $pyMethodPattern }
        ".cs"   { $lang = "csharp";  $classPat = $csClassPattern;   $methodPat = $csMethodPattern }
        ".java" { $lang = "java";    $classPat = $javaClassPattern;  $methodPat = $javaMethodPattern }
    }

    $currentClass = $null

    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]

        # Check for class definition
        if ($line -match $classPat) {
            $currentClass = $Matches[1]
            continue
        }

        # Check for method/function definition (skip lines that are class declarations)
        if ($currentClass -and $line -notmatch '\bclass\b' -and $line -match $methodPat) {
            $methodName = $Matches[1]
            $paramString = $Matches[2]

            # Skip Python dunder methods and constructors
            if ($lang -eq "python" -and $methodName -like "__*") { continue }
            if ($lang -eq "csharp" -and $methodName -eq $currentClass) { continue }
            if ($lang -eq "java" -and $methodName -eq $currentClass) { continue }

            $defaults = @()
            if ($lang -eq "java") {
                $defaults = Get-JavaBodyDefaults -Lines $lines -MethodLineIndex $i
            } else {
                $defaults = Get-DefaultValues -ParamString $paramString -Language $lang
            }

            foreach ($d in $defaults) {
                $results.Add([PSCustomObject]@{
                    ClassName    = $currentClass
                    MethodName   = $methodName
                    DefaultValue = $d.DefaultValue
                    Source       = $file.Name
                })
            }
        }
    }
}

# ── Update timestamp ─────────────────────────────────────────────────────────
$now = (Get-Date).ToString("o")
Set-Content -Path $tsPath -Value $now
Write-Host "Timestamp updated: $now" -ForegroundColor DarkGray

# ── Output ───────────────────────────────────────────────────────────────────
if ($results.Count -eq 0) {
    Write-Host "No (class, method, default) tuples found." -ForegroundColor Yellow
} else {
    Write-Host "`nExtracted $($results.Count) tuple(s):`n" -ForegroundColor Green
    $results | Format-Table -AutoSize
}

return $results
