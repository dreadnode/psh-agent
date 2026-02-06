function New-DangerousCommandHook {
    <#
    .SYNOPSIS
    Built-in hook: block dangerous shell commands
    .PARAMETER ExtraCommands
    Additional dangerous commands to block
    .PARAMETER Feedback
    Feedback to send when a dangerous command is detected
    .PARAMETER Name
    Hook name (default: detect_dangerous_commands)
    .EXAMPLE
    $hook = New-DangerousCommandHook -ExtraCommands @('format', 'fdisk')
    #>
    [CmdletBinding()]
    [OutputType([PshAgentHook])]
    param(
        [Parameter()]
        [string[]]$ExtraCommands = @(),

        [Parameter()]
        [string]$Feedback = 'That command appears dangerous. Please explain why it is necessary and confirm you want to proceed.',

        [Parameter()]
        [string]$Name = 'detect_dangerous_commands'
    )

    $dangerousSet = [System.Collections.Generic.HashSet[string]]::new(
        [string[]]@('rm', 'sudo', 'chmod', 'chown', 'mkfs', 'dd', 'del', 'format'),
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($cmd in $ExtraCommands) {
        $null = $dangerousSet.Add($cmd)
    }

    $fb = $Feedback

    return [PshAgentHook]::new($Name, [AgentEventType]::ToolStart, {
        param($event)

        $toolName = $event.ToolCall.Name.ToLower()
        if ($toolName -notin @('run_command', 'command', 'shell', 'bash', 'exec')) {
            return [Reaction]::Continue()
        }

        $command = ''
        if ($event.ToolCall.Arguments.command) { $command = $event.ToolCall.Arguments.command }
        elseif ($event.ToolCall.Arguments.cmd) { $command = $event.ToolCall.Arguments.cmd }
        elseif ($event.ToolCall.Arguments.script) { $command = $event.ToolCall.Arguments.script }

        $words = $command -split '\s+'
        $hasDangerous = $false
        foreach ($word in $words) {
            if ($dangerousSet.Contains($word)) {
                $hasDangerous = $true
                break
            }
        }

        if ($hasDangerous) {
            return [Reaction]::RetryWithFeedback($fb)
        }

        return [Reaction]::Continue()
    }.GetNewClosure())
}
