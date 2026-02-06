function New-Generator {
    <#
    .SYNOPSIS
    Create a generator from a connection string
    .DESCRIPTION
    Creates a PshGenerator that can call LLM APIs.
    Supports 'anthropic/model' and 'openai/model' connection strings.
    .PARAMETER ConnectionString
    Provider/model connection string (e.g., 'anthropic/claude-sonnet-4-20250514')
    .PARAMETER Defaults
    Default options for generation (temperature, max_tokens, etc.)
    .EXAMPLE
    $gen = New-Generator -ConnectionString 'anthropic/claude-sonnet-4-20250514'
    .EXAMPLE
    $gen = New-Generator 'openai/gpt-4o' -Defaults @{ temperature = 0.7; max_tokens = 2048 }
    #>
    [CmdletBinding()]
    [OutputType([PshGenerator])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$ConnectionString,

        [Parameter()]
        [hashtable]$Defaults = @{}
    )

    return [PshGenerator]::new($ConnectionString, $Defaults)
}
