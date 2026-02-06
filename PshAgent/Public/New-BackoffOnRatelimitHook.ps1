function New-BackoffOnRatelimitHook {
    <#
    .SYNOPSIS
    Built-in hook: backoff on rate limit (wraps New-BackoffOnErrorHook)
    .PARAMETER MaxTries
    Maximum retry attempts (default: 8)
    .PARAMETER MaxTime
    Maximum total time in seconds (default: 300)
    .PARAMETER BaseFactor
    Base delay factor in seconds (default: 1.0)
    .EXAMPLE
    $hook = New-BackoffOnRatelimitHook
    #>
    [CmdletBinding()]
    [OutputType([PshAgentHook])]
    param(
        [Parameter()]
        [int]$MaxTries = 8,

        [Parameter()]
        [int]$MaxTime = 300,

        [Parameter()]
        [double]$BaseFactor = 1.0
    )

    return New-BackoffOnErrorHook `
        -ErrorTypes @('RateLimitError', 'APIError', 'rate_limit', 'too_many_requests', '429') `
        -MaxTries $MaxTries -MaxTime $MaxTime -BaseFactor $BaseFactor `
        -Name 'backoff_on_ratelimit'
}
