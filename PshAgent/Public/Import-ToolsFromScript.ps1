function Import-ToolsFromScript {
    <#
    .SYNOPSIS
    Import functions from a PowerShell script file as PshAgentTool objects
    .DESCRIPTION
    Snapshots the current function list, dot-sources the script, then
    discovers newly defined functions and converts each to a PshAgentTool.
    .PARAMETER Path
    Path to the .ps1 script file
    .PARAMETER Include
    Wildcard patterns for function names to include
    .PARAMETER Exclude
    Wildcard patterns for function names to exclude
    .PARAMETER Prefix
    Prefix to add to tool names (e.g., 'script_')
    .EXAMPLE
    $tools = Import-ToolsFromScript './my-tools.ps1'
    .EXAMPLE
    $tools = Import-ToolsFromScript './helpers.ps1' -Include 'Get-*' -Prefix 'helper_'
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool[]])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Path,

        [Parameter()]
        [string[]]$Include,

        [Parameter()]
        [string[]]$Exclude,

        [Parameter()]
        [string]$Prefix
    )

    $resolvedPath = Resolve-Path -Path $Path -ErrorAction Stop

    # Snapshot existing functions
    $beforeFunctions = @(Get-ChildItem Function:\ | Select-Object -ExpandProperty Name)

    # Dot-source the script to load its functions
    . $resolvedPath

    # Discover newly added functions
    $afterFunctions = @(Get-ChildItem Function:\ | Select-Object -ExpandProperty Name)
    $newFunctions = $afterFunctions | Where-Object { $_ -notin $beforeFunctions }

    if (-not $newFunctions) {
        Write-Warning "No new functions found in '$Path'"
        return @()
    }

    $tools = [System.Collections.Generic.List[PshAgentTool]]::new()

    foreach ($funcName in $newFunctions) {
        # Apply include filter (wildcard match)
        if ($Include) {
            $matched = $false
            foreach ($pattern in $Include) {
                if ($funcName -like $pattern) { $matched = $true; break }
            }
            if (-not $matched) { continue }
        }

        # Apply exclude filter (wildcard match)
        if ($Exclude) {
            $excluded = $false
            foreach ($pattern in $Exclude) {
                if ($funcName -like $pattern) { $excluded = $true; break }
            }
            if ($excluded) { continue }
        }

        # Convert to tool
        try {
            $cmd = Get-Command -Name $funcName -ErrorAction Stop

            $toolName = if ($Prefix) {
                $Prefix + (ConvertTo-SnakeCase -Name $funcName)
            } else {
                $null
            }

            $importParams = @{ Command = $cmd }
            if ($toolName) { $importParams['Name'] = $toolName }

            $tool = Import-ToolFromCommand @importParams
            $tools.Add($tool)
        }
        catch {
            Write-Warning "Failed to import '$funcName' as tool: $_"
        }
    }

    return @($tools)
}
