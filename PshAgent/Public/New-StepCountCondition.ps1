function New-StepCountCondition {
    <#
    .SYNOPSIS
    Stop after N steps
    .PARAMETER MaxSteps
    Maximum number of steps before stopping
    .EXAMPLE
    $cond = New-StepCountCondition -MaxSteps 10
    #>
    [CmdletBinding()]
    [OutputType([StopCondition])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [int]$MaxSteps
    )

    $max = $MaxSteps
    return [StopCondition]::new(
        "stop_on_step_count($MaxSteps)",
        { param($steps) $steps.Count -ge $max }.GetNewClosure()
    )
}
