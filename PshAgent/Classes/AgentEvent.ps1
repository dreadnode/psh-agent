# Agent Event classes

class AgentEvent {
    [AgentEventType]$Type
    [datetime]$Timestamp = [datetime]::UtcNow
    [string]$AgentId
    [string]$AgentName
    [AgentStatus]$Status
    [int]$Step = 0
    [hashtable]$Metrics = @{}

    AgentEvent([AgentEventType]$type, [string]$agentId) {
        $this.Type = $type
        $this.AgentId = $agentId
    }

    AgentEvent([AgentEventType]$type, [string]$agentId, [string]$agentName) {
        $this.Type = $type
        $this.AgentId = $agentId
        $this.AgentName = $agentName
    }

    # Serialize to hashtable
    [hashtable] ToHashtable() {
        $h = @{
            type      = $this.Type.ToString()
            timestamp = $this.Timestamp.ToString('o')
            agentId   = $this.AgentId
            status    = $this.Status.ToString()
            step      = $this.Step
        }
        if ($this.AgentName) { $h.agentName = $this.AgentName }
        return $h
    }
}

# Agent lifecycle events
class AgentStartEvent : AgentEvent {
    [hashtable]$Inputs = @{}
    [hashtable]$Params = @{}

    AgentStartEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::AgentStart, $agentId, $agentName) {
        $this.Status = [AgentStatus]::running
    }
}

class AgentEndEvent : AgentEvent {
    [string]$StopReason = 'finished'
    [string]$Output
    [string]$Error

    AgentEndEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::AgentEnd, $agentId, $agentName) {}
}

class AgentStalledEvent : AgentEvent {
    [string]$Reason

    AgentStalledEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::AgentStalled, $agentId, $agentName) {
        $this.Status = [AgentStatus]::stalled
    }
}

class AgentErrorEvent : AgentEvent {
    [string]$Error
    [string]$ErrorType

    AgentErrorEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::AgentError, $agentId, $agentName) {
        $this.Status = [AgentStatus]::errored
    }
}

# Generation events
class GenerationStartEvent : AgentEvent {
    [string]$Model

    GenerationStartEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::GenerationStart, $agentId, $agentName) {
        $this.Status = [AgentStatus]::running
    }
}

class GenerationEndEvent : AgentEvent {
    [Message[]]$Messages
    [Usage]$Usage
    [string]$StopReason
    [string]$Model

    GenerationEndEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::GenerationEnd, $agentId, $agentName) {
        $this.Status = [AgentStatus]::running
    }
}

class GenerationStepEvent : AgentEvent {
    [Message[]]$Messages
    [Usage]$Usage
    [string]$StopReason
    [string]$Model
    [bool]$GenerationFailed = $false

    GenerationStepEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::GenerationStep, $agentId, $agentName) {
        $this.Status = [AgentStatus]::running
    }
}

class GenerationErrorEvent : AgentEvent {
    [string]$Error
    [string]$ErrorType
    [string]$Model

    GenerationErrorEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::GenerationError, $agentId, $agentName) {
        $this.Status = [AgentStatus]::running
    }
}

# Tool events
class ToolStartEvent : AgentEvent {
    [ToolCall]$ToolCall

    ToolStartEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::ToolStart, $agentId, $agentName) {
        $this.Status = [AgentStatus]::running
    }
}

class ToolEndEvent : AgentEvent {
    [ToolCall]$ToolCall
    $Result
    [bool]$Stop = $false

    ToolEndEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::ToolEnd, $agentId, $agentName) {
        $this.Status = [AgentStatus]::running
    }
}

class ToolStepEvent : AgentEvent {
    [ToolCall]$ToolCall
    $Result
    [Message[]]$Messages
    [Usage]$Usage
    [string]$Error
    [bool]$Stop = $false

    ToolStepEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::ToolStep, $agentId, $agentName) {
        $this.Status = [AgentStatus]::running
        $this.Usage = [Usage]::Zero()
    }
}

class ToolErrorEvent : AgentEvent {
    [ToolCall]$ToolCall
    [string]$Error
    [string]$ErrorType

    ToolErrorEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::ToolError, $agentId, $agentName) {
        $this.Status = [AgentStatus]::running
    }
}

# Hook events
class ReactStepEvent : AgentEvent {
    [Message[]]$Messages = @()
    [Usage]$Usage
    [string]$HookName
    [string]$ReactionType
    [string]$Feedback
    [string]$Reason

    ReactStepEvent([string]$agentId, [string]$agentName) : base([AgentEventType]::ReactStep, $agentId, $agentName) {
        $this.Status = [AgentStatus]::running
        $this.Usage = [Usage]::Zero()
    }
}
