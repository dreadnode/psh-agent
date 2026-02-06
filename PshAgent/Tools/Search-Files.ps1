function Search-Files {
    <#
    .SYNOPSIS
    Built-in tool: search_files - Search for files matching a glob pattern
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param()

    return New-Tool -Name 'search_files' `
        -Description 'Search for files matching a pattern (glob)' `
        -Parameters @{
            type       = 'object'
            properties = @{
                pattern = @{ type = 'string'; description = 'Glob pattern to match (e.g., *.ps1, **/*.txt)' }
                path    = @{ type = 'string'; description = 'Directory to search in' }
            }
            required   = @('pattern')
        } `
        -Execute {
            param($a)
            $searchPath = if ($a.path) { Resolve-Path $a.path -ErrorAction Stop } else { $PWD.Path }
            $pattern = $a.pattern

            # Use Get-ChildItem with -Filter for simple patterns or -Recurse for **
            $results = if ($pattern.StartsWith('**/') -or $pattern.Contains('/**/')) {
                $cleanPattern = $pattern -replace '^\*\*/', '' -replace '/\*\*/', '/'
                Get-ChildItem -Path $searchPath -Filter $cleanPattern -Recurse -ErrorAction SilentlyContinue |
                    Select-Object -First 50 -ExpandProperty FullName
            }
            else {
                Get-ChildItem -Path $searchPath -Filter $pattern -ErrorAction SilentlyContinue |
                    Select-Object -First 50 -ExpandProperty FullName
            }

            if ($results) {
                $results -join "`n"
            }
            else {
                'No files found'
            }
        }
}
