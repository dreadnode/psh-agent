function Import-ToolsFromModule {
    <#
    .SYNOPSIS
    Import all exported functions from a module as PshAgentTool objects
    .DESCRIPTION
    Loads a module (if not already loaded), discovers its exported functions,
    and converts each to a PshAgentTool via Import-ToolFromCommand.
    .PARAMETER Module
    Module name or path to .psm1/.psd1 file
    .PARAMETER Include
    Wildcard patterns for function names to include
    .PARAMETER Exclude
    Wildcard patterns for function names to exclude
    .PARAMETER Prefix
    Prefix to add to tool names (e.g., 'mymod_')
    .EXAMPLE
    $tools = Import-ToolsFromModule 'Microsoft.PowerShell.Management' -Include 'Get-Content', 'Set-Location'
    .EXAMPLE
    $tools = Import-ToolsFromModule './MyModule.psm1' -Prefix 'custom_'
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool[]])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Module,

        [Parameter()]
        [string[]]$Include,

        [Parameter()]
        [string[]]$Exclude,

        [Parameter()]
        [string]$Prefix
    )

    # Import the module if not already loaded
    $modInfo = Get-Module -Name $Module -ErrorAction SilentlyContinue
    if (-not $modInfo) {
        # Try as a path
        if (Test-Path $Module) {
            $modInfo = Import-Module -Name $Module -PassThru -ErrorAction Stop
        }
        else {
            $modInfo = Import-Module -Name $Module -PassThru -ErrorAction Stop
        }
    }

    # Get exported commands from the module
    $commands = Get-Command -Module $modInfo.Name -CommandType Function, Cmdlet -ErrorAction SilentlyContinue

    if (-not $commands) {
        Write-Warning "No functions or cmdlets found in module '$($modInfo.Name)'"
        return @()
    }

    $tools = [System.Collections.Generic.List[PshAgentTool]]::new()

    foreach ($cmd in $commands) {
        # Apply include filter (wildcard match)
        if ($Include) {
            $matched = $false
            foreach ($pattern in $Include) {
                if ($cmd.Name -like $pattern) { $matched = $true; break }
            }
            if (-not $matched) { continue }
        }

        # Apply exclude filter (wildcard match)
        if ($Exclude) {
            $excluded = $false
            foreach ($pattern in $Exclude) {
                if ($cmd.Name -like $pattern) { $excluded = $true; break }
            }
            if ($excluded) { continue }
        }

        # Convert to tool
        try {
            $toolName = if ($Prefix) {
                $Prefix + (ConvertTo-SnakeCase -Name $cmd.Name)
            } else {
                $null
            }

            $importParams = @{ Command = $cmd }
            if ($toolName) { $importParams['Name'] = $toolName }

            $tool = Import-ToolFromCommand @importParams
            $tools.Add($tool)
        }
        catch {
            Write-Warning "Failed to import '$($cmd.Name)' as tool: $_"
        }
    }

    return @($tools)
}
