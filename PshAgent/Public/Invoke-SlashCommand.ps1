function Invoke-SlashCommand {
    <#
    .SYNOPSIS
    Slash command dispatch for the interactive CLI
    .PARAMETER Command
    The slash command string (e.g., '/help', '/clear', '/model anthropic/gpt-4o')
    .PARAMETER Context
    CLI context hashtable with session, messages, config, etc.
    .OUTPUTS
    Hashtable with: Continue (bool), Message (string to send to agent)
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Command,

        [Parameter(Mandatory)]
        [hashtable]$Context
    )

    $esc = [char]27
    $dim = "$esc[2m"
    $bold = "$esc[1m"
    $cyan = "$esc[36m"
    $green = "$esc[32m"
    $yellow = "$esc[33m"
    $reset = "$esc[0m"

    $parts = $Command.TrimStart('/').Split(' ', 2)
    $cmd = $parts[0].ToLower()
    $arg = if ($parts.Count -gt 1) { $parts[1].Trim() } else { '' }

    switch ($cmd) {
        'help' {
            Write-Host @"
${bold}${cyan}PshAgent Commands${reset}

  ${bold}/help${reset}              Show this help
  ${bold}/quit${reset}              Exit the CLI
  ${bold}/clear${reset}             Clear conversation history
  ${bold}/model${reset} [conn]      Show or change model (e.g., /model anthropic/claude-sonnet-4-20250514)
  ${bold}/compact${reset}           Toggle compact mode
  ${bold}/tokens${reset}            Show token usage
  ${bold}/session${reset}           Show current session info
  ${bold}/sessions${reset}          List saved sessions
  ${bold}/save${reset} [name]       Save current session
  ${bold}/load${reset} <id>         Load a saved session
  ${bold}/delete${reset} <id>       Delete a saved session
  ${bold}/system${reset} <prompt>   Set system prompt
  ${bold}/tools${reset}             List available tools
  ${bold}/hooks${reset}             List active hooks
"@
            return @{ Continue = $true }
        }

        'quit' {
            Write-Host "${dim}bye${reset}"
            return @{ Continue = $false }
        }

        'exit' {
            Write-Host "${dim}bye${reset}"
            return @{ Continue = $false }
        }

        'clear' {
            $Context.messages.Clear()
            $Context.session.Messages = @()
            Write-Host "${dim}Conversation cleared${reset}"
            return @{ Continue = $true }
        }

        'model' {
            if ($arg) {
                $Context.config.ConnectionString = $arg
                $Context.generator = [PshGenerator]::new($arg)
                Write-Host "${green}Model changed to: $arg${reset}"
            }
            else {
                Write-Host "${cyan}Current model: $($Context.config.ConnectionString)${reset}"
            }
            return @{ Continue = $true }
        }

        'compact' {
            $Context.config.Compact = -not $Context.config.Compact
            $state = if ($Context.config.Compact) { 'ON' } else { 'OFF' }
            Write-Host "${dim}Compact mode: $state${reset}"
            return @{ Continue = $true }
        }

        'tokens' {
            $usage = $Context.totalUsage
            Write-Host "${cyan}Token Usage:${reset}"
            Write-Host "  Input:  $($usage.Input)"
            Write-Host "  Output: $($usage.Output)"
            Write-Host "  Total:  $($usage.Total)"
            return @{ Continue = $true }
        }

        'session' {
            $s = $Context.session
            Write-Host "${cyan}Session:${reset} $($s.Name)"
            Write-Host "  ID:       $($s.Id)"
            Write-Host "  Created:  $($s.Created)"
            Write-Host "  Messages: $($s.Messages.Count)"
            Write-Host "  Tokens:   $($s.TotalTokens)"
            return @{ Continue = $true }
        }

        'sessions' {
            $sessions = Get-AgentSession
            if ($sessions.Count -eq 0) {
                Write-Host "${dim}No saved sessions${reset}"
            }
            else {
                Write-Host "${bold}${cyan}Saved Sessions:${reset}"
                foreach ($s in $sessions) {
                    Write-Host "  ${bold}$($s.Id)${reset} - $($s.Name) ($($s.Messages) messages, $($s.Tokens) tokens)"
                }
            }
            return @{ Continue = $true }
        }

        'save' {
            $name = if ($arg) { $arg } else { $Context.session.Name }
            $Context.session.Name = $name
            $path = Save-AgentSession -Session $Context.session
            Write-Host "${green}Session saved: $name${reset}"
            return @{ Continue = $true }
        }

        'load' {
            if (-not $arg) {
                Write-Host "${yellow}Usage: /load <session-id>${reset}"
                return @{ Continue = $true }
            }
            try {
                $loaded = Get-AgentSession -Id $arg
                $Context.session = $loaded
                $Context.messages.Clear()
                foreach ($m in $loaded.Messages) {
                    $Context.messages.Add($m)
                }
                Write-Host "${green}Session loaded: $($loaded.Name) ($($loaded.Messages.Count) messages)${reset}"
            }
            catch {
                Write-Host "${yellow}$($_.Exception.Message)${reset}"
            }
            return @{ Continue = $true }
        }

        'delete' {
            if (-not $arg) {
                Write-Host "${yellow}Usage: /delete <session-id>${reset}"
                return @{ Continue = $true }
            }
            try {
                Remove-AgentSession -Id $arg -Confirm:$false
                Write-Host "${green}Session deleted${reset}"
            }
            catch {
                Write-Host "${yellow}$($_.Exception.Message)${reset}"
            }
            return @{ Continue = $true }
        }

        'system' {
            if ($arg) {
                $Context.systemPrompt = $arg
                Write-Host "${green}System prompt updated${reset}"
            }
            else {
                if ($Context.systemPrompt) {
                    Write-Host "${cyan}System prompt:${reset} $($Context.systemPrompt)"
                }
                else {
                    Write-Host "${dim}No system prompt set${reset}"
                }
            }
            return @{ Continue = $true }
        }

        'tools' {
            if ($Context.toolkit -and $Context.toolkit.Tools.Count -gt 0) {
                Write-Host "${bold}${cyan}Available Tools:${reset}"
                foreach ($entry in $Context.toolkit.Tools.GetEnumerator()) {
                    Write-Host "  ${bold}$($entry.Key)${reset} - $($entry.Value.Description)"
                }
            }
            else {
                Write-Host "${dim}No tools configured${reset}"
            }
            return @{ Continue = $true }
        }

        'hooks' {
            if ($Context.hooks -and $Context.hooks.Count -gt 0) {
                Write-Host "${bold}${cyan}Active Hooks:${reset}"
                foreach ($h in $Context.hooks) {
                    Write-Host "  ${bold}$($h.Name)${reset} -> $($h.EventType)"
                }
            }
            else {
                Write-Host "${dim}No hooks configured${reset}"
            }
            return @{ Continue = $true }
        }

        default {
            Write-Host "${yellow}Unknown command: /$cmd${reset}. Type ${bold}/help${reset} for available commands."
            return @{ Continue = $true }
        }
    }
}
