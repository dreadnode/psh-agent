function Invoke-ShellCommand {
    <#
    .SYNOPSIS
    Built-in tool: run_command - Run a shell command
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param()

    return New-Tool -Name 'run_command' `
        -Description 'Run a shell command and return its output' `
        -Parameters @{
            type       = 'object'
            properties = @{
                command = @{ type = 'string'; description = 'Command to execute' }
                cwd     = @{ type = 'string'; description = 'Working directory (optional)' }
            }
            required   = @('command')
        } `
        -Execute {
            param($a)
            $cmd = $a.command
            $workDir = if ($a.cwd) { Resolve-Path $a.cwd -ErrorAction Stop | Select-Object -ExpandProperty Path } else { $PWD.Path }

            $psi = [System.Diagnostics.ProcessStartInfo]::new()
            if ($IsWindows -or [System.Environment]::OSVersion.Platform -eq 'Win32NT') {
                $psi.FileName = 'cmd.exe'
                $psi.Arguments = "/c $cmd"
            }
            else {
                $psi.FileName = '/bin/sh'
                $psi.Arguments = "-c `"$($cmd.Replace('"','\"'))`""
            }
            $psi.WorkingDirectory = $workDir
            $psi.RedirectStandardOutput = $true
            $psi.RedirectStandardError = $true
            $psi.UseShellExecute = $false
            $psi.CreateNoWindow = $true

            $proc = [System.Diagnostics.Process]::Start($psi)
            $stdout = $proc.StandardOutput.ReadToEnd()
            $stderr = $proc.StandardError.ReadToEnd()

            if (-not $proc.WaitForExit(30000)) {
                $proc.Kill()
                throw 'Command timed out after 30 seconds'
            }

            $output = $stdout
            if ($proc.ExitCode -ne 0 -and $stderr) {
                $output += "`nSTDERR: $stderr"
            }
            elseif ($stderr) {
                $output += $stderr
            }

            if (-not $output) { $output = "(no output, exit code: $($proc.ExitCode))" }
            $output
        }
}
