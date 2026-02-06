# Trajectory - holds the execution history of an agent run

class Trajectory {
    [string]$SessionId
    [string]$AgentId
    [string]$AgentName
    [string]$SystemPrompt
    hidden [System.Collections.Generic.List[AgentEvent]]$_events = [System.Collections.Generic.List[AgentEvent]]::new()
    hidden [System.Collections.Generic.List[Message]]$_feedbackMessages = [System.Collections.Generic.List[Message]]::new()

    Trajectory([string]$agentId) {
        $this.SessionId = [guid]::NewGuid().ToString()
        $this.AgentId = $agentId
    }

    Trajectory([string]$agentId, [string]$agentName, [string]$systemPrompt) {
        $this.SessionId = [guid]::NewGuid().ToString()
        $this.AgentId = $agentId
        $this.AgentName = $agentName
        $this.SystemPrompt = $systemPrompt
    }

    [void] AddEvent([AgentEvent]$event) {
        $this._events.Add($event)
    }

    [AgentEvent[]] GetEvents() {
        return $this._events.ToArray()
    }

    # Get step events (GenerationStep and ToolStep)
    [AgentEvent[]] GetSteps() {
        return @($this._events | Where-Object {
            $_.Type -eq [AgentEventType]::GenerationStep -or
            $_.Type -eq [AgentEventType]::ToolStep
        })
    }

    # Reconstruct messages from steps
    [Message[]] GetMessages() {
        $messages = [System.Collections.Generic.List[Message]]::new()

        if ($this.SystemPrompt) {
            $messages.Add([Message]::System($this.SystemPrompt))
        }

        foreach ($step in $this.GetSteps()) {
            if ($step.Type -eq [AgentEventType]::GenerationStep -and $step.Messages) {
                foreach ($m in $step.Messages) {
                    $messages.Add($m)
                }
            }
            elseif ($step.Type -eq [AgentEventType]::ToolStep -and $step.Messages) {
                foreach ($m in $step.Messages) {
                    $messages.Add($m)
                }
            }
        }

        return $messages.ToArray()
    }

    # Calculate total token usage
    [Usage] GetUsage() {
        $inputTokens = 0
        $outputTokens = 0

        foreach ($event in $this._events) {
            if ($event.Type -eq [AgentEventType]::GenerationStep -and $event.Usage) {
                $inputTokens += $event.Usage.InputTokens
                $outputTokens += $event.Usage.OutputTokens
            }
        }

        return [Usage]::new($inputTokens, $outputTokens)
    }

    # Get the last message
    [Message] GetLastMessage() {
        $msgs = $this.GetMessages()
        if ($msgs.Count -gt 0) {
            return $msgs[-1]
        }
        return $null
    }

    # Get current step number
    [int] GetCurrentStep() {
        return $this.GetSteps().Count
    }

    # Add feedback message (for RetryWithFeedback)
    [void] AddFeedback([string]$feedback) {
        $this._feedbackMessages.Add([Message]::User($feedback))
    }

    # Get messages including pending feedback for next generation
    [Message[]] GetMessagesForGeneration([string]$userInput) {
        $messages = [System.Collections.Generic.List[Message]]::new($this.GetMessages())

        # Add any pending feedback
        foreach ($fb in $this._feedbackMessages) {
            $messages.Add($fb)
        }
        $this._feedbackMessages.Clear()

        # Add new user input if provided
        if ($userInput) {
            $messages.Add([Message]::User($userInput))
        }

        return $messages.ToArray()
    }

    # Overload without user input
    [Message[]] GetMessagesForGeneration() {
        return $this.GetMessagesForGeneration($null)
    }

    # Serialize to hashtable
    [hashtable] ToHashtable() {
        return @{
            sessionId    = $this.SessionId
            agentId      = $this.AgentId
            agentName    = $this.AgentName
            systemPrompt = $this.SystemPrompt
            events       = @($this._events | ForEach-Object { $_.ToHashtable() })
        }
    }
}
