function Invoke-Agent {
    <#
    .SYNOPSIS
    Blocking agent run - returns AgentResult hashtable
    .DESCRIPTION
    Runs the agent loop: generate -> tool calls -> generate, until stop condition.
    Returns @{ Status; Trajectory; Output; Error }
    .PARAMETER Agent
    A PshAgent instance
    .PARAMETER Input
    User input string
    .PARAMETER Trajectory
    Existing trajectory to continue from (for multi-turn)
    .EXAMPLE
    $result = Invoke-Agent -Agent $agent -Input 'List all .ps1 files'
    $result.Trajectory.GetMessages() | ForEach-Object { $_.GetText() }
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [PshAgent]$Agent,

        [Parameter(Mandatory)]
        [string]$Input,

        [Parameter()]
        [Trajectory]$Trajectory
    )

    # Collect all events from streaming and return final result
    $events = @(Invoke-AgentStream -Agent $Agent -Input $Input -Trajectory $Trajectory)

    # Find end event
    $endEvent = $events | Where-Object { $_.Type -eq [AgentEventType]::AgentEnd } | Select-Object -Last 1

    $status = if ($endEvent) { $endEvent.Status } else { [AgentStatus]::errored }
    $error = if ($endEvent) { $endEvent.Error } else { $null }

    # Find the trajectory from the pipeline events
    $traj = if ($Trajectory) { $Trajectory } else {
        # Reconstruct from start event
        $startEvt = $events | Where-Object { $_.Type -eq [AgentEventType]::AgentStart } | Select-Object -First 1
        if ($startEvt) { $startEvt._trajectory } else { $null }
    }

    return @{
        Status     = $status
        Trajectory = $traj
        Output     = $null
        Error      = $error
    }
}
