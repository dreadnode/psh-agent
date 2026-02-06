function Read-FileContent {
    <#
    .SYNOPSIS
    Built-in tool: read_file - Read the contents of a file
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param()

    return New-Tool -Name 'read_file' `
        -Description 'Read the contents of a file' `
        -Parameters @{
            type       = 'object'
            properties = @{
                path = @{ type = 'string'; description = 'Path to the file to read' }
            }
            required   = @('path')
        } `
        -Execute {
            param($a)
            $resolvedPath = Resolve-Path -Path $a.path -ErrorAction Stop
            Get-Content -Path $resolvedPath -Raw -ErrorAction Stop
        }
}
