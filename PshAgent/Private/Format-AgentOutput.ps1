function Format-AgentOutput {
    <#
    .SYNOPSIS
    Colored console output formatting for agent events and messages
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        $Event,

        [Parameter()]
        [switch]$Compact
    )

    $esc = [char]27

    # Color codes
    $cyan = "$esc[36m"
    $green = "$esc[32m"
    $yellow = "$esc[33m"
    $red = "$esc[31m"
    $magenta = "$esc[35m"
    $dim = "$esc[2m"
    $bold = "$esc[1m"
    $reset = "$esc[0m"

    if ($Event -is [AgentEvent]) {
        switch ($Event.Type) {
            'AgentStart' {
                return "${bold}${cyan}> Agent started${reset} ${dim}(step limit: $($Event.Metrics))${reset}"
            }
            'AgentEnd' {
                $statusColor = switch ($Event.Status) {
                    'finished' { $green }
                    'errored' { $red }
                    'stalled' { $yellow }
                    default { $dim }
                }
                return "${bold}${statusColor}> Agent $($Event.Status)${reset}$(if ($Event.Error) { " ${red}$($Event.Error)${reset}" })"
            }
            'GenerationStep' {
                $text = ''
                if ($Event.Messages -and $Event.Messages.Count -gt 0) {
                    $lastMsg = $Event.Messages[-1]
                    if ($lastMsg.Role -eq [MessageRole]::assistant) {
                        $text = $lastMsg.GetText()
                    }
                }
                $usage = if ($Event.Usage) { " ${dim}[$($Event.Usage.InputTokens)/$($Event.Usage.OutputTokens) tokens]${reset}" } else { '' }
                if ($text -and -not $Compact) {
                    return "${bold}${green}Assistant:${reset}$usage`n$text"
                }
                elseif ($text) {
                    return "${green}$text${reset}$usage"
                }
                return "${dim}(generation step $($Event.Step))${reset}$usage"
            }
            'ToolStart' {
                $name = $Event.ToolCall.Name
                $argsStr = ($Event.ToolCall.Arguments | ConvertTo-Json -Compress -Depth 3)
                if ($argsStr.Length -gt 100) { $argsStr = $argsStr.Substring(0, 97) + '...' }
                return "${yellow}> Tool: ${bold}$name${reset} ${dim}$argsStr${reset}"
            }
            'ToolStep' {
                $name = $Event.ToolCall.Name
                if ($Event.Error) {
                    return "${red}> Tool $name error: $($Event.Error)${reset}"
                }
                $resultStr = if ($Event.Result -is [string]) {
                    $Event.Result
                }
                else {
                    ($Event.Result | ConvertTo-Json -Compress -Depth 3)
                }
                if ($resultStr.Length -gt 500 -and $Compact) {
                    $resultStr = $resultStr.Substring(0, 497) + '...'
                }
                return "${dim}> Result ($name): ${reset}$resultStr"
            }
            'AgentError' {
                return "${red}> Error: $($Event.Error)${reset}"
            }
            'AgentStalled' {
                return "${yellow}> Agent stalled: $($Event.Reason)${reset}"
            }
            'ReactStep' {
                return "${magenta}> Hook '$($Event.HookName)' -> $($Event.ReactionType)$(if ($Event.Feedback) { ": $($Event.Feedback)" })${reset}"
            }
            default {
                return "${dim}> $($Event.Type) (step $($Event.Step))${reset}"
            }
        }
    }
    elseif ($Event -is [hashtable]) {
        # Format token usage
        if ($Event.ContainsKey('input') -and $Event.ContainsKey('output')) {
            return "${dim}[Tokens: in=$($Event.input) out=$($Event.output) total=$($Event.total)]${reset}"
        }
    }

    return [string]$Event
}
