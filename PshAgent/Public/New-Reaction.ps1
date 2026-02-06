function New-Reaction {
    <#
    .SYNOPSIS
    Reaction factory helpers
    .PARAMETER Type
    Reaction type: Continue, Retry, RetryWithFeedback, Fail, Finish
    .PARAMETER Feedback
    Feedback text (for RetryWithFeedback)
    .PARAMETER Reason
    Error reason (for Fail)
    .PARAMETER Result
    Result value (for Finish)
    .EXAMPLE
    $r = New-Reaction -Type Continue
    $r = New-Reaction -Type RetryWithFeedback -Feedback 'Try again'
    $r = New-Reaction -Type Fail -Reason 'Too many errors'
    $r = New-Reaction -Type Finish -Result 'done'
    #>
    [CmdletBinding()]
    [OutputType([Reaction])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [ReactionType]$Type,

        [Parameter()]
        [string]$Feedback,

        [Parameter()]
        [string]$Reason,

        [Parameter()]
        $Result
    )

    switch ($Type) {
        'Continue' { return [Reaction]::Continue() }
        'Retry' { return [Reaction]::Retry() }
        'RetryWithFeedback' { return [Reaction]::RetryWithFeedback($Feedback) }
        'Fail' { return [Reaction]::Fail($Reason) }
        'Finish' {
            if ($PSBoundParameters.ContainsKey('Result')) {
                return [Reaction]::Finish($Result)
            }
            return [Reaction]::Finish()
        }
    }
}
