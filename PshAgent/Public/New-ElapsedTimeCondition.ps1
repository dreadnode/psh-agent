function New-ElapsedTimeCondition {
    <#
    .SYNOPSIS
    Stop when elapsed time exceeds a limit
    .PARAMETER MaxSeconds
    Maximum time in seconds
    .EXAMPLE
    $cond = New-ElapsedTimeCondition -MaxSeconds 300
    #>
    [CmdletBinding()]
    [OutputType([StopCondition])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [int]$MaxSeconds
    )

    $maxSec = $MaxSeconds
    return [StopCondition]::new(
        "stop_on_elapsed_time(${MaxSeconds}s)",
        {
            param($steps)
            if ($steps.Count -lt 2) { return $false }
            $first = $steps[0]
            $last = $steps[$steps.Count - 1]
            $elapsed = ($last.Timestamp - $first.Timestamp).TotalSeconds
            $elapsed -gt $maxSec
        }.GetNewClosure()
    )
}
