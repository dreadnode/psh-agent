function New-SubAgentTool {
    <#
    .SYNOPSIS
    Create a tool that delegates work to a child agent
    .DESCRIPTION
    Creates a PshAgentTool that, when invoked, runs a child agent with the
    given configuration. The parent agent calls the tool with a task string,
    and the child agent runs autonomously and returns its output.

    Supports two modes:
    - In-process (default): Runs the child agent in the same PowerShell process.
      Fast, shares memory. Pass tools directly via -Tools parameter.
    - Out-of-process (-OutOfProcess): Spawns a separate pwsh process and
      communicates via named pipes. Isolated, can load tool modules independently.
    .PARAMETER Name
    Tool name (e.g., 'code_reviewer')
    .PARAMETER Description
    What the sub-agent does
    .PARAMETER ConnectionString
    Provider/model for the child (e.g., 'anthropic/claude-sonnet-4-20250514')
    .PARAMETER SystemPrompt
    System prompt for the child agent
    .PARAMETER Tools
    PshAgentTool objects for the child (in-process mode)
    .PARAMETER BuiltinTools
    Built-in tool names for the child (e.g., 'read_file', 'run_command')
    .PARAMETER ToolModules
    Module names to import as tools in child (out-of-process mode)
    .PARAMETER MaxSteps
    Child agent step limit (default: 10)
    .PARAMETER OutOfProcess
    Run in a separate pwsh process via named pipes
    .EXAMPLE
    $reviewer = New-SubAgentTool -Name 'reviewer' -Description 'Review code' `
        -ConnectionString 'anthropic/claude-sonnet-4-20250514' `
        -SystemPrompt 'You review code for bugs.' -Tools @(Read-FileContent) -MaxSteps 5
    .EXAMPLE
    $worker = New-SubAgentTool -Name 'researcher' -Description 'Research topics' `
        -ConnectionString 'anthropic/claude-sonnet-4-20250514' `
        -SystemPrompt 'You research topics.' -BuiltinTools @('run_command') `
        -MaxSteps 5 -OutOfProcess
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$Description,

        [Parameter(Mandatory)]
        [string]$ConnectionString,

        [Parameter(Mandatory)]
        [string]$SystemPrompt,

        [Parameter()]
        [PshAgentTool[]]$Tools = @(),

        [Parameter()]
        [string[]]$BuiltinTools = @(),

        [Parameter()]
        [string[]]$ToolModules = @(),

        [Parameter()]
        [int]$MaxSteps = 10,

        [Parameter()]
        [switch]$OutOfProcess
    )

    $schema = @{
        type       = 'object'
        properties = @{
            task = @{
                type        = 'string'
                description = 'The task to delegate to this sub-agent'
            }
        }
        required   = @('task')
    }

    if ($OutOfProcess) {
        # Out-of-process mode: spawn child pwsh and communicate via named pipe
        $cs = $ConnectionString
        $sp = $SystemPrompt
        $bt = $BuiltinTools
        $tm = $ToolModules
        $ms = $MaxSteps
        # Resolve module path for the child process to import
        $mp = (Get-Module PshAgent).Path
        if (-not $mp) {
            # Fallback: use the .psd1 next to this script
            $mp = Join-Path $PSScriptRoot '..' 'PshAgent.psd1' | Resolve-Path
        }

        $executeBlock = {
            param($a)
            $result = Invoke-SubAgentOutOfProcess `
                -ConnectionString $cs `
                -SystemPrompt $sp `
                -Prompt $a.task `
                -BuiltinTools $bt `
                -ToolModules $tm `
                -MaxSteps $ms `
                -ModulePath "$mp"

            if ($result.error) {
                "Sub-agent error: $($result.error)"
            }
            elseif ($result.output) {
                $result.output
            }
            else {
                '(sub-agent produced no output)'
            }
        }.GetNewClosure()
    }
    else {
        # In-process mode: run child agent directly
        $cs = $ConnectionString
        $sp = $SystemPrompt
        $tl = $Tools
        $bt = $BuiltinTools
        $ms = $MaxSteps

        $executeBlock = {
            param($a)
            $result = Invoke-SubAgentInProcess `
                -ConnectionString $cs `
                -SystemPrompt $sp `
                -Prompt $a.task `
                -Tools $tl `
                -BuiltinTools $bt `
                -MaxSteps $ms

            if ($result.error) {
                "Sub-agent error: $($result.error)"
            }
            elseif ($result.output) {
                $result.output
            }
            else {
                '(sub-agent produced no output)'
            }
        }.GetNewClosure()
    }

    return [PshAgentTool]::new($Name, $Description, $schema, $executeBlock)
}
