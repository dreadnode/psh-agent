function Remove-AgentSession {
    <#
    .SYNOPSIS
    Delete sessions from ~/.psh-agent/sessions/
    .PARAMETER Id
    Session ID to delete
    .PARAMETER All
    Delete all sessions
    .EXAMPLE
    Remove-AgentSession -Id 'session-20250101-abc123'
    .EXAMPLE
    Remove-AgentSession -All
    #>
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Position = 0)]
        [string]$Id,

        [Parameter()]
        [switch]$All
    )

    $dir = [PshAgentSession]::GetSessionDir()

    if ($All) {
        $files = Get-ChildItem -Path $dir -Filter '*.json' -ErrorAction SilentlyContinue
        foreach ($file in $files) {
            if ($PSCmdlet.ShouldProcess($file.Name, 'Delete session')) {
                Remove-Item -Path $file.FullName -Force
            }
        }
        Write-Verbose "All sessions deleted"
        return
    }

    if (-not $Id) {
        throw "Specify -Id or -All"
    }

    $filePath = Join-Path $dir "$Id.json"
    if (-not (Test-Path $filePath)) {
        throw "Session not found: $Id"
    }

    if ($PSCmdlet.ShouldProcess($Id, 'Delete session')) {
        Remove-Item -Path $filePath -Force
        Write-Verbose "Session deleted: $Id"
    }
}
