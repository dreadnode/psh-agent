# PshAgentHook class - event matching + scriptblock handler

class PshAgentHook {
    [string]$Name
    [AgentEventType]$EventType
    [scriptblock]$Fn

    PshAgentHook([string]$name, [AgentEventType]$eventType, [scriptblock]$fn) {
        $this.Name = $name
        $this.EventType = $eventType
        $this.Fn = $fn
    }

    [bool] Matches([AgentEvent]$event) {
        if ($event.Type -ne $this.EventType) {
            return $false
        }
        # Skip ReactStep when listening to step events (prevent recursion)
        if ($event.Type -eq [AgentEventType]::ReactStep -and $this.EventType -ne [AgentEventType]::ReactStep) {
            return $false
        }
        return $true
    }

    [Reaction] Execute([AgentEvent]$event) {
        try {
            $result = & $this.Fn $event
            if ($result -is [Reaction]) {
                return $result
            }
            return $null
        }
        catch {
            # If the scriptblock throws a Reaction, catch it
            if ($_.Exception -is [Reaction]) {
                return $_.Exception
            }
            throw
        }
    }
}
