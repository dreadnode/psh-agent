function New-RetryWithFeedbackHook {
    <#
    .SYNOPSIS
    Built-in hook: retry with user feedback when agent stalls
    .PARAMETER Feedback
    Feedback text to send to the agent
    .PARAMETER Name
    Hook name (default: retry_with_feedback)
    .EXAMPLE
    $hook = New-RetryWithFeedbackHook -Feedback 'Please use a tool to make progress.'
    #>
    [CmdletBinding()]
    [OutputType([PshAgentHook])]
    param(
        [Parameter(Mandatory)]
        [string]$Feedback,

        [Parameter()]
        [string]$Name = 'retry_with_feedback'
    )

    $fb = $Feedback
    return [PshAgentHook]::new($Name, [AgentEventType]::AgentStalled, {
        param($event)
        return [Reaction]::RetryWithFeedback($fb)
    }.GetNewClosure())
}
