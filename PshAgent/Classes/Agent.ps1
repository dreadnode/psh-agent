# PshAgent - state holder class

class PshAgent {
    [string]$Id
    [string]$Name
    [PshGenerator]$Generator
    [string]$SystemPrompt
    [PshAgentToolkit]$Toolkit
    [StopCondition]$StopCondition
    [PshAgentHook[]]$Hooks = @()
    [hashtable]$GenerateOptions = @{}

    PshAgent([hashtable]$config) {
        $this.Id = [guid]::NewGuid().ToString()
        $this.Name = $config.Name
        $this.Generator = $config.Generator
        $this.SystemPrompt = $config.SystemPrompt
        $this.GenerateOptions = if ($config.GenerateOptions) { $config.GenerateOptions } else { @{} }
        $this.Hooks = if ($config.Hooks) { $config.Hooks } else { @() }

        # Set up toolkit
        if ($config.Toolkit -is [PshAgentToolkit]) {
            $this.Toolkit = $config.Toolkit
        }
        elseif ($config.Tools -is [PshAgentTool[]]) {
            $this.Toolkit = [PshAgentToolkit]::new($config.Tools)
        }
        else {
            $this.Toolkit = [PshAgentToolkit]::new()
        }

        # Set up stop condition (backwards compatible with MaxSteps)
        if ($config.StopCondition) {
            $this.StopCondition = $config.StopCondition
        }
        else {
            $maxSteps = if ($config.MaxSteps) { $config.MaxSteps } else { 10 }
            $ms = $maxSteps
            $this.StopCondition = [StopCondition]::new(
                "stop_on_step_count($maxSteps)",
                { param($steps) $steps.Count -ge $ms }.GetNewClosure()
            )
        }
    }
}
