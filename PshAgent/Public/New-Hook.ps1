function New-Hook {
    <#
    .SYNOPSIS
    Create a custom hook that listens for agent events
    .PARAMETER Name
    Hook name
    .PARAMETER EventType
    Which event type to listen for
    .PARAMETER Fn
    Scriptblock that receives an AgentEvent and optionally returns a Reaction
    .EXAMPLE
    $hook = New-Hook -Name 'log_steps' -EventType 'GenerationStep' -Fn {
        param($event)
        Write-Host "Step $($event.Step): $($event.Usage.TotalTokens) tokens"
        # Return $null to continue, or a Reaction to control flow
    }
    #>
    [CmdletBinding()]
    [OutputType([PshAgentHook])]
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [AgentEventType]$EventType,

        [Parameter(Mandatory)]
        [scriptblock]$Fn
    )

    return [PshAgentHook]::new($Name, $EventType, $Fn)
}
