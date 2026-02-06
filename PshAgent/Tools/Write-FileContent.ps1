function Write-FileContent {
    <#
    .SYNOPSIS
    Built-in tool: write_file - Write content to a file
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param()

    return New-Tool -Name 'write_file' `
        -Description 'Write content to a file. Creates parent directories if needed.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                path    = @{ type = 'string'; description = 'Path to the file to write' }
                content = @{ type = 'string'; description = 'Content to write' }
            }
            required   = @('path', 'content')
        } `
        -Execute {
            param($a)
            $fullPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($a.path)
            $dir = [System.IO.Path]::GetDirectoryName($fullPath)
            if ($dir -and -not (Test-Path $dir)) {
                $null = New-Item -Path $dir -ItemType Directory -Force
            }
            Set-Content -Path $fullPath -Value $a.content -NoNewline -ErrorAction Stop
            "File written: $fullPath"
        }
}
