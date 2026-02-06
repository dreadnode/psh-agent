@{
    RootModule        = 'PshAgent.psm1'
    ModuleVersion     = '0.1.0'
    GUID              = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
    Author            = 'PshAgent'
    CompanyName       = 'PshAgent'
    Copyright         = '(c) 2025 PshAgent. All rights reserved.'
    Description       = 'PowerShell AI Agent Framework - port of dreadcode agent runtime. Supports Anthropic and OpenAI APIs with tool calling, hooks, stop conditions, and an interactive CLI.'

    PowerShellVersion = '7.0'

    # Classes must be in ScriptsToProcess to be visible outside the module
    ScriptsToProcess  = @(
        'Classes/Types.ps1'
        'Classes/Content.ps1'
        'Classes/ToolCall.ps1'
        'Classes/Message.ps1'
        'Classes/Reaction.ps1'
        'Classes/AgentEvent.ps1'
        'Classes/StopCondition.ps1'
        'Classes/Hook.ps1'
        'Classes/Tool.ps1'
        'Classes/Generator.ps1'
        'Classes/Trajectory.ps1'
        'Classes/Agent.ps1'
        'Classes/Session.ps1'
    )

    FunctionsToExport = @(
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

    CmdletsToExport   = @()
    VariablesToExport  = @()
    AliasesToExport    = @()

    PrivateData = @{
        PSData = @{
            Tags       = @('AI', 'Agent', 'LLM', 'Anthropic', 'OpenAI', 'ChatGPT', 'Claude', 'ToolCalling')
            LicenseUri = ''
            ProjectUri = ''
        }
    }
}
