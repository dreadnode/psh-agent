# PshAgentTool and PshAgentToolkit classes

class PshAgentTool {
    [string]$Name
    [string]$Description
    [hashtable]$Parameters  # JSON Schema
    [scriptblock]$Execute

    PshAgentTool([string]$name, [string]$description, [hashtable]$parameters, [scriptblock]$execute) {
        $this.Name = $name
        $this.Description = $description
        $this.Parameters = $parameters
        $this.Execute = $execute
    }

    [object] Invoke([hashtable]$arguments) {
        try {
            return & $this.Execute $arguments
        }
        catch {
            throw "Tool '$($this.Name)' error: $_"
        }
    }

    # Get tool definition for API calls
    [hashtable] ToDefinition() {
        return @{
            Description = $this.Description
            Parameters  = $this.Parameters
        }
    }
}

class PshAgentToolkit {
    [hashtable]$Tools = @{}

    PshAgentToolkit() {}

    PshAgentToolkit([PshAgentTool[]]$tools) {
        foreach ($tool in $tools) {
            $this.Tools[$tool.Name] = $tool
        }
    }

    [void] Add([PshAgentTool]$tool) {
        $this.Tools[$tool.Name] = $tool
    }

    [void] AddRange([PshAgentTool[]]$tools) {
        foreach ($tool in $tools) {
            $this.Tools[$tool.Name] = $tool
        }
    }

    [PshAgentTool] Get([string]$name) {
        return $this.Tools[$name]
    }

    [string[]] List() {
        return @($this.Tools.Keys)
    }

    [object] Execute([string]$name, [hashtable]$arguments) {
        $tool = $this.Tools[$name]
        if (-not $tool) {
            throw "Unknown tool: $name"
        }
        return $tool.Invoke($arguments)
    }

    # Get tools as hashtable for API options
    [hashtable] ToToolDefinitions() {
        $defs = @{}
        foreach ($entry in $this.Tools.GetEnumerator()) {
            $defs[$entry.Key] = $entry.Value.ToDefinition()
        }
        return $defs
    }

    # Merge another toolkit into this one
    [void] Merge([PshAgentToolkit]$other) {
        foreach ($entry in $other.Tools.GetEnumerator()) {
            $this.Tools[$entry.Key] = $entry.Value
        }
    }
}
