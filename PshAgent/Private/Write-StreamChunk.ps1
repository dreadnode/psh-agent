function Write-StreamChunk {
    <#
    .SYNOPSIS
    Write streaming text to console in real-time (no newline)
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Text,

        [Parameter()]
        [ConsoleColor]$Color
    )

    if ($Color) {
        $prev = [Console]::ForegroundColor
        [Console]::ForegroundColor = $Color
        [Console]::Write($Text)
        [Console]::ForegroundColor = $prev
    }
    else {
        [Console]::Write($Text)
    }
}
