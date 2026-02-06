function Invoke-SubAgentOutOfProcess {
    <#
    .SYNOPSIS
    Spawn a child pwsh process and communicate via named pipe
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ConnectionString,

        [Parameter(Mandatory)]
        [string]$SystemPrompt,

        [Parameter(Mandatory)]
        [string]$Prompt,

        [Parameter()]
        [string[]]$BuiltinTools = @(),

        [Parameter()]
        [string[]]$ToolModules = @(),

        [Parameter()]
        [int]$MaxSteps = 10,

        [Parameter(Mandatory)]
        [string]$ModulePath
    )

    $pipeName = "psh-agent-sub-$([guid]::NewGuid().ToString('N'))"
    $pipeServer = $null
    $reader = $null
    $writer = $null
    $process = $null

    try {
        # Create named pipe server
        $pipeServer = [System.IO.Pipes.NamedPipeServerStream]::new(
            $pipeName,
            [System.IO.Pipes.PipeDirection]::InOut,
            1,  # maxNumberOfServerInstances
            [System.IO.Pipes.PipeTransmissionMode]::Byte,
            [System.IO.Pipes.PipeOptions]::Asynchronous
        )

        # Build the child process command
        $escapedModulePath = $ModulePath -replace "'", "''"
        $escapedPipeName = $pipeName -replace "'", "''"
        $childCommand = "Import-Module '$escapedModulePath'; Start-SubAgentWorker -PipeName '$escapedPipeName'"

        # Spawn child process
        $psi = [System.Diagnostics.ProcessStartInfo]::new()
        $psi.FileName = 'pwsh'
        $psi.Arguments = "-NoProfile -NonInteractive -Command `"$childCommand`""
        $psi.UseShellExecute = $false
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true

        $process = [System.Diagnostics.Process]::Start($psi)

        # Wait for connection with timeout (60 seconds)
        $connectTask = $pipeServer.WaitForConnectionAsync()
        if (-not $connectTask.Wait(60000)) {
            throw "Child process did not connect within 60 seconds"
        }

        $reader = [System.IO.StreamReader]::new($pipeServer)
        $writer = [System.IO.StreamWriter]::new($pipeServer)
        $writer.AutoFlush = $true

        # Send request
        $request = @{
            connectionString = $ConnectionString
            systemPrompt     = $SystemPrompt
            builtinTools     = $BuiltinTools
            toolModules      = $ToolModules
            maxSteps         = $MaxSteps
            prompt           = $Prompt
        }

        $requestJson = $request | ConvertTo-Json -Depth 10 -Compress
        $writer.WriteLine($requestJson)

        # Read response (with timeout via async read)
        $readTask = $reader.ReadLineAsync()
        # Allow up to 5 minutes for the child agent to complete
        if (-not $readTask.Wait(300000)) {
            throw "Child process did not respond within 5 minutes"
        }

        $responseJson = $readTask.Result
        if (-not $responseJson) {
            # Check for stderr output
            $stderr = $process.StandardError.ReadToEnd()
            throw "Child process returned empty response. Stderr: $stderr"
        }

        $response = $responseJson | ConvertFrom-Json -AsHashtable
        return $response
    }
    catch {
        return @{
            status = 'errored'
            output = $null
            steps  = 0
            error  = "$_"
        }
    }
    finally {
        if ($reader) { $reader.Dispose() }
        if ($writer) { $writer.Dispose() }
        if ($pipeServer) { $pipeServer.Dispose() }
        if ($process -and -not $process.HasExited) {
            try { $process.Kill() } catch { }
        }
        if ($process) { $process.Dispose() }
    }
}
