function Invoke-Agent {
    <#
    .SYNOPSIS
    Blocking agent run - returns AgentResult hashtable
    .DESCRIPTION
    Runs the agent loop: generate -> tool calls -> generate, until stop condition.
    Returns @{ Status; Output; Steps; Usage; Trajectory; Error }
    .PARAMETER Agent
    A PshAgent instance
    .PARAMETER Prompt
    User input string
    .PARAMETER Trajectory
    Existing trajectory to continue from (for multi-turn)
    .EXAMPLE
    $result = Invoke-Agent -Agent $agent -Prompt 'List all .ps1 files'
    $result.Output
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [PshAgent]$Agent,

        [Parameter(Mandatory)]
        [string]$Prompt,

        [Parameter()]
        [Trajectory]$Trajectory
    )

    # Collect all events from streaming and return final result
    $events = @(Invoke-AgentStream -Agent $Agent -Prompt $Prompt -Trajectory $Trajectory)

    # Find end event
    $endEvent = $events | Where-Object { $_.Type -eq [AgentEventType]::AgentEnd } | Select-Object -Last 1

    $status = if ($endEvent) { $endEvent.Status } else { [AgentStatus]::errored }
    $output = if ($endEvent) { $endEvent.Output } else { $null }
    $agentError = if ($endEvent) { $endEvent.Error } else { $null }

    # Find the trajectory from the start event
    $traj = if ($Trajectory) { $Trajectory } else {
        $startEvt = $events | Where-Object { $_.Type -eq [AgentEventType]::AgentStart } | Select-Object -First 1
        if ($startEvt) { $startEvt._trajectory } else { $null }
    }

    # Count steps and usage
    $stepEvents = @($events | Where-Object {
        $_.Type -eq [AgentEventType]::GenerationStep
    })
    $usage = if ($traj) { $traj.GetUsage() } else { [Usage]::Zero() }

    return @{
        Status     = $status
        Output     = $output
        Steps      = $stepEvents.Count
        Usage      = $usage
        Trajectory = $traj
        Error      = $agentError
    }
}
