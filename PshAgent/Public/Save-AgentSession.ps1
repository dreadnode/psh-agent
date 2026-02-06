function Save-AgentSession {
    <#
    .SYNOPSIS
    Save session to ~/.psh-agent/sessions/
    .PARAMETER Session
    PshAgentSession to save
    .EXAMPLE
    Save-AgentSession -Session $session
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [PshAgentSession]$Session
    )

    $dir = [PshAgentSession]::GetSessionDir()
    $filePath = Join-Path $dir "$($Session.Id).json"

    $Session.Updated = [datetime]::UtcNow
    $json = $Session.ToHashtable() | ConvertTo-Json -Depth 20
    Set-Content -Path $filePath -Value $json -NoNewline

    Write-Verbose "Session saved: $filePath"
    return $filePath
}
