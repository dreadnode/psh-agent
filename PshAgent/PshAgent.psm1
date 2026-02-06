# PshAgent Module Root Loader
# Dot-sources all files in the correct order

$ModuleRoot = $PSScriptRoot

# 1. Classes (order matters - dependencies first)
. "$ModuleRoot/Classes/Types.ps1"
. "$ModuleRoot/Classes/Content.ps1"
. "$ModuleRoot/Classes/ToolCall.ps1"
. "$ModuleRoot/Classes/Message.ps1"
. "$ModuleRoot/Classes/Reaction.ps1"
. "$ModuleRoot/Classes/AgentEvent.ps1"
. "$ModuleRoot/Classes/StopCondition.ps1"
. "$ModuleRoot/Classes/Hook.ps1"
. "$ModuleRoot/Classes/Tool.ps1"
. "$ModuleRoot/Classes/Generator.ps1"
. "$ModuleRoot/Classes/Trajectory.ps1"
. "$ModuleRoot/Classes/Agent.ps1"
. "$ModuleRoot/Classes/Session.ps1"

# 2. Private functions
$privateFunctions = Get-ChildItem -Path "$ModuleRoot/Private/*.ps1" -ErrorAction SilentlyContinue
foreach ($file in $privateFunctions) {
    . $file.FullName
}

# 3. Public functions
$publicFunctions = Get-ChildItem -Path "$ModuleRoot/Public/*.ps1" -ErrorAction SilentlyContinue
foreach ($file in $publicFunctions) {
    . $file.FullName
}

# 4. Tool factories (these are functions that return PshAgentTool instances)
$toolFunctions = Get-ChildItem -Path "$ModuleRoot/Tools/*.ps1" -ErrorAction SilentlyContinue
foreach ($file in $toolFunctions) {
    . $file.FullName
}

# Export public functions
$exportedFunctions = @(
    # Generator
    'New-Generator'
    'Invoke-Generate'
    'Invoke-GenerateStream'

    # Agent
    'New-Agent'
    'Invoke-Agent'
    'Invoke-AgentStream'

    # Messages
    'New-Message'

    # Tools
    'New-Tool'
    'New-Toolkit'

    # Built-in tool factories
    'Read-FileContent'
    'Write-FileContent'
    'Get-DirectoryListing'
    'Invoke-ShellCommand'
    'Search-Files'
    'Search-FileContent'
    'New-NtResearchAgent'

    # Hooks
    'New-Hook'
    'New-BackoffOnErrorHook'
    'New-BackoffOnRatelimitHook'
    'New-RetryWithFeedbackHook'
    'New-DangerousCommandHook'

    # Reactions
    'New-Reaction'

    # Stop conditions
    'New-StopCondition'
    'New-StepCountCondition'
    'New-ToolUseCondition'
    'New-TokenUsageCondition'
    'New-ElapsedTimeCondition'
    'New-OutputPatternCondition'
    'New-ConsecutiveErrorCondition'

    # Sessions
    'Save-AgentSession'
    'Get-AgentSession'
    'Remove-AgentSession'

    # CLI
    'Start-PshAgent'
    'Invoke-SlashCommand'

    # Tool Import
    'Import-ToolFromCommand'
    'Import-ToolsFromModule'
    'Import-ToolsFromScript'

    # Sub-Agents
    'New-SubAgentTool'
)

Export-ModuleMember -Function $exportedFunctions
