function New-ConsecutiveErrorCondition {
    <#
    .SYNOPSIS
    Stop after N consecutive tool errors
    .PARAMETER Count
    Number of consecutive errors before stopping
    .EXAMPLE
    $cond = New-ConsecutiveErrorCondition -Count 3
    #>
    [CmdletBinding()]
    [OutputType([StopCondition])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [int]$Count
    )

    $maxCount = $Count
    return [StopCondition]::new(
        "stop_on_consecutive_errors($Count)",
        {
            param($steps)
            $consecutive = 0
            for ($i = $steps.Count - 1; $i -ge 0; $i--) {
                $s = $steps[$i]
                if ($s.Type -ne [AgentEventType]::ToolStep) { continue }

                if ($s.Error) {
                    $consecutive++
                    if ($consecutive -ge $maxCount) { return $true }
                }
                else {
                    $consecutive = 0
                }
            }
            return $false
        }.GetNewClosure()
    )
}
