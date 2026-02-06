function Start-PshAgent {
    <#
    .SYNOPSIS
    Main interactive CLI entry point for PshAgent
    .DESCRIPTION
    Launches an interactive REPL with chat, slash commands, tool calling, and streaming output.
    .PARAMETER ConnectionString
    Provider/model connection string (e.g., 'anthropic/claude-sonnet-4-20250514')
    .PARAMETER SystemPrompt
    System prompt for the agent
    .PARAMETER Tools
    Array of PshAgentTool objects (defaults to built-in tools)
    .PARAMETER Hooks
    Array of PshAgentHook objects
    .PARAMETER StopCondition
    Stop condition (defaults to step count 50)
    .PARAMETER MaxSteps
    Maximum steps per turn (default: 50)
    .PARAMETER Compact
    Enable compact output mode
    .EXAMPLE
    Start-PshAgent -ConnectionString 'anthropic/claude-sonnet-4-20250514'
    .EXAMPLE
    Start-PshAgent 'openai/gpt-4o' -SystemPrompt 'You are an expert PowerShell developer.'
    #>
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$ConnectionString,

        [Parameter()]
        [string]$SystemPrompt,

        [Parameter()]
        [PshAgentTool[]]$Tools,

        [Parameter()]
        [PshAgentHook[]]$Hooks = @(),

        [Parameter()]
        [StopCondition]$StopCondition,

        [Parameter()]
        [int]$MaxSteps = 50,

        [Parameter()]
        [switch]$Compact
    )

    $esc = [char]27
    $bold = "$esc[1m"
    $dim = "$esc[2m"
    $cyan = "$esc[36m"
    $green = "$esc[32m"
    $yellow = "$esc[33m"
    $red = "$esc[31m"
    $magenta = "$esc[35m"
    $reset = "$esc[0m"

    # Resolve connection string
    if (-not $ConnectionString) {
        # Try to load from config
        $configPath = Join-Path ([System.Environment]::GetFolderPath('UserProfile')) '.psh-agent' 'config.json'
        if (Test-Path $configPath) {
            $config = Get-Content $configPath -Raw | ConvertFrom-Json
            $ConnectionString = $config.connectionString
        }
        if (-not $ConnectionString) {
            $ConnectionString = 'anthropic/claude-sonnet-4-20250514'
        }
    }

    # Create generator
    $generator = [PshGenerator]::new($ConnectionString)

    # Set up default system prompt
    if (-not $SystemPrompt) {
        $SystemPrompt = @"
You are PshAgent, an AI coding assistant running in PowerShell. Be concise and direct.

Working directory: $($PWD.Path)

Guidelines:
- Use tools to accomplish tasks, don't just explain
- Be brief but helpful
- For file operations, use relative or absolute paths
- Prefer simple, safe shell commands
"@
    }

    # Set up tools (defaults to built-in tools)
    $toolkit = [PshAgentToolkit]::new()
    if ($Tools) {
        $toolkit.AddRange($Tools)
    }
    else {
        # Add built-in tools
        $toolkit.Add((Read-FileContent))
        $toolkit.Add((Write-FileContent))
        $toolkit.Add((Get-DirectoryListing))
        $toolkit.Add((Invoke-ShellCommand))
        $toolkit.Add((Search-Files))
        $toolkit.Add((Search-FileContent))
    }

    # Set up stop condition
    if (-not $StopCondition) {
        $ms = $MaxSteps
        $StopCondition = [StopCondition]::new(
            "stop_on_step_count($MaxSteps)",
            { param($steps) $steps.Count -ge $ms }.GetNewClosure()
        )
    }

    # Add default hooks if none provided
    $allHooks = [System.Collections.Generic.List[PshAgentHook]]::new($Hooks)
    if ($Hooks.Count -eq 0) {
        $allHooks.Add((New-BackoffOnRatelimitHook))
        $allHooks.Add((New-DangerousCommandHook))
        $allHooks.Add((New-RetryWithFeedbackHook -Feedback 'Please use a tool to make progress toward the goal. If you are stuck, try a different approach.'))
    }

    # Create session
    $session = [PshAgentSession]::new()
    $session.ConnectionString = $ConnectionString

    # Context for slash commands
    $ctx = @{
        config       = @{
            ConnectionString = $ConnectionString
            Compact          = [bool]$Compact
        }
        messages     = [System.Collections.Generic.List[Message]]::new()
        session      = $session
        totalUsage   = @{ Input = 0; Output = 0; Total = 0 }
        generator    = $generator
        toolkit      = $toolkit
        hooks        = $allHooks.ToArray()
        systemPrompt = $SystemPrompt
    }

    # Print banner
    Write-Host ""
    Write-Host "${bold}${cyan}  ____  _____ _   _    _                    _   ${reset}"
    Write-Host "${bold}${cyan} |  _ \/ ____| | | |  / \   __ _  ___ _ __ | |_ ${reset}"
    Write-Host "${bold}${cyan} | |_) \___ \| |_| | / _ \ / _  |/ _ \ '_ \| __|${reset}"
    Write-Host "${bold}${cyan} |  __/ ___) |  _  |/ ___ \ (_| |  __/ | | | |_ ${reset}"
    Write-Host "${bold}${cyan} |_|  |____/|_| |_/_/   \_\__, |\___|_| |_|\__|${reset}"
    Write-Host "${bold}${cyan}                          |___/                  ${reset}"
    Write-Host ""
    Write-Host "  ${dim}Model: $ConnectionString${reset}"
    Write-Host "  ${dim}Tools: $($toolkit.List() -join ', ')${reset}"
    Write-Host "  ${dim}Type /help for commands, /quit to exit${reset}"
    Write-Host ""

    # REPL loop
    $running = $true
    $trajectory = $null

    while ($running) {
        # Prompt
        Write-Host -NoNewline "`n${cyan}>${reset} "
        $userInput = Read-Host

        if ([string]::IsNullOrWhiteSpace($userInput)) {
            continue
        }

        # Handle slash commands
        if ($userInput.StartsWith('/')) {
            $result = Invoke-SlashCommand -Command $userInput -Context $ctx
            $running = $result.Continue

            if ($result.Message) {
                $userInput = $result.Message
            }
            else {
                continue
            }
        }

        # Create agent for this turn
        $agent = [PshAgent]::new(@{
            Generator       = $ctx.generator
            Name            = 'psh-agent'
            SystemPrompt    = $ctx.systemPrompt
            Toolkit         = $toolkit
            StopCondition   = $StopCondition
            Hooks           = $ctx.hooks
        })

        # Build generate options with tools
        $genOptions = @{
            tools = $toolkit.ToToolDefinitions()
        }

        # Track this turn's messages in session
        $ctx.messages.Add([Message]::User($userInput))
        $session.AddMessage([Message]::User($userInput))

        # Run agent loop with streaming output
        $spinner = $null
        $continueLoop = $true

        while ($continueLoop) {
            $continueLoop = $false

            # Show spinner while generating
            $spinner = Start-Spinner 'Thinking...'

            try {
                # Build message history for this call
                $allMessages = [System.Collections.Generic.List[Message]]::new()
                $allMessages.Add([Message]::System($ctx.systemPrompt))
                foreach ($m in $ctx.messages) {
                    $allMessages.Add($m)
                }

                # Call LLM
                $result = $ctx.generator.Generate($allMessages.ToArray(), $genOptions)

                Stop-Spinner -State $spinner

                # Show token usage
                if ($result.Usage -and -not $ctx.config.Compact) {
                    $ctx.totalUsage.Input += $result.Usage.InputTokens
                    $ctx.totalUsage.Output += $result.Usage.OutputTokens
                    $ctx.totalUsage.Total += $result.Usage.TotalTokens
                    $session.UpdateTokens($result.Usage.TotalTokens)
                    Write-Host "${dim}[$($result.Usage.InputTokens)/$($result.Usage.OutputTokens) tokens]${reset}"
                }

                # Show response content
                $responseText = $result.Message.GetText()
                if ($responseText) {
                    Write-Host ""
                    Write-Host "${green}$responseText${reset}"
                }

                # Track assistant message
                $ctx.messages.Add($result.Message)
                $session.AddMessage($result.Message)

                # Handle tool calls
                if ($result.Message.HasToolCalls()) {
                    foreach ($tc in $result.Message.ToolCalls) {
                        # Show tool call
                        $argsStr = ($tc.Arguments | ConvertTo-Json -Compress -Depth 3)
                        if ($argsStr.Length -gt 120) { $argsStr = $argsStr.Substring(0, 117) + '...' }
                        Write-Host ""
                        Write-Host "${yellow}> Tool: ${bold}$($tc.Name)${reset} ${dim}$argsStr${reset}"

                        # Execute tool
                        $spinner = Start-Spinner "Running $($tc.Name)..."
                        $toolResult = $null
                        $toolError = $null
                        try {
                            $toolResult = $toolkit.Execute($tc.Name, $tc.Arguments)
                        }
                        catch {
                            $toolError = $_.Exception.Message
                            $toolResult = "Error: $toolError"
                        }
                        Stop-Spinner -State $spinner

                        # Show result
                        $resultStr = if ($toolResult -is [string]) { $toolResult } else { ($toolResult | ConvertTo-Json -Compress -Depth 3) }
                        if ($resultStr.Length -gt 500 -and $ctx.config.Compact) {
                            $resultStr = $resultStr.Substring(0, 497) + '...'
                        }
                        if ($toolError) {
                            Write-Host "${red}> Error: $toolError${reset}"
                        }
                        else {
                            $displayResult = if ($resultStr.Length -gt 200) {
                                $resultStr.Substring(0, 197) + '...'
                            } else { $resultStr }
                            Write-Host "${dim}> Result: $displayResult${reset}"
                        }

                        # Add tool result to messages
                        $toolMsg = [Message]::Tool($tc.Id, $resultStr)
                        $ctx.messages.Add($toolMsg)
                        $session.AddMessage($toolMsg)
                    }

                    # Continue loop for next LLM call
                    $continueLoop = $true
                }
            }
            catch {
                if ($spinner) { Stop-Spinner -State $spinner }
                Write-Host "${red}Error: $($_.Exception.Message)${reset}"
            }
        }
    }
}
