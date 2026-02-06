function New-NtResearchAgent {
    <#
    .SYNOPSIS
    Built-in tool: Sub-agent with NtObjectManager and OleViewDotNet for Windows security research
    .DESCRIPTION
    Creates a sub-agent tool loaded with James Forshaw's NtObjectManager and
    optionally OleViewDotNet modules. Capable of enumerating NT objects, auditing
    access controls, inspecting RPC interfaces, analyzing tokens/privileges,
    investigating COM/DCOM attack surface, and probing Windows security boundaries.

    The sub-agent gets a curated set of the most useful functions as tools,
    plus run_powershell for ad-hoc access to the full module surface.
    .PARAMETER ConnectionString
    Provider/model for the sub-agent (default: anthropic/claude-sonnet-4-20250514)
    .PARAMETER NtObjectManagerPath
    Path to NtObjectManager module (default: auto-detect via Get-Module)
    .PARAMETER OleViewDotNetPath
    Path to OleViewDotNet PowerShell module (optional, enables COM research)
    .PARAMETER MaxSteps
    Maximum agent steps (default: 15)
    .PARAMETER OutOfProcess
    Run in a separate pwsh process
    .EXAMPLE
    $researcher = New-NtResearchAgent
    $agent = New-Agent -Generator $gen -Tools @($researcher) -MaxSteps 5
    $result = Invoke-Agent -Agent $agent -Prompt 'Find services with weak permissions'
    .EXAMPLE
    $researcher = New-NtResearchAgent -OleViewDotNetPath '~/projects/oleviewdotnet/OleViewDotNetPS'
    $result = Invoke-Agent -Agent $agent -Prompt 'Enumerate COM objects accessible from a low-privilege AppContainer'
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param(
        [Parameter()]
        [string]$ConnectionString = 'anthropic/claude-sonnet-4-20250514',

        [Parameter()]
        [string]$NtObjectManagerPath,

        [Parameter()]
        [string]$OleViewDotNetPath,

        [Parameter()]
        [int]$MaxSteps = 15,

        [Parameter()]
        [switch]$OutOfProcess
    )

    # Build system prompt — include COM section only if OleViewDotNet is available
    $comSection = ''
    if ($OleViewDotNetPath) {
        $comSection = @'

## COM/DCOM Research (OleViewDotNet)

**COM database** — Load and query the COM registration database:
- Get-ComDatabase to load, Set-ComDatabase to set current, Get-ComClass/Get-ComInterface/Get-ComAppId to query
- Get-ComProcess to see COM servers running in processes
- Get-ComRegisteredClass to find active class registrations

**COM security** — Audit COM object permissions:
- Select-ComAccess / Test-ComAccess / Get-ComAccess to check launch/access permissions
- Format-ComSecurityDescriptor to display COM SDs in readable form
- Compare COM SDs against token capabilities to find accessible objects

**COM proxies and RPC** — Decompile COM interfaces:
- Get-ComProxy / Format-ComProxy to decompile interface proxies
- Get-ComRpcClient to generate RPC client code for COM interfaces
- Get-ComObjectIpid to inspect cross-process COM connections

**COM activation** — Monitor and trigger COM activation:
- Start-ComActivationLog / Stop-ComActivationLog to trace activations
- New-ComObject / New-ComObjectFactory to instantiate objects
- Get-ComMoniker to parse moniker strings

**COM type libraries** — Inspect type information:
- Get-ComTypeLib / Format-ComTypeLib to enumerate and display type libraries
- ConvertTo-ComAssembly to generate .NET interop assemblies
- Import-ComTypeLib to load type info programmatically

**Key COM research patterns:**
- Load database: `$db = Get-ComDatabase; Set-ComDatabase $db`
- Find accessible objects: `Get-ComClass | Select-ComAccess -Token $token`
- Enumerate DCOM: `Get-ComClass | Where-Object AppId -ne $null`
- Cross-session activation: Check AppId launch permissions for non-interactive sessions
- COM type confusion: Inspect proxy definitions for mismatched interface marshaling
'@
    }

    $systemPrompt = @"
You are a Windows security researcher with access to James Forshaw's security research tools.

## Research Methodology
1. Enumerate objects/endpoints in the target subsystem
2. Check security descriptors and access controls
3. Identify mismatches — objects writable by low-privilege users, RPC methods callable without auth, tokens with unnecessary privileges, COM objects activatable across security boundaries
4. Report findings with specifics: object path, current permissions, who can access it, and why it matters

## NT Object Research (NtObjectManager)

**Access auditing** — Use Get-Accessible* to scan for permission issues:
- Get-AccessibleProcess, Get-AccessibleFile, Get-AccessibleKey, Get-AccessibleNamedPipe, Get-AccessibleService

**RPC enumeration** — Find and decompile RPC interfaces:
- Get-RpcServer to decompile, Get-RpcEndpoint to list endpoints, Format-RpcServer for readable output

**Token analysis** — Inspect process tokens and privileges:
- Get-NtToken, Get-NtTokenPrivilege, Get-NtTokenGroup, Test-NtTokenImpersonation

**Object namespace** — Explore the NT object tree:
- Get-NtDirectoryEntry, Get-NtObject, Get-NtSecurityDescriptor, Get-NtSymbolicLinkTarget

**Security descriptors** — Read and compare ACLs:
- Get-NtSecurityDescriptor, Format-NtSecurityDescriptor, Compare-NtSecurityDescriptor
$comSection

## Tips
- Use run_powershell for any cmdlet not available as a direct tool
- Pipe output through Format-List or Format-Table for readability
- Use -Recurse where available to scan subdirectories/subkeys
- Filter with Where-Object to focus on interesting results
- When checking access, test from the perspective of low-privilege identities
"@

    # Curated NtObjectManager include list
    $ntIncludeList = @(
        # Access checking
        'Get-AccessibleProcess'
        'Get-AccessibleFile'
        'Get-AccessibleKey'
        'Get-AccessibleNamedPipe'
        'Get-AccessibleService'
        'Get-AccessibleObject'
        'Get-AccessibleDevice'
        'Get-AccessibleHandle'
        'Get-AccessibleScheduledTask'

        # RPC
        'Get-RpcServer'
        'Get-RpcEndpoint'
        'Get-RpcAlpcServer'
        'Format-RpcServer'

        # Tokens
        'Get-NtToken'
        'Get-NtTokenPrivilege'
        'Get-NtTokenGroup'
        'Test-NtTokenImpersonation'
        'Get-NtTokenIntegrityLevel'

        # Processes
        'Get-NtProcess'
        'Get-NtProcessMitigations'
        'Get-NtHandle'
        'Get-NtProcessUser'

        # Objects & namespace
        'Get-NtDirectoryEntry'
        'Get-NtObject'
        'Get-NtType'
        'Get-NtSymbolicLinkTarget'

        # Security descriptors
        'Get-NtSecurityDescriptor'
        'Format-NtSecurityDescriptor'
        'Compare-NtSecurityDescriptor'
        'Show-NtSecurityDescriptor'

        # Files
        'Get-NtFile'
        'Get-NtFilePath'
        'Get-NtFileSecurityDescriptor'

        # Registry
        'Get-NtKey'
        'Get-NtKeyValue'

        # Services
        'Get-Win32Service'
        'Get-Win32ServiceConfig'
        'Get-Win32ServiceSecurityDescriptor'

        # SIDs and names
        'Get-NtSid'
        'Get-NtSidName'

        # System info
        'Get-NtSystemInformation'
        'Get-NtKernelModule'
    )

    # Curated OleViewDotNet include list
    $oleIncludeList = @(
        # Database
        'Get-ComDatabase'
        'Set-ComDatabase'
        'Compare-ComDatabase'
        'Get-CurrentComDatabase'

        # Classes and interfaces
        'Get-ComClass'
        'Get-ComInterface'
        'Get-ComAppId'
        'Get-ComCategory'
        'Get-ComProgId'
        'Get-ComClassInterface'
        'Get-ComRuntimeClass'
        'Get-ComRuntimeServer'
        'Get-ComRuntimeInterface'

        # Security
        'Select-ComAccess'
        'Test-ComAccess'
        'Get-ComAccess'
        'Format-ComSecurityDescriptor'
        'Get-ComAccessToken'

        # Processes and runtime
        'Get-ComProcess'
        'Get-ComRegisteredClass'
        'Get-ComObjectIpid'
        'Get-ComObjectInterface'
        'Format-ComProcessClient'

        # Proxies and RPC
        'Get-ComProxy'
        'Format-ComProxy'
        'Get-ComRpcClient'
        'Get-ComProxyName'

        # Activation and objects
        'New-ComObject'
        'New-ComObjectFactory'
        'Start-ComActivationLog'
        'Stop-ComActivationLog'
        'Get-ComMoniker'

        # Type libraries
        'Get-ComTypeLib'
        'Format-ComTypeLib'
        'ConvertTo-ComAssembly'

        # ObjRef
        'Get-ComObjRef'
        'Get-ComRunningObjectTable'
    )

    # run_powershell tool for ad-hoc access
    $runPwsh = New-Tool -Name 'run_powershell' `
        -Description 'Run arbitrary PowerShell code. Use for any cmdlet not available as a direct tool, including all NtObjectManager and OleViewDotNet functions.' `
        -Parameters @{
            type       = 'object'
            properties = @{
                code = @{ type = 'string'; description = 'PowerShell code to execute' }
            }
            required   = @('code')
        } `
        -Execute {
            param($a)
            $result = Invoke-Expression $a.code 2>&1
            if ($null -eq $result) { '(no output)' }
            elseif ($result -is [string]) { $result }
            else { ($result | Out-String).TrimEnd() }
        }

    if ($OutOfProcess) {
        $ntModPath = $NtObjectManagerPath
        if (-not $ntModPath) {
            $ntMod = Get-Module NtObjectManager -ListAvailable -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($ntMod) { $ntModPath = $ntMod.Path }
            else { throw "NtObjectManager not found. Provide -NtObjectManagerPath." }
        }

        $toolModules = @($ntModPath)
        if ($OleViewDotNetPath) {
            $toolModules += $OleViewDotNetPath
        }

        return New-SubAgentTool -Name 'nt_researcher' `
            -Description 'Windows security researcher with NtObjectManager and OleViewDotNet. Delegates research tasks — enumerate NT objects, audit access controls, inspect RPC/COM interfaces, analyze tokens, investigate security boundaries.' `
            -ConnectionString $ConnectionString `
            -SystemPrompt $systemPrompt `
            -BuiltinTools @('run_command', 'read_file', 'list_directory') `
            -ToolModules $toolModules `
            -MaxSteps $MaxSteps `
            -OutOfProcess
    }
    else {
        # In-process: import curated tools
        if (-not $NtObjectManagerPath) {
            $ntMod = Get-Module NtObjectManager -ErrorAction SilentlyContinue
            if (-not $ntMod) {
                $ntMod = Get-Module NtObjectManager -ListAvailable -ErrorAction SilentlyContinue | Select-Object -First 1
            }
            if ($ntMod) { $NtObjectManagerPath = $ntMod.Path }
            else { throw "NtObjectManager not found. Provide -NtObjectManagerPath or import the module first." }
        }

        $allTools = [System.Collections.Generic.List[PshAgentTool]]::new()

        # Import NtObjectManager tools
        $ntTools = Import-ToolsFromModule -Module $NtObjectManagerPath -Include $ntIncludeList
        foreach ($t in $ntTools) { $allTools.Add($t) }

        # Import OleViewDotNet tools if path provided
        if ($OleViewDotNetPath) {
            $oleTools = Import-ToolsFromModule -Module $OleViewDotNetPath -Include $oleIncludeList
            foreach ($t in $oleTools) { $allTools.Add($t) }
        }

        $allTools.Add($runPwsh)
        $allTools.Add((Invoke-ShellCommand))

        return New-SubAgentTool -Name 'nt_researcher' `
            -Description 'Windows security researcher with NtObjectManager and OleViewDotNet. Delegates research tasks — enumerate NT objects, audit access controls, inspect RPC/COM interfaces, analyze tokens, investigate security boundaries.' `
            -ConnectionString $ConnectionString `
            -SystemPrompt $systemPrompt `
            -Tools @($allTools) `
            -MaxSteps $MaxSteps
    }
}
