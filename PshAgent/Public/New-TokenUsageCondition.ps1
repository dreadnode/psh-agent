function New-TokenUsageCondition {
    <#
    .SYNOPSIS
    Stop when token usage exceeds a limit
    .PARAMETER Limit
    Maximum token count
    .PARAMETER Mode
    Which tokens to count: 'total', 'input', or 'output' (default: total)
    .EXAMPLE
    $cond = New-TokenUsageCondition -Limit 100000
    #>
    [CmdletBinding()]
    [OutputType([StopCondition])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [int]$Limit,

        [Parameter()]
        [ValidateSet('total', 'input', 'output')]
        [string]$Mode = 'total'
    )

    $lim = $Limit
    $m = $Mode
    return [StopCondition]::new(
        "stop_on_token_usage($Limit, $Mode)",
        {
            param($steps)
            $total = 0
            foreach ($s in $steps) {
                if ($s.Type -eq [AgentEventType]::GenerationStep -and $s.Usage) {
                    switch ($m) {
                        'total' { $total += $s.Usage.TotalTokens }
                        'input' { $total += $s.Usage.InputTokens }
                        'output' { $total += $s.Usage.OutputTokens }
                    }
                }
            }
            $total -gt $lim
        }.GetNewClosure()
    )
}
