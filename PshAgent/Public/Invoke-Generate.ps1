function Invoke-Generate {
    <#
    .SYNOPSIS
    Non-streaming LLM call
    .DESCRIPTION
    Calls the LLM API and returns the complete response.
    Returns a hashtable with Message, Usage, StopReason, Raw.
    .PARAMETER Generator
    A PshGenerator instance
    .PARAMETER Messages
    Array of Message objects to send
    .PARAMETER Options
    Additional options (temperature, max_tokens, tools, etc.)
    .EXAMPLE
    $result = Invoke-Generate -Generator $gen -Messages @([Message]::User('Hello'))
    $result.Message.GetText()
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

    return $Generator.Generate($Messages, $Options)
}
