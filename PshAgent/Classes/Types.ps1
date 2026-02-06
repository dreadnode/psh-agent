# PshAgent Types - Enums and basic types

enum MessageRole {
    system
    user
    assistant
    tool
}

enum AgentStatus {
    running
    stalled
    errored
    finished
    cancelled
    max_steps
}

enum StopReason {
    stop
    length
    content_filter
    tool_calls
    error
    other
    unknown
}

enum AgentEventType {
    AgentStart
    AgentEnd
    AgentStalled
    AgentError
    GenerationStart
    GenerationEnd
    GenerationStep
    GenerationError
    ToolStart
    ToolEnd
    ToolStep
    ToolError
    ReactStep
}

enum ReactionType {
    Continue
    Retry
    RetryWithFeedback
    Fail
    Finish
}

class Usage {
    [int]$InputTokens = 0
    [int]$OutputTokens = 0
    [int]$TotalTokens = 0

    Usage() {}

    Usage([int]$inputTokens, [int]$outputTokens) {
        $this.InputTokens = $inputTokens
        $this.OutputTokens = $outputTokens
        $this.TotalTokens = $inputTokens + $outputTokens
    }

    static [Usage] Zero() {
        return [Usage]::new()
    }
}
