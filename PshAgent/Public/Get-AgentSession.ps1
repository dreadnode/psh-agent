function Get-AgentSession {
    <#
    .SYNOPSIS
    Load or list sessions from ~/.psh-agent/sessions/
    .PARAMETER Id
    Session ID to load. If not specified, lists all sessions.
    .EXAMPLE
    Get-AgentSession  # List all sessions
    .EXAMPLE
    Get-AgentSession -Id 'session-20250101-abc123'  # Load specific session
    #>
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$Id
    )

    $dir = [PshAgentSession]::GetSessionDir()

    if ($Id) {
        $filePath = Join-Path $dir "$Id.json"
        if (-not (Test-Path $filePath)) {
            throw "Session not found: $Id"
        }
        $json = Get-Content -Path $filePath -Raw
        $data = $json | ConvertFrom-Json -AsHashtable
        return [PshAgentSession]::FromHashtable($data)
    }

    # List all sessions
    $files = Get-ChildItem -Path $dir -Filter '*.json' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending

    $sessions = @()
    foreach ($file in $files) {
        try {
            $json = Get-Content -Path $file.FullName -Raw
            $data = $json | ConvertFrom-Json -AsHashtable
            $sessions += [PSCustomObject]@{
                Id        = $data.id
                Name      = $data.name
                Created   = $data.created
                Updated   = $data.updated
                Messages  = if ($data.messages) { $data.messages.Count } else { 0 }
                Tokens    = $data.totalTokens
            }
        }
        catch {
            Write-Verbose "Error loading session $($file.Name): $_"
        }
    }

    return $sessions
}
