function Search-FileContent {
    <#
    .SYNOPSIS
    Built-in tool: grep - Search for text in files
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param()

    return New-Tool -Name 'grep' `
        -Description 'Search for text or regex pattern in files' `
        -Parameters @{
            type       = 'object'
            properties = @{
                pattern = @{ type = 'string'; description = 'Text or regex pattern to search for' }
                path    = @{ type = 'string'; description = 'File or directory to search in' }
                include = @{ type = 'string'; description = 'File pattern to include (e.g., *.ps1)' }
            }
            required   = @('pattern')
        } `
        -Execute {
            param($a)
            $searchPath = if ($a.path) { Resolve-Path $a.path -ErrorAction Stop } else { $PWD.Path }
            $pattern = $a.pattern

            $params = @{
                Pattern     = $pattern
                Path        = $searchPath
                Recurse     = $true
                ErrorAction = 'SilentlyContinue'
            }
            if ($a.include) {
                $params.Include = $a.include
            }

            $results = Select-String @params | Select-Object -First 100

            if ($results) {
                $lines = @($results | ForEach-Object {
                    "$($_.RelativePath ?? $_.Path):$($_.LineNumber): $($_.Line.Trim())"
                })
                $lines -join "`n"
            }
            else {
                'No matches found'
            }
        }
}
