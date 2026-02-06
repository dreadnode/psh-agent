function Get-DirectoryListing {
    <#
    .SYNOPSIS
    Built-in tool: list_directory - List files and directories
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param()

    return New-Tool -Name 'list_directory' `
        -Description 'List files and directories in a path' `
        -Parameters @{
            type       = 'object'
            properties = @{
                path = @{ type = 'string'; description = 'Directory path to list' }
            }
            required   = @('path')
        } `
        -Execute {
            param($a)
            $dirPath = if ($a.path) { $a.path } else { '.' }
            $resolvedPath = Resolve-Path -Path $dirPath -ErrorAction Stop
            $entries = Get-ChildItem -Path $resolvedPath -ErrorAction Stop
            if ($entries.Count -eq 0) {
                return '(empty directory)'
            }
            $lines = @($entries | ForEach-Object {
                $icon = if ($_.PSIsContainer) { 'd' } else { 'f' }
                "[$icon] $($_.Name)"
            })
            $lines -join "`n"
        }
}
