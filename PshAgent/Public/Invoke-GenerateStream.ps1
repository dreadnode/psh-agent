function Invoke-GenerateStream {
    <#
    .SYNOPSIS
    Streaming LLM call - yields StreamChunk objects to the pipeline
    .DESCRIPTION
    Calls the LLM API with streaming enabled. Emits PSCustomObject chunks
    with Type property: 'text-delta', 'tool-call', or 'finish'.
    .PARAMETER Generator
    A PshGenerator instance
    .PARAMETER Messages
    Array of Message objects to send
    .PARAMETER Options
    Additional options (temperature, max_tokens, tools, etc.)
    .EXAMPLE
    Invoke-GenerateStream -Generator $gen -Messages @([Message]::User('Hello')) |
        Where-Object Type -eq 'text-delta' |
        ForEach-Object { Write-Host $_.TextDelta -NoNewline }
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [PshGenerator]$Generator,

        [Parameter(Mandatory)]
        [Message[]]$Messages,

        [Parameter()]
        [hashtable]$Options = @{}
    )

    $Generator.Stream($Messages, $Options)
}
