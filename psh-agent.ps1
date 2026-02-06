#!/usr/bin/env pwsh
<#
.SYNOPSIS
    PshAgent CLI entry script
.DESCRIPTION
    Launches the PshAgent interactive CLI.
    This is a thin shim that imports the module and starts the REPL.
.PARAMETER ConnectionString
    Provider/model connection string (e.g., 'anthropic/claude-sonnet-4-20250514')
.PARAMETER SystemPrompt
    System prompt for the agent
.PARAMETER Compact
    Enable compact output mode
.EXAMPLE
    ./psh-agent.ps1
.EXAMPLE
    ./psh-agent.ps1 -ConnectionString 'anthropic/claude-sonnet-4-20250514'
.EXAMPLE
    ./psh-agent.ps1 'openai/gpt-4o' -Compact
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$ConnectionString,

    [Parameter()]
    [string]$SystemPrompt,

    [Parameter()]
    [switch]$Compact
)

$ErrorActionPreference = 'Stop'

# Import module from same directory
$modulePath = Join-Path $PSScriptRoot 'PshAgent' 'PshAgent.psd1'
if (-not (Test-Path $modulePath)) {
    Write-Error "Module not found at $modulePath"
    exit 1
}

Import-Module $modulePath -Force

# Build params
$params = @{}
if ($ConnectionString) { $params.ConnectionString = $ConnectionString }
if ($SystemPrompt) { $params.SystemPrompt = $SystemPrompt }
if ($Compact) { $params.Compact = $true }

# Start the interactive CLI
Start-PshAgent @params
