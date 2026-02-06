function Import-ToolFromCommand {
    <#
    .SYNOPSIS
    Convert a PowerShell command into a PshAgentTool
    .DESCRIPTION
    Inspects a command's parameter metadata and generates a PshAgentTool
    with JSON Schema parameters and an execute scriptblock that invokes
    the original command via splatting.
    .PARAMETER Command
    A CommandInfo object or command name string
    .PARAMETER Name
    Override the tool name (default: snake_case of command name)
    .PARAMETER Description
    Override the tool description (default: synopsis from Get-Help)
    .PARAMETER ExcludeParameter
    Parameter names to exclude from the schema
    .PARAMETER IncludeParameter
    Parameter names to include (excludes all others)
    .EXAMPLE
    $tool = Import-ToolFromCommand 'Get-Process' -Name 'list_processes'
    .EXAMPLE
    $tool = Import-ToolFromCommand (Get-Command Get-ChildItem) -ExcludeParameter 'Force','Hidden'
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [object]$Command,

        [Parameter()]
        [string]$Name,

        [Parameter()]
        [string]$Description,

        [Parameter()]
        [string[]]$ExcludeParameter,

        [Parameter()]
        [string[]]$IncludeParameter
    )

    # Resolve to CommandInfo
    if ($Command -is [string]) {
        $cmdInfo = Get-Command -Name $Command -ErrorAction Stop
    }
    elseif ($Command -is [System.Management.Automation.CommandInfo]) {
        $cmdInfo = $Command
    }
    else {
        throw "Command must be a string name or CommandInfo object"
    }

    # Determine tool name
    if (-not $Name) {
        $Name = ConvertTo-SnakeCase -Name $cmdInfo.Name
    }

    # Determine description from help
    if (-not $Description) {
        try {
            $help = Get-Help -Name $cmdInfo.Name -ErrorAction SilentlyContinue
            if ($help -and $help.Synopsis) {
                $Description = $help.Synopsis.Trim()
            }
        } catch { }

        if (-not $Description) {
            $Description = "Execute the $($cmdInfo.Name) command"
        }
    }

    # Build parameter schema
    $metaResult = ConvertFrom-ParameterMetadata -CommandInfo $cmdInfo `
        -ExcludeParameter $ExcludeParameter -IncludeParameter $IncludeParameter

    $schema = $metaResult.Schema
    $switchParamNames = $metaResult.SwitchParams

    # Build the execute scriptblock
    # We capture the command name and switch param list via closure
    $cn = $cmdInfo.Name
    $sp = @($switchParamNames | ForEach-Object { ConvertTo-SnakeCase -Name $_ })
    # Build a mapping from snake_case schema names back to original parameter names
    $paramNameMap = @{}
    foreach ($param in $cmdInfo.Parameters.Values) {
        $snakeName = ConvertTo-SnakeCase -Name $param.Name
        $paramNameMap[$snakeName] = $param.Name
    }
    $pnm = $paramNameMap

    $executeBlock = {
        param($a)
        $splatArgs = @{}
        foreach ($key in $a.Keys) {
            # Map snake_case back to original parameter name
            $originalName = if ($pnm.ContainsKey($key)) { $pnm[$key] } else { $key }
            if ($key -in $sp) {
                if ($a[$key] -eq $true) {
                    $splatArgs[$originalName] = [switch]::Present
                }
                continue
            }
            $splatArgs[$originalName] = $a[$key]
        }
        $result = & $cn @splatArgs 2>&1
        if ($null -eq $result) { '(no output)' }
        elseif ($result -is [string]) { $result }
        else { ($result | Out-String).TrimEnd() }
    }.GetNewClosure()

    return [PshAgentTool]::new($Name, $Description, $schema, $executeBlock)
}
