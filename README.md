# PshAgent

PowerShell 7+ AI agent framework with tool calling, hooks, stop conditions, and an interactive CLI. Port of the [dreadcode](https://github.com/dreadnode) agent runtime.

Supports **Anthropic** (Claude) and **OpenAI** (GPT) APIs. Zero external module dependencies.

```
  ____  _____ _   _    _                    _
 |  _ \/ ____| | | |  / \   __ _  ___ _ __ | |_
 | |_) \___ \| |_| | / _ \ / _  |/ _ \ '_ \| __|
 |  __/ ___) |  _  |/ ___ \ (_| |  __/ | | | |_
 |_|  |____/|_| |_/_/   \_\__, |\___|_| |_|\__|
                          |___/
```

## Quick Start

```powershell
# Set your API key
$env:ANTHROPIC_API_KEY = 'sk-ant-...'
# or
$env:OPENAI_API_KEY = 'sk-...'

# Launch the interactive CLI
./psh-agent.ps1

# Specify a model
./psh-agent.ps1 'anthropic/claude-sonnet-4-20250514'

# Use OpenAI
./psh-agent.ps1 'openai/gpt-4o' -Compact
```

## Requirements

- PowerShell 7.0+
- An API key for Anthropic or OpenAI (set via environment variable)

## Installation

```powershell
git clone git@github.com:dreadnode/psh-agent.git
cd psh-agent
./psh-agent.ps1
```

Or import the module directly in your scripts:

```powershell
Import-Module ./PshAgent/PshAgent.psd1
```

---

## Table of Contents

- [Interactive CLI](#interactive-cli)
- [Programmatic Usage](#programmatic-usage)
  - [Generator](#generator)
  - [Tools](#tools)
  - [Agent](#agent)
  - [Streaming](#streaming)
  - [Stop Conditions](#stop-conditions)
  - [Hooks](#hooks)
  - [Sessions](#sessions)
- [Built-in Tools](#built-in-tools)
- [Tool Import](#tool-import)
- [Sub-Agents](#sub-agents)
- [Architecture](#architecture)
- [API Reference](#api-reference)

---

## Interactive CLI

Launch with `Start-PshAgent` or the `psh-agent.ps1` shim:

```powershell
./psh-agent.ps1 'anthropic/claude-sonnet-4-20250514'
```

The CLI provides a REPL with tool calling, colored output, spinners, and slash commands. It ships with 6 built-in tools (file read/write, directory listing, shell commands, file search, grep) and default hooks for rate limit backoff, dangerous command detection, and stall recovery.

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/quit` `/exit` | Exit the CLI |
| `/clear` | Clear conversation history |
| `/model [conn]` | Show or change model |
| `/compact` | Toggle compact output mode |
| `/tokens` | Show token usage |
| `/system [prompt]` | Show or set system prompt |
| `/tools` | List available tools |
| `/hooks` | List active hooks |
| `/session` | Show current session info |
| `/sessions` | List saved sessions |
| `/save [name]` | Save current session |
| `/load <id>` | Load a saved session |
| `/delete <id>` | Delete a saved session |

### CLI Parameters

```powershell
Start-PshAgent
    [-ConnectionString] <string>   # 'provider/model' (default: anthropic/claude-sonnet-4-20250514)
    [-SystemPrompt <string>]       # Custom system prompt
    [-Tools <PshAgentTool[]>]      # Custom tools (default: all built-in)
    [-Hooks <PshAgentHook[]>]      # Custom hooks
    [-StopCondition <StopCondition>]
    [-MaxSteps <int>]              # Default: 50
    [-Compact]                     # Compact output mode
```

---

## Programmatic Usage

### Generator

A generator wraps an LLM API behind a connection string:

```powershell
$gen = New-Generator 'anthropic/claude-sonnet-4-20250514'
$gen = New-Generator 'openai/gpt-4o' -Defaults @{ temperature = 0.7; max_tokens = 2048 }
```

Direct generation without an agent:

```powershell
$result = Invoke-Generate -Generator $gen -Messages @(
    New-Message -Role user -Content 'What is 2+2?'
)

$result.Message.GetText()           # "4"
$result.Usage.InputTokens           # token counts
$result.StopReason                  # "stop"
```

### Tools

Define custom tools with a name, description, JSON Schema parameters, and an execute scriptblock:

```powershell
$calculator = New-Tool -Name 'add' `
    -Description 'Add two numbers' `
    -Parameters @{
        type       = 'object'
        properties = @{
            a = @{ type = 'number'; description = 'First number' }
            b = @{ type = 'number'; description = 'Second number' }
        }
        required = @('a', 'b')
    } `
    -Execute {
        param($a)  # receives a hashtable of arguments
        [double]$a.a + [double]$a.b
    }
```

> **Note:** Do not use `$args` as the parameter name in `-Execute` scriptblocks — it's a reserved PowerShell automatic variable. Use `$a` or any other name.

Collect tools into a toolkit:

```powershell
$toolkit = New-Toolkit -Tools @($calculator, (Read-FileContent), (Invoke-ShellCommand))
```

### Agent

An agent combines a generator, tools, stop conditions, and hooks:

```powershell
$agent = New-Agent -Generator $gen `
    -Tools @($calculator, (Read-FileContent)) `
    -SystemPrompt 'You are a helpful assistant.' `
    -MaxSteps 10

$result = Invoke-Agent -Agent $agent -Prompt 'What is 42 + 58?'

$result.Status     # finished
$result.Output     # "42 + 58 = 100"
$result.Steps      # 2
$result.Usage      # Usage object with InputTokens, OutputTokens, TotalTokens
```

For multi-turn, pass the trajectory back:

```powershell
$r1 = Invoke-Agent -Agent $agent -Prompt 'Read config.json'
$r2 = Invoke-Agent -Agent $agent -Prompt 'Now update the version' -Trajectory $r1.Trajectory
```

### Streaming

Stream individual events from the agent loop:

```powershell
Invoke-AgentStream -Agent $agent -Prompt 'Find all .ps1 files' | ForEach-Object {
    switch ($_.GetType().Name) {
        'GenerationStepEvent' { Write-Host "Step $($_.Step)" }
        'ToolStartEvent'      { Write-Host "Calling $($_.ToolCall.Name)..." }
        'ToolEndEvent'        { Write-Host "Result: $($_.Result)" }
        'AgentEndEvent'       { Write-Host "Done: $($_.Output)" }
    }
}
```

Stream raw LLM output (text deltas, tool calls):

```powershell
Invoke-GenerateStream -Generator $gen -Messages @(New-Message -Role user -Content 'Hello') |
    Where-Object { $_.Type -eq 'text-delta' } |
    ForEach-Object { Write-Host $_.TextDelta -NoNewline }
```

### Stop Conditions

Control when the agent loop terminates. All conditions support composition with `.And()`, `.Or()`, `.Not()`:

```powershell
# Stop after N steps
$cond = New-StepCountCondition 10

# Stop when a specific tool is used
$cond = New-ToolUseCondition 'submit'
$cond = New-ToolUseCondition 'run_command' -Count 3

# Stop on token limit
$cond = New-TokenUsageCondition 100000
$cond = New-TokenUsageCondition 50000 -Mode input

# Stop on time limit
$cond = New-ElapsedTimeCondition 300  # 5 minutes

# Stop when output matches a pattern
$cond = New-OutputPatternCondition 'DONE'
$cond = New-OutputPatternCondition '^\d+$' -Regex

# Stop after N consecutive tool errors
$cond = New-ConsecutiveErrorCondition 3

# Compose conditions
$cond = (New-StepCountCondition 20).Or((New-TokenUsageCondition 100000))
$cond = (New-StepCountCondition 5).And((New-ElapsedTimeCondition 60))

# Custom condition
$cond = New-StopCondition -Name 'custom' -Fn {
    param($steps)
    $steps.Count -ge 10
}
```

### Hooks

Hooks react to agent events and control execution flow. A hook receives an `AgentEvent` and returns a `Reaction` (or `$null` to take no action):

```powershell
# Custom logging hook
$logger = New-Hook -Name 'logger' -EventType GenerationStep -Fn {
    param($event)
    Write-Host "Step $($event.Step): $($event.Usage.TotalTokens) tokens"
}

# Custom error handler
$errorHandler = New-Hook -Name 'error_handler' -EventType ToolError -Fn {
    param($event)
    if ($event.Error -like '*timeout*') {
        return New-Reaction -Type RetryWithFeedback -Feedback 'Try a simpler approach.'
    }
    if ($event.Error -like '*permission*') {
        return New-Reaction -Type Fail -Reason $event.Error
    }
}

$agent = New-Agent -Generator $gen -Tools $tools -Hooks @($logger, $errorHandler)
```

#### Built-in Hooks

```powershell
# Exponential backoff on rate limits
$hook = New-BackoffOnRatelimitHook -MaxTries 8 -MaxTime 300

# Block dangerous shell commands (rm, sudo, chmod, etc.)
$hook = New-DangerousCommandHook
$hook = New-DangerousCommandHook -ExtraCommands @('fdisk', 'format')

# Retry with feedback when agent stalls
$hook = New-RetryWithFeedbackHook -Feedback 'Use a tool to make progress.'

# Generic error backoff
$hook = New-BackoffOnErrorHook -ErrorTypes @('RateLimitError', 'APIError') -MaxTries 10
```

#### Reaction Types

Hooks return reactions to control the agent loop:

| Reaction | Priority | Effect |
|----------|----------|--------|
| `Finish` | 5 (highest) | Stop agent, mark as finished |
| `Fail` | 4 | Stop agent, mark as errored |
| `Retry` | 3 | Retry the current step |
| `RetryWithFeedback` | 3 | Retry with a feedback message injected |
| `Continue` | 2 (lowest) | Continue normally |

When multiple hooks fire, the highest-priority reaction wins.

### Sessions

Save and restore conversation sessions to `~/.psh-agent/sessions/`:

```powershell
# List all sessions
Get-AgentSession

# Load a session
$session = Get-AgentSession -Id 'session-20250205-abc123'

# Delete a session
Remove-AgentSession -Id 'session-20250205-abc123'
Remove-AgentSession -All
```

Session persistence is automatic in the interactive CLI via `/save` and `/load`.

---

## Built-in Tools

Six tools ship with the module. Each factory function returns a `PshAgentTool` instance:

| Function | Tool Name | Description |
|----------|-----------|-------------|
| `Read-FileContent` | `read_file` | Read file contents |
| `Write-FileContent` | `write_file` | Write content to a file (creates parent dirs) |
| `Get-DirectoryListing` | `list_directory` | List files and directories |
| `Invoke-ShellCommand` | `run_command` | Execute a shell command (30s timeout) |
| `Search-Files` | `search_files` | Find files by glob pattern (max 50 results) |
| `Search-FileContent` | `grep` | Search file contents by pattern (max 100 results) |

Use them directly:

```powershell
$tools = @(
    Read-FileContent
    Write-FileContent
    Get-DirectoryListing
    Invoke-ShellCommand
    Search-Files
    Search-FileContent
)

$agent = New-Agent -Generator $gen -Tools $tools -MaxSteps 20
```

---

## Tool Import

Auto-convert PowerShell functions and cmdlets into agent tools. Parameter metadata is inspected to generate JSON Schema, and a splatting execute block is created automatically.

### Import a Single Command

```powershell
$tool = Import-ToolFromCommand 'Get-Process' -Name 'list_processes'
$tool.Name         # 'list_processes'
$tool.Parameters   # JSON Schema with name, id, etc.
$tool.Invoke(@{ Name = 'pwsh' })  # returns process info
```

Override the name or description, filter parameters:

```powershell
$tool = Import-ToolFromCommand 'Get-ChildItem' `
    -Name 'list_files' `
    -Description 'List files in a directory' `
    -IncludeParameter 'Path', 'Filter', 'Recurse'
```

### Import from a Module

```powershell
# Import specific functions from a module
$tools = Import-ToolsFromModule 'Microsoft.PowerShell.Management' `
    -Include 'Get-Content', 'Set-Location', 'Get-ChildItem'

# Import all functions with a prefix
$tools = Import-ToolsFromModule './MyModule.psm1' -Prefix 'custom_'

# Exclude functions by wildcard
$tools = Import-ToolsFromModule 'SomeModule' -Exclude 'Set-*', 'Remove-*'
```

### Import from a Script

```powershell
# Dot-sources the script and imports any new functions
$tools = Import-ToolsFromScript './my-tools.ps1'
$tools = Import-ToolsFromScript './helpers.ps1' -Include 'Get-*' -Prefix 'helper_'
```

### Use Imported Tools with an Agent

```powershell
$tools = Import-ToolsFromModule 'Microsoft.PowerShell.Management' `
    -Include 'Get-Process', 'Get-Service', 'Get-ChildItem'

$agent = New-Agent -Generator $gen -Tools $tools `
    -SystemPrompt 'Use tools to answer questions.' -MaxSteps 5

$result = Invoke-Agent -Agent $agent -Prompt 'What PowerShell processes are running?'
```

Works with binary cmdlets too — PowerShell's parameter binding handles type coercion from the string/JSON values the LLM sends.

---

## Sub-Agents

Delegate work to child agents exposed as tools. The parent agent calls a sub-agent tool with a task string, and the child runs autonomously and returns its output.

### In-Process (default)

Runs the child agent in the same PowerShell process. Fast, shares memory.

```powershell
$reviewer = New-SubAgentTool -Name 'reviewer' `
    -Description 'Review code for bugs and security issues' `
    -ConnectionString 'anthropic/claude-sonnet-4-20250514' `
    -SystemPrompt 'You review code for bugs and security issues.' `
    -Tools @(Read-FileContent) `
    -MaxSteps 5

$agent = New-Agent -Generator $gen -Tools @($reviewer, (Read-FileContent)) -MaxSteps 5
$result = Invoke-Agent -Agent $agent -Prompt 'Have the reviewer check PshAgent/Classes/Agent.ps1'
```

### Out-of-Process

Spawns a separate `pwsh` process and communicates via named pipes. Isolated, can load tool modules independently.

```powershell
$worker = New-SubAgentTool -Name 'researcher' `
    -Description 'Research topics using shell commands' `
    -ConnectionString 'anthropic/claude-sonnet-4-20250514' `
    -SystemPrompt 'You research topics using available tools.' `
    -BuiltinTools @('run_command', 'read_file', 'list_directory') `
    -ToolModules @('./SomeModule.psm1') `
    -MaxSteps 10 -OutOfProcess

$agent = New-Agent -Generator $gen -Tools @($worker) -MaxSteps 3
$result = Invoke-Agent -Agent $agent -Prompt 'Have the researcher find what OS we are on'
```

### NtObjectManager Research Agent

Pre-configured sub-agent for Windows security research with James Forshaw's [NtObjectManager](https://github.com/googleprojectzero/sandbox-attacksurface-analysis-tools) and optionally [OleViewDotNet](https://github.com/tyranid/oleviewdotnet).

```powershell
# NT object research only
$researcher = New-NtResearchAgent `
    -NtObjectManagerPath '~/NtObjectManager'

# NT + COM/DCOM research
$researcher = New-NtResearchAgent `
    -NtObjectManagerPath '~/NtObjectManager' `
    -OleViewDotNetPath '~/OleViewDotNetPS'

# Out-of-process with full module loaded
$researcher = New-NtResearchAgent `
    -NtObjectManagerPath '~/NtObjectManager' `
    -OutOfProcess

$agent = New-Agent -Generator $gen -Tools @($researcher) -MaxSteps 5
$result = Invoke-Agent -Agent $agent -Prompt 'Find services with weak ACLs'
```

The in-process mode loads ~40 curated NT tools + ~35 COM tools + `run_powershell` for ad-hoc access to the full 330+ function surface. Out-of-process loads the full modules in the child process.

Curated tool categories:
- **Access auditing** — `Get-AccessibleProcess`, `Get-AccessibleFile`, `Get-AccessibleKey`, `Get-AccessibleNamedPipe`, `Get-AccessibleService`
- **RPC enumeration** — `Get-RpcServer`, `Get-RpcEndpoint`, `Format-RpcServer`
- **Token analysis** — `Get-NtToken`, `Get-NtTokenPrivilege`, `Test-NtTokenImpersonation`
- **Object namespace** — `Get-NtDirectoryEntry`, `Get-NtObject`, `Get-NtSecurityDescriptor`
- **COM/DCOM** — `Get-ComClass`, `Get-ComProcess`, `Select-ComAccess`, `Get-ComProxy`
- **Services** — `Get-Win32Service`, `Get-Win32ServiceConfig`, `Get-Win32ServiceSecurityDescriptor`

---

## Architecture

```
PshAgent/
├── PshAgent.psd1              # Module manifest
├── PshAgent.psm1              # Root loader
├── Classes/                   # 13 class files (loaded via ScriptsToProcess)
│   ├── Types.ps1              # Enums: MessageRole, AgentStatus, StopReason, etc.
│   ├── Content.ps1            # Content helpers
│   ├── ToolCall.ps1           # ToolCall, ToolResult
│   ├── Message.ps1            # Message with static factories
│   ├── Reaction.ps1           # Reaction class
│   ├── AgentEvent.ps1         # 13 event subclasses
│   ├── StopCondition.ps1      # Composable stop conditions
│   ├── Hook.ps1               # Event hooks
│   ├── Tool.ps1               # PshAgentTool, PshAgentToolkit
│   ├── Generator.ps1          # Connection string parsing, provider dispatch
│   ├── Trajectory.ps1         # Execution history, message reconstruction
│   ├── Agent.ps1              # PshAgent state holder
│   └── Session.ps1            # Session persistence
├── Private/                   # 16 internal functions
│   ├── Invoke-AnthropicApi.ps1
│   ├── Invoke-OpenAIApi.ps1
│   ├── Invoke-StreamingRequest.ps1  # SSE via HttpClient
│   ├── ConvertTo-AnthropicMessages.ps1
│   ├── ConvertTo-OpenAIMessages.ps1
│   ├── ConvertTo-JsonSchema.ps1
│   ├── ConvertFrom-PowerShellType.ps1   # .NET type → JSON Schema
│   ├── ConvertTo-SnakeCase.ps1          # Verb-Noun → snake_case
│   ├── ConvertFrom-ParameterMetadata.ps1 # CommandInfo → JSON Schema
│   ├── Invoke-SubAgentInProcess.ps1     # In-process child agent
│   ├── Invoke-SubAgentOutOfProcess.ps1  # Named pipe parent side
│   ├── Start-SubAgentWorker.ps1         # Named pipe child entry point
│   ├── Select-WinningReaction.ps1
│   ├── Format-AgentOutput.ps1
│   ├── Write-StreamChunk.ps1
│   └── Get-SpinnerFrame.ps1
├── Public/                    # 31 exported functions
│   ├── New-Generator.ps1
│   ├── Invoke-Generate.ps1
│   ├── Invoke-GenerateStream.ps1
│   ├── New-Agent.ps1
│   ├── Invoke-Agent.ps1
│   ├── Invoke-AgentStream.ps1
│   ├── New-Message.ps1
│   ├── New-Tool.ps1
│   ├── New-Toolkit.ps1
│   ├── Import-ToolFromCommand.ps1       # Command → PshAgentTool
│   ├── Import-ToolsFromModule.ps1       # Module → PshAgentTool[]
│   ├── Import-ToolsFromScript.ps1       # Script → PshAgentTool[]
│   ├── New-SubAgentTool.ps1             # Sub-agent tool factory
│   ├── New-Hook.ps1
│   ├── New-BackoffOnErrorHook.ps1
│   ├── New-BackoffOnRatelimitHook.ps1
│   ├── New-RetryWithFeedbackHook.ps1
│   ├── New-DangerousCommandHook.ps1
│   ├── New-Reaction.ps1
│   ├── New-StopCondition.ps1
│   ├── New-StepCountCondition.ps1
│   ├── New-ToolUseCondition.ps1
│   ├── New-TokenUsageCondition.ps1
│   ├── New-ElapsedTimeCondition.ps1
│   ├── New-OutputPatternCondition.ps1
│   ├── New-ConsecutiveErrorCondition.ps1
│   ├── Save-AgentSession.ps1
│   ├── Get-AgentSession.ps1
│   ├── Remove-AgentSession.ps1
│   ├── Start-PshAgent.ps1
│   └── Invoke-SlashCommand.ps1
└── Tools/                     # 7 built-in tool factories
    ├── Read-FileContent.ps1
    ├── Write-FileContent.ps1
    ├── Get-DirectoryListing.ps1
    ├── Invoke-ShellCommand.ps1
    ├── Search-Files.ps1
    ├── Search-FileContent.ps1
    └── New-NtResearchAgent.ps1          # NtObjectManager + OleViewDotNet sub-agent
```

### Key Design Decisions

- **Classes hold state, functions operate on them.** PowerShell class methods can't emit to the pipeline, so the agent loop lives in `Invoke-AgentStream` (a function), not a class method.
- **No external dependencies.** Non-streaming calls use `Invoke-RestMethod`. SSE streaming uses `System.Net.Http.HttpClient` with `ResponseHeadersRead` + `StreamReader`.
- **Stop condition composition.** `.And()`, `.Or()`, `.Not()` methods use `.GetNewClosure()` for scriptblock closures.
- **Hook priority.** When multiple hooks fire on the same event, the highest-priority reaction wins: Finish(5) > Fail(4) > Retry(3) > Continue(2).
- **Classes exported via `ScriptsToProcess`.** PowerShell classes dot-sourced in a `.psm1` are module-scoped. The manifest's `ScriptsToProcess` runs class files in the caller's scope so types like `[PshAgent]` and `[Message]` are visible outside the module.

---

## API Reference

### Exported Functions (38)

#### Generator
| Function | Description |
|----------|-------------|
| `New-Generator` | Create a generator from a connection string |
| `Invoke-Generate` | Non-streaming LLM call, returns `@{ Message; Usage; StopReason; Raw }` |
| `Invoke-GenerateStream` | Streaming LLM call, emits chunk objects to the pipeline |

#### Agent
| Function | Description |
|----------|-------------|
| `New-Agent` | Create an agent with generator, tools, hooks, stop conditions |
| `Invoke-Agent` | Blocking agent run, returns `@{ Status; Output; Steps; Usage; Trajectory; Error }` |
| `Invoke-AgentStream` | Streaming agent run, emits `AgentEvent` objects to the pipeline |

#### Messages
| Function | Description |
|----------|-------------|
| `New-Message` | Create a Message (user, system, assistant, tool) |

#### Tools
| Function | Description |
|----------|-------------|
| `New-Tool` | Define a custom tool |
| `New-Toolkit` | Collect tools into a toolkit |
| `Read-FileContent` | Built-in: read a file |
| `Write-FileContent` | Built-in: write a file |
| `Get-DirectoryListing` | Built-in: list directory |
| `Invoke-ShellCommand` | Built-in: run shell command |
| `Search-Files` | Built-in: glob file search |
| `Search-FileContent` | Built-in: grep |
| `New-NtResearchAgent` | Built-in: NtObjectManager/OleViewDotNet research sub-agent |

#### Tool Import
| Function | Description |
|----------|-------------|
| `Import-ToolFromCommand` | Convert a PowerShell command to a PshAgentTool |
| `Import-ToolsFromModule` | Import all functions from a module as tools |
| `Import-ToolsFromScript` | Dot-source a script and import new functions as tools |

#### Sub-Agents
| Function | Description |
|----------|-------------|
| `New-SubAgentTool` | Create a tool that delegates to a child agent (in-process or out-of-process) |

#### Hooks
| Function | Description |
|----------|-------------|
| `New-Hook` | Create a custom event hook |
| `New-BackoffOnErrorHook` | Exponential backoff on errors |
| `New-BackoffOnRatelimitHook` | Rate limit backoff |
| `New-RetryWithFeedbackHook` | Retry with feedback on stall |
| `New-DangerousCommandHook` | Block dangerous shell commands |

#### Reactions
| Function | Description |
|----------|-------------|
| `New-Reaction` | Create a reaction (Continue, Retry, RetryWithFeedback, Fail, Finish) |

#### Stop Conditions
| Function | Description |
|----------|-------------|
| `New-StopCondition` | Custom stop condition |
| `New-StepCountCondition` | Stop after N steps |
| `New-ToolUseCondition` | Stop when tool used N times |
| `New-TokenUsageCondition` | Stop on token limit |
| `New-ElapsedTimeCondition` | Stop on time limit |
| `New-OutputPatternCondition` | Stop on output pattern match |
| `New-ConsecutiveErrorCondition` | Stop after N consecutive errors |

#### Sessions
| Function | Description |
|----------|-------------|
| `Save-AgentSession` | Save session to `~/.psh-agent/sessions/` |
| `Get-AgentSession` | Load or list sessions |
| `Remove-AgentSession` | Delete sessions |

#### CLI
| Function | Description |
|----------|-------------|
| `Start-PshAgent` | Launch interactive REPL |
| `Invoke-SlashCommand` | Slash command dispatcher |

### Exported Classes (14)

| Class | Description |
|-------|-------------|
| `Message` | Conversation message with role, content, tool calls |
| `PshGenerator` | LLM provider/model wrapper |
| `PshAgent` | Agent state holder |
| `PshAgentTool` | Tool definition with execute scriptblock |
| `PshAgentToolkit` | Tool collection |
| `StopCondition` | Composable stop condition |
| `PshAgentHook` | Event hook |
| `Reaction` | Hook reaction (Continue/Retry/Fail/Finish) |
| `Trajectory` | Execution history and message reconstruction |
| `PshAgentSession` | Session persistence |
| `Usage` | Token usage tracking |
| `ToolCall` | Tool invocation (id, name, arguments) |
| `ToolResult` | Tool execution result |
| `AgentEvent` | Base event class (13 subclasses) |

### Connection Strings

Format: `provider/model`

```
anthropic/claude-sonnet-4-20250514
anthropic/claude-haiku-4-5-20251001
openai/gpt-4o
openai/gpt-4o-mini
```

API keys are read from environment variables:
- `ANTHROPIC_API_KEY` for Anthropic
- `OPENAI_API_KEY` for OpenAI
- `{PROVIDER}_API_KEY` for other providers (treated as OpenAI-compatible)

### Config Directory

`~/.psh-agent/`
- `config.json` — default connection string and settings
- `sessions/` — saved conversation sessions (JSON)

---

## C2 Agent Mesh

The `c2-mesh/` module builds a command-and-control agent mesh on top of PshAgent. Instead of shipping a static implant with hardcoded tradecraft, every compromised host runs a full PshAgent with Claude as its brain. You give it natural language tasks and the AI reasons about what commands to run, what files to read, how to persist, how to move laterally — using the same built-in tools (`run_command`, `read_file`, etc.) that ship with PshAgent.

> Full implementation spec: [`docs/c2-mesh-implementation.md`](docs/c2-mesh-implementation.md)

### How It Works

Three components, one observer:

```
┌──────────────┐         ┌──────────────────┐         ┌──────────────┐
│   Operator   │         │    Controller    │  HTTPS   │    Beacon    │
│  (your CLI)  │────────►│  (HttpListener)  │◄────────►│ (on target)  │
│              │  tools   │                  │  poll    │              │
│  PshAgent +  │         │  beacon registry │         │  PshAgent +  │
│  5 operator  │         │  task queues     │         │  Claude AI   │
│  tools       │         │  result store    │         │  built-in    │
│              │         │                  │         │  tools       │
└──────────────┘         └────────┬─────────┘         └──────┬───────┘
                                  │ internal API              │
                                  ▼                           ▼ (mesh)
                         ┌──────────────────┐         Beacon ◄──► Beacon
                         │    Dashboard     │         relay via HTTP
                         │ (Phoenix/Elixir) │
                         │ read-only observer│
                         └──────────────────┘
```

**Operator** — You run `Start-PshAgent` with 5 operator tools: `list_beacons`, `task_beacon`, `get_results`, `deploy_beacon`, `kill_beacon`. You talk naturally ("scan 10.0.1.0/24 from beacon-alpha") and the AI on your laptop routes to the right tool calls.

**Controller** — A PowerShell `HttpListener` on port 8443 with three endpoints: `/register`, `/checkin`, `/task`. Maintains a `ConcurrentDictionary` beacon registry, per-beacon task queues, and a result store. All payloads encrypted with AES-256-GCM.

**Beacon** — A polling loop on the target host. Every ~30s (with jitter), it calls `/checkin`. If the controller returns a task, the beacon spins up a full PshAgent via `Invoke-Agent` — Claude receives the task as a prompt and decides which tools to call. Results flow back on the next check-in.

**Dashboard** — An Elixir/Phoenix LiveView app that polls the controller's internal API (localhost:8444) and renders a world map (GeoIP), activity heatmap, beacon table, and live result feed. Pure observer — never writes to the controller.

### The "AI is the tradecraft" idea

Traditional C2 agents ship hardcoded modules for credential harvesting, persistence, lateral movement. This is pointless when the agent on target is Claude. It already knows how to:

- Enumerate services, processes, network config
- Read registry keys, harvest stored credentials
- Set up scheduled tasks, registry run keys, WMI subscriptions
- Move laterally via WinRM, SMB, PSRemoting
- Adapt when something fails or an AV blocks a technique

So the beacon ships with only PshAgent's built-in tools plus one custom `port_scan` (because structured TCP scanning is faster than shelling out per-port). Everything else is natural language → Claude → tool calls.

### Example Walkthrough

```
# 1. Start the controller on your VPS
pwsh ./c2-mesh/Launchers/start-controller.ps1

# 2. Start the operator CLI
pwsh ./c2-mesh/Launchers/start-controller.ps1 -OperatorMode

# 3. Beacon registers from target host (10.0.1.20)
#    (deployed via initial access — runs start-beacon.ps1)
```

```
Operator > list my beacons

  Tool: list_beacons
  beacon-7f3a | 10.0.1.20 | WIN-TARGET01 | alive | last seen 4s ago

Operator > find all saved credentials on beacon-7f3a and check
           if any work for lateral movement on the subnet

  Tool: task_beacon(beaconId='7f3a', task='find all saved credentials...')
  Task queued.

  --- on the target, beacon-7f3a picks up the task ---

  Claude reasons:
    run_command("cmdkey /list")              → 3 stored creds
    run_command("reg query ...DefaultPassword") → autologon password
    port_scan(target="10.0.1.0/24", ports="445,3389,5985")
                                              → 3 hosts with open ports
    run_command("net use \\10.0.1.5\C$ ...")  → cred works on .5

  --- results flow back on next check-in ---

Operator > get results from beacon-7f3a

  "Found 3 stored credentials via cmdkey. AutoLogon password for
   DOMAIN\admin recovered from registry. Verified lateral movement
   to 10.0.1.5 via SMB. Additional targets: 10.0.1.10 (RDP),
   10.0.1.30 (WinRM)."

Operator > deploy a beacon to 10.0.1.5 through beacon-7f3a

  Tool: deploy_beacon(target='10.0.1.5', via='7f3a', ...)
  → Claude on 7f3a copies the beacon script, executes it on .5
  → New beacon registers with controller
```

### Observability with `dn.task()`

The C2 mesh's `task_beacon` tool (queues a natural language string for a beacon) is a different layer from dreadnode's `dn.task()` decorator (wraps functions with tracing/scoring). But `dn.task()` can **instrument** the entire chain — the SDK's trace context propagation (`dn.get_run_context()` / `dn.continue_run()`) links operator → controller → beacon execution into a single traced run across machines:

```
dn.run("red-team-op")
  └─ @dn.task: operator sends task              ← traced
       └─ controller queues it                  ← context serialized
            └─ dn.continue_run(context)         ← beacon picks up trace
                 └─ @dn.task: Claude executes   ← same run, same span tree
                      └─ tool calls, metrics    ← all linked
```

This means every tool call on every beacon feeds into one run with scoring, metrics, and artifact logging — and the dashboard can pull from dreadnode's tracing backend alongside the controller's internal API.

### PshAgent ↔ C2 Mapping

| C2 concept | PshAgent API | What it does |
|---|---|---|
| Operator CLI | `Start-PshAgent` + 5 custom tools | Interactive REPL for commanding beacons |
| Controller | `HttpListener` + `ConcurrentDictionary` | HTTP server, registry, task queues |
| Beacon brain | `New-Agent` + `Invoke-Agent` | Claude executes tasks with tools |
| Beacon tools | PshAgent built-ins + `port_scan` | `run_command`, `read_file`, `write_file`, `list_directory`, `search_files`, `grep` |
| Beacon hooks | `New-Hook` (×4) | Telemetry, check-in, kill switch, stealth |
| Beacon stop | `StopCondition` | Kill switch or max-steps |
| Mesh relay | `New-Tool` wrapping HTTP | Beacon-to-beacon forwarding |
| Comms crypto | `System.Security.Cryptography.AesGcm` | AES-256-GCM on all payloads |
| Dashboard | Phoenix LiveView + GenServer poller | Read-only observer UI |

### Module Layout

```
c2-mesh/
├── c2-mesh.psd1 / .psm1        # module manifest + loader
├── Config/c2-config.ps1         # constants, defaults
├── Crypto/Invoke-C2Crypto.ps1   # AES-256-GCM encrypt/decrypt
├── Controller/
│   ├── Start-C2Listener.ps1     # HttpListener in background runspace
│   ├── Get-BeaconRegistry.ps1   # ConcurrentDictionary management
│   ├── Send-BeaconTask.ps1      # queue task for a beacon
│   ├── Get-BeaconResults.ps1    # retrieve results
│   ├── New-OperatorTools.ps1    # 5 operator tools
│   └── Start-C2Controller.ps1   # compose & launch
├── Beacon/
│   ├── Register-Beacon.ps1      # POST /register on startup
│   ├── Invoke-CheckIn.ps1       # POST /checkin (poll loop)
│   ├── New-BeaconHooks.ps1      # telemetry, check-in, kill, stealth
│   ├── New-PortScanTool.ps1     # only custom tool
│   └── Start-C2Beacon.ps1       # beacon polling loop
├── Mesh/
│   ├── New-MeshRelayTool.ps1    # relay through peers
│   ├── Invoke-MeshDiscovery.ps1 # discover peer beacons
│   └── Invoke-SwarmTask.ps1     # distribute across mesh
├── Dashboard/                   # Elixir/Phoenix LiveView app
│   └── c2_dash/                 # mix project
└── Launchers/
    ├── start-controller.ps1
    └── start-beacon.ps1
```
