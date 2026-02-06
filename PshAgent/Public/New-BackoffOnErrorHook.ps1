function New-BackoffOnErrorHook {
    <#
    .SYNOPSIS
    Built-in hook: exponential backoff on errors
    .PARAMETER ErrorTypes
    Error type strings to match against
    .PARAMETER MaxTries
    Maximum retry attempts (default: 8)
    .PARAMETER MaxTime
    Maximum total time in seconds (default: 300)
    .PARAMETER BaseFactor
    Base delay factor in seconds (default: 1.0)
    .PARAMETER Name
    Hook name (default: backoff_on_error)
    .EXAMPLE
    $hook = New-BackoffOnErrorHook -ErrorTypes @('RateLimitError', 'APIError')
    #>
    [CmdletBinding()]
    [OutputType([PshAgentHook])]
    param(
        [Parameter(Mandatory)]
        [string[]]$ErrorTypes,

        [Parameter()]
        [int]$MaxTries = 8,

        [Parameter()]
        [int]$MaxTime = 300,

        [Parameter()]
        [double]$BaseFactor = 1.0,

        [Parameter()]
        [string]$Name = 'backoff_on_error'
    )

    $types = $ErrorTypes
    $maxT = $MaxTries
    $maxTm = $MaxTime
    $base = $BaseFactor
    $state = @{ tries = 0; startTime = $null }

    return [PshAgentHook]::new($Name, [AgentEventType]::AgentError, {
        param($event)

        # Check if error matches any type
        $matched = $false
        foreach ($t in $types) {
            if ($event.ErrorType -eq $t -or $event.ErrorType -like "*$t*") {
                $matched = $true
                break
            }
        }
        if (-not $matched) {
            return [Reaction]::Continue()
        }

        if ($null -eq $state.startTime) {
            $state.startTime = [datetime]::UtcNow
        }
        $state.tries++

        $elapsed = ([datetime]::UtcNow - $state.startTime).TotalSeconds
        if ($state.tries -gt $maxT -or $elapsed -gt $maxTm) {
            $state.tries = 0
            $state.startTime = $null
            return [Reaction]::Continue()  # Let error propagate
        }

        # Exponential backoff: 2^(tries-1) * baseFactor with jitter
        $delay = [math]::Pow(2, $state.tries - 1) * $base
        $jitter = (Get-Random -Minimum 50 -Maximum 150) / 100.0
        $delay = $delay * $jitter

        Start-Sleep -Seconds $delay
        Write-Warning "[$Name] Retry $($state.tries)/$maxT after $([math]::Round($delay, 1))s ($($event.Error))"

        return [Reaction]::Retry()
    }.GetNewClosure())
}
