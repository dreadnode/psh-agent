function New-Agent {
    <#
    .SYNOPSIS
    Create an agent with generator, tools, hooks, and stop conditions
    .PARAMETER Generator
    A PshGenerator instance
    .PARAMETER Name
    Optional agent name
    .PARAMETER SystemPrompt
    System prompt for the agent
    .PARAMETER Toolkit
    PshAgentToolkit instance
    .PARAMETER Tools
    Array of PshAgentTool objects (alternative to Toolkit)
    .PARAMETER StopCondition
    A StopCondition instance
    .PARAMETER MaxSteps
    Maximum steps (default: 10, used if StopCondition not provided)
    .PARAMETER Hooks
    Array of PshAgentHook instances
    .PARAMETER GenerateOptions
    Additional options for LLM generation
    .EXAMPLE
    $agent = New-Agent -Generator $gen -Toolkit $toolkit -SystemPrompt 'You are a helpful assistant.'
    .EXAMPLE
    $agent = New-Agent -Generator $gen -Tools @($readFile, $writeFile) -StopCondition (New-StepCountCondition 20)
    #>
    [CmdletBinding()]
    [OutputType([PshAgent])]
    param(
        [Parameter(Mandatory)]
        [PshGenerator]$Generator,

        [Parameter()]
        [string]$Name,

        [Parameter()]
        [string]$SystemPrompt,

        [Parameter()]
        [PshAgentToolkit]$Toolkit,

        [Parameter()]
        [PshAgentTool[]]$Tools,

        [Parameter()]
        [StopCondition]$StopCondition,

        [Parameter()]
        [int]$MaxSteps = 10,

        [Parameter()]
        [PshAgentHook[]]$Hooks = @(),

        [Parameter()]
        [hashtable]$GenerateOptions = @{}
    )

    $config = @{
        Generator       = $Generator
        Name            = $Name
        SystemPrompt    = $SystemPrompt
        Toolkit         = $Toolkit
        Tools           = $Tools
        StopCondition   = $StopCondition
        MaxSteps        = $MaxSteps
        Hooks           = $Hooks
        GenerateOptions = $GenerateOptions
    }

    return [PshAgent]::new($config)
}
