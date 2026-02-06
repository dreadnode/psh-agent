function Start-SubAgentWorker {
    <#
    .SYNOPSIS
    Child process entry point for out-of-process sub-agents
    .DESCRIPTION
    Connects to the parent process via named pipe, reads a JSON request,
    runs the agent, and writes the JSON result back.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$PipeName
    )

    $pipeClient = $null
    $reader = $null
    $writer = $null

    try {
        # Connect to parent's named pipe server
        $pipeClient = [System.IO.Pipes.NamedPipeClientStream]::new(
            '.', $PipeName, [System.IO.Pipes.PipeDirection]::InOut
        )
        $pipeClient.Connect(30000)  # 30 second timeout

        $reader = [System.IO.StreamReader]::new($pipeClient)
        $writer = [System.IO.StreamWriter]::new($pipeClient)
        $writer.AutoFlush = $true

        # Read the JSON request (single line)
        $requestJson = $reader.ReadLine()
        $request = $requestJson | ConvertFrom-Json -AsHashtable

        # Create generator
        $generator = New-Generator -ConnectionString $request.connectionString

        # Collect tools
        $tools = [System.Collections.Generic.List[PshAgentTool]]::new()

        # Load built-in tools
        $builtinMap = @{
            'read_file'      = 'Read-FileContent'
            'write_file'     = 'Write-FileContent'
            'list_directory'  = 'Get-DirectoryListing'
            'run_command'    = 'Invoke-ShellCommand'
            'search_files'   = 'Search-Files'
            'grep'           = 'Search-FileContent'
        }

        if ($request.builtinTools) {
            foreach ($toolName in $request.builtinTools) {
                if ($builtinMap.ContainsKey($toolName)) {
                    $tool = & $builtinMap[$toolName]
                    $tools.Add($tool)
                }
            }
        }

        # Import tools from modules
        if ($request.toolModules) {
            foreach ($moduleName in $request.toolModules) {
                try {
                    $moduleTools = Import-ToolsFromModule -Module $moduleName
                    foreach ($t in $moduleTools) { $tools.Add($t) }
                }
                catch {
                    Write-Warning "Failed to import tools from module '$moduleName': $_"
                }
            }
        }

        # Create and run agent
        $agent = New-Agent -Generator $generator -Tools @($tools) `
            -SystemPrompt $request.systemPrompt `
            -MaxSteps ([int]($request.maxSteps))

        $result = Invoke-Agent -Agent $agent -Prompt $request.prompt

        # Write result
        $response = @{
            status = "$($result.Status)"
            output = $result.Output
            steps  = $result.Steps
            error  = $null
        }

        if ($result.Status -eq [AgentStatus]::errored) {
            $response.error = if ($result.Error) { "$($result.Error)" } else { 'Unknown error' }
        }

        $responseJson = $response | ConvertTo-Json -Depth 10 -Compress
        $writer.WriteLine($responseJson)
    }
    catch {
        # Try to send error response if pipe is still connected
        if ($writer) {
            try {
                $errorResponse = @{
                    status = 'errored'
                    output = $null
                    steps  = 0
                    error  = "$_"
                } | ConvertTo-Json -Depth 5 -Compress
                $writer.WriteLine($errorResponse)
            } catch { }
        }
    }
    finally {
        if ($reader) { $reader.Dispose() }
        if ($writer) { $writer.Dispose() }
        if ($pipeClient) { $pipeClient.Dispose() }
    }
}
