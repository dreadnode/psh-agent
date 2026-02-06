function Invoke-SubAgentInProcess {
    <#
    .SYNOPSIS
    Run a child agent in the current process and return its output
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ConnectionString,

        [Parameter(Mandatory)]
        [string]$SystemPrompt,

        [Parameter(Mandatory)]
        [string]$Prompt,

        [Parameter()]
        [PshAgentTool[]]$Tools = @(),

        [Parameter()]
        [string[]]$BuiltinTools = @(),

        [Parameter()]
        [int]$MaxSteps = 10
    )

    # Create generator from connection string
    $generator = New-Generator -ConnectionString $ConnectionString

    # Collect tools
    $allTools = [System.Collections.Generic.List[PshAgentTool]]::new()

    # Add built-in tools by name
    $builtinMap = @{
        'read_file'      = 'Read-FileContent'
        'write_file'     = 'Write-FileContent'
        'list_directory'  = 'Get-DirectoryListing'
        'run_command'    = 'Invoke-ShellCommand'
        'search_files'   = 'Search-Files'
        'grep'           = 'Search-FileContent'
    }

    foreach ($toolName in $BuiltinTools) {
        if ($builtinMap.ContainsKey($toolName)) {
            $factoryName = $builtinMap[$toolName]
            $tool = & $factoryName
            $allTools.Add($tool)
        }
        else {
            Write-Warning "Unknown built-in tool: $toolName"
        }
    }

    # Add explicitly provided tools
    foreach ($tool in $Tools) {
        $allTools.Add($tool)
    }

    # Create and run the child agent
    $agent = New-Agent -Generator $generator -Tools @($allTools) `
        -SystemPrompt $SystemPrompt -MaxSteps $MaxSteps

    $result = Invoke-Agent -Agent $agent -Prompt $Prompt

    if ($result.Status -eq [AgentStatus]::errored) {
        return @{
            Status = 'errored'
            Output = $null
            Steps  = $result.Steps
            Error  = if ($result.Error) { "$($result.Error)" } else { 'Unknown error' }
        }
    }

    return @{
        Status = "$($result.Status)"
        Output = $result.Output
        Steps  = $result.Steps
        Error  = $null
    }
}
