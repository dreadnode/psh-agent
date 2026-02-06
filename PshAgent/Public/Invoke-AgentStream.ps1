function Invoke-AgentStream {
    <#
    .SYNOPSIS
    Streaming agent run - emits AgentEvent objects to the pipeline
    .DESCRIPTION
    Runs the agent loop and writes each event to the pipeline as it happens.
    Events include: AgentStart, GenerationStart, GenerationStep, ToolStart, ToolStep, AgentEnd, etc.
    .PARAMETER Agent
    A PshAgent instance
    .PARAMETER Prompt
    User input string
    .PARAMETER Trajectory
    Existing trajectory to continue from (for multi-turn)
    .EXAMPLE
    Invoke-AgentStream -Agent $agent -Prompt 'Hello' | ForEach-Object {
        Write-Host "$($_.Type) step=$($_.Step)"
    }
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [PshAgent]$Agent,

        [Parameter(Mandatory)]
        [string]$Prompt,

        [Parameter()]
        [Trajectory]$Trajectory
    )

    # Create or reuse trajectory
    $traj = if ($Trajectory) {
        $Trajectory
    }
    else {
        [Trajectory]::new($Agent.Id, $Agent.Name, $Agent.SystemPrompt)
    }

    # Helper to dispatch event through hooks and return winning reaction
    $dispatchEvent = {
        param([AgentEvent]$event)
        $collected = @{}
        foreach ($h in $Agent.Hooks) {
            if (-not $h.Matches($event)) { continue }
            try {
                $reaction = $h.Execute($event)
                if ($reaction) {
                    $collected[$h.Name] = $reaction
                }
            }
            catch {
                # Ignore hook errors for now
                Write-Verbose "Hook '$($h.Name)' error: $_"
            }
        }
        if ($collected.Count -gt 0) {
            Select-WinningReaction -Reactions $collected
        }
        else {
            $null
        }
    }

    # Helper to handle a reaction
    $handleReaction = {
        param($winner, [int]$step)
        $hookName = $winner.HookName
        $reaction = $winner.Reaction

        # Emit ReactStep
        $reactEvent = [ReactStepEvent]::new($Agent.Id, $Agent.Name)
        $reactEvent.Step = $step
        $reactEvent.HookName = $hookName
        $reactEvent.ReactionType = $reaction.Type.ToString()
        if ($reaction.Feedback) { $reactEvent.Feedback = $reaction.Feedback }
        if ($reaction.Reason) { $reactEvent.Reason = $reaction.Reason }
        $traj.AddEvent($reactEvent)
        & $dispatchEvent $reactEvent | Out-Null

        switch ($reaction.Type) {
            'Continue' {
                return @{ Done = $false; Retry = $false }
            }
            'Retry' {
                return @{ Done = $false; Retry = $true }
            }
            'RetryWithFeedback' {
                $traj.AddFeedback($reaction.Feedback)
                return @{ Done = $false; Retry = $true }
            }
            'Fail' {
                return @{
                    Done       = $true
                    Retry      = $false
                    Status     = [AgentStatus]::errored
                    StopReason = 'error'
                    Error      = $reaction.Reason
                }
            }
            'Finish' {
                return @{
                    Done       = $true
                    Retry      = $false
                    Status     = [AgentStatus]::finished
                    StopReason = 'finished'
                    Result     = $reaction.Result
                }
            }
        }
        return @{ Done = $false; Retry = $false }
    }

    # Build tool definitions for generate options
    $genOptions = @{}
    foreach ($k in $Agent.GenerateOptions.Keys) {
        $genOptions[$k] = $Agent.GenerateOptions[$k]
    }
    if ($Agent.Toolkit.Tools.Count -gt 0) {
        $genOptions.tools = $Agent.Toolkit.ToToolDefinitions()
    }

    # Emit AgentStart
    $startEvent = [AgentStartEvent]::new($Agent.Id, $Agent.Name)
    $startEvent.Inputs = @{ goal = $Prompt }
    $traj.AddEvent($startEvent)
    & $dispatchEvent $startEvent | Out-Null
    # Attach trajectory for Invoke-Agent to retrieve
    $startEvent | Add-Member -NotePropertyName '_trajectory' -NotePropertyValue $traj -Force
    Write-Output $startEvent

    $status = [AgentStatus]::running
    $stopReason = 'finished'
    $agentError = $null
    $finishResult = $null
    $step = 0
    $steps = [System.Collections.Generic.List[AgentEvent]]::new()

    try {
        while ($status -eq [AgentStatus]::running -and -not $Agent.StopCondition.Evaluate($steps.ToArray())) {
            $step++
            $continueStep = $false

            # Emit GenerationStart
            $genStartEvent = [GenerationStartEvent]::new($Agent.Id, $Agent.Name)
            $genStartEvent.Step = $step
            $genStartEvent.Model = $Agent.Generator.ModelId
            $traj.AddEvent($genStartEvent)
            & $dispatchEvent $genStartEvent | Out-Null
            Write-Output $genStartEvent

            try {
                # Get messages for generation
                $userInput = if ($step -eq 1) { $Prompt } else { $null }
                $messages = $traj.GetMessagesForGeneration($userInput)

                # Generate
                $result = $null
                try {
                    $result = $Agent.Generator.Generate($messages, $genOptions)
                }
                catch {
                    $errorMsg = $_.Exception.Message

                    $genErrorEvent = [GenerationErrorEvent]::new($Agent.Id, $Agent.Name)
                    $genErrorEvent.Step = $step
                    $genErrorEvent.Error = $errorMsg
                    $genErrorEvent.ErrorType = $_.Exception.GetType().Name
                    $genErrorEvent.Model = $Agent.Generator.ModelId
                    $traj.AddEvent($genErrorEvent)
                    & $dispatchEvent $genErrorEvent | Out-Null
                    Write-Output $genErrorEvent

                    throw
                }

                # Emit GenerationEnd
                $genEndEvent = [GenerationEndEvent]::new($Agent.Id, $Agent.Name)
                $genEndEvent.Step = $step
                $genEndEvent.Messages = @($result.Message)
                $genEndEvent.Usage = $result.Usage
                $genEndEvent.StopReason = $result.StopReason
                $genEndEvent.Model = $Agent.Generator.ModelId
                $traj.AddEvent($genEndEvent)
                & $dispatchEvent $genEndEvent | Out-Null
                Write-Output $genEndEvent

                # Emit GenerationStep (for trajectory/hook processing)
                $stepMessages = if ($userInput) {
                    @([Message]::User($userInput), $result.Message)
                }
                else {
                    @($result.Message)
                }

                $genStepEvent = [GenerationStepEvent]::new($Agent.Id, $Agent.Name)
                $genStepEvent.Step = $step
                $genStepEvent.Messages = $stepMessages
                $genStepEvent.Usage = $result.Usage
                $genStepEvent.StopReason = $result.StopReason
                $genStepEvent.Model = $Agent.Generator.ModelId
                $genStepEvent.GenerationFailed = $false
                $traj.AddEvent($genStepEvent)
                $steps.Add($genStepEvent)

                $genReaction = & $dispatchEvent $genStepEvent
                Write-Output $genStepEvent

                # Handle generation reaction
                $deferredRetry = $null
                if ($genReaction) {
                    $r = $genReaction.Reaction
                    if ($r.Type -eq [ReactionType]::Fail -or $r.Type -eq [ReactionType]::Finish) {
                        $handled = & $handleReaction $genReaction $step
                        $status = $handled.Status
                        $stopReason = $handled.StopReason
                        $agentError = $handled.Error
                        $finishResult = $handled.Result
                        break
                    }
                    elseif ($r.Type -eq [ReactionType]::Retry -or $r.Type -eq [ReactionType]::RetryWithFeedback) {
                        $deferredRetry = $genReaction
                    }
                }

                # Check for tool calls
                $toolCalls = $result.Message.ToolCalls
                if (-not $toolCalls -or $toolCalls.Count -eq 0) {
                    # No tool calls - check for deferred retry
                    if ($deferredRetry) {
                        $handled = & $handleReaction $deferredRetry $step
                        if ($handled.Retry) { continue }
                    }

                    if ($result.StopReason -eq 'stop') {
                        $status = [AgentStatus]::finished
                        $stopReason = 'finished'
                    }
                    else {
                        $stalledEvent = [AgentStalledEvent]::new($Agent.Id, $Agent.Name)
                        $stalledEvent.Step = $step
                        $stalledEvent.Reason = 'No tool calls and no stop condition met'
                        $traj.AddEvent($stalledEvent)
                        & $dispatchEvent $stalledEvent | Out-Null
                        Write-Output $stalledEvent
                        $status = [AgentStatus]::stalled
                        $stopReason = 'stalled'
                    }
                    break
                }

                # Execute tool calls
                $breakLoop = $false
                foreach ($toolCall in $toolCalls) {
                    # Emit ToolStart
                    $toolStartEvent = [ToolStartEvent]::new($Agent.Id, $Agent.Name)
                    $toolStartEvent.Step = $step
                    $toolStartEvent.ToolCall = $toolCall
                    $traj.AddEvent($toolStartEvent)
                    & $dispatchEvent $toolStartEvent | Out-Null
                    Write-Output $toolStartEvent

                    $toolResult = $null
                    $toolError = $null

                    $tool = $Agent.Toolkit.Get($toolCall.Name)
                    if (-not $tool) {
                        $toolError = "Unknown tool: $($toolCall.Name)"
                        $toolResult = @{ error = $toolError }

                        $toolErrorEvent = [ToolErrorEvent]::new($Agent.Id, $Agent.Name)
                        $toolErrorEvent.Step = $step
                        $toolErrorEvent.ToolCall = $toolCall
                        $toolErrorEvent.Error = $toolError
                        $toolErrorEvent.ErrorType = 'UnknownToolError'
                        $traj.AddEvent($toolErrorEvent)
                        & $dispatchEvent $toolErrorEvent | Out-Null
                        Write-Output $toolErrorEvent
                    }
                    else {
                        try {
                            $toolResult = $tool.Invoke($toolCall.Arguments)

                            $toolEndEvent = [ToolEndEvent]::new($Agent.Id, $Agent.Name)
                            $toolEndEvent.Step = $step
                            $toolEndEvent.ToolCall = $toolCall
                            $toolEndEvent.Result = $toolResult
                            $traj.AddEvent($toolEndEvent)
                            & $dispatchEvent $toolEndEvent | Out-Null
                            Write-Output $toolEndEvent
                        }
                        catch {
                            $toolError = $_.Exception.Message
                            $toolResult = @{ error = $toolError }

                            $toolErrorEvent = [ToolErrorEvent]::new($Agent.Id, $Agent.Name)
                            $toolErrorEvent.Step = $step
                            $toolErrorEvent.ToolCall = $toolCall
                            $toolErrorEvent.Error = $toolError
                            $toolErrorEvent.ErrorType = $_.Exception.GetType().Name
                            $traj.AddEvent($toolErrorEvent)
                            & $dispatchEvent $toolErrorEvent | Out-Null
                            Write-Output $toolErrorEvent
                        }
                    }

                    # Emit ToolStep
                    $resultStr = if ($toolResult -is [string]) { $toolResult } else { ($toolResult | ConvertTo-Json -Compress -Depth 5) }
                    $toolStepEvent = [ToolStepEvent]::new($Agent.Id, $Agent.Name)
                    $toolStepEvent.Step = $step
                    $toolStepEvent.ToolCall = $toolCall
                    $toolStepEvent.Result = $toolResult
                    $toolStepEvent.Messages = @([Message]::Tool($toolCall.Id, $resultStr))
                    $toolStepEvent.Error = $toolError
                    $traj.AddEvent($toolStepEvent)
                    $steps.Add($toolStepEvent)

                    $toolReaction = & $dispatchEvent $toolStepEvent
                    Write-Output $toolStepEvent

                    if ($toolReaction) {
                        $r = $toolReaction.Reaction
                        if ($r.Type -eq [ReactionType]::Fail -or $r.Type -eq [ReactionType]::Finish) {
                            $handled = & $handleReaction $toolReaction $step
                            $status = $handled.Status
                            $stopReason = $handled.StopReason
                            $agentError = $handled.Error
                            $finishResult = $handled.Result
                            $breakLoop = $true
                            break
                        }
                        elseif ($r.Type -eq [ReactionType]::Retry -or $r.Type -eq [ReactionType]::RetryWithFeedback) {
                            $deferredRetry = $toolReaction
                        }
                    }
                }

                if ($breakLoop) { break }
                if ($status -ne [AgentStatus]::running) { break }

                # After all tools, check deferred retry
                if ($deferredRetry) {
                    $handled = & $handleReaction $deferredRetry $step
                    if ($handled.Retry) { continue }
                }
            }
            catch {
                throw
            }
        }

        # Check if stop condition caused exit
        if ($status -eq [AgentStatus]::running -and $Agent.StopCondition.Evaluate($steps.ToArray())) {
            $status = [AgentStatus]::finished
            $stopReason = 'finished'
        }
    }
    catch {
        $errorMsg = $_.Exception.Message

        $agentErrorEvent = [AgentErrorEvent]::new($Agent.Id, $Agent.Name)
        $agentErrorEvent.Step = $step
        $agentErrorEvent.Error = $errorMsg
        $agentErrorEvent.ErrorType = $_.Exception.GetType().Name
        $traj.AddEvent($agentErrorEvent)
        & $dispatchEvent $agentErrorEvent | Out-Null
        Write-Output $agentErrorEvent

        $status = [AgentStatus]::errored
        $stopReason = 'error'
        $agentError = $errorMsg
    }

    # Extract final output from trajectory
    $finalOutput = if ($finishResult) {
        $finishResult
    } else {
        $lastMsg = $traj.GetLastMessage()
        if ($lastMsg -and $lastMsg.Role -eq [MessageRole]::assistant) {
            $lastMsg.GetText()
        } else { $null }
    }

    # Emit AgentEnd
    $endEvent = [AgentEndEvent]::new($Agent.Id, $Agent.Name)
    $endEvent.Status = $status
    $endEvent.StopReason = $stopReason
    $endEvent.Output = $finalOutput
    $endEvent.Error = $agentError
    $traj.AddEvent($endEvent)
    & $dispatchEvent $endEvent | Out-Null
    Write-Output $endEvent
}
