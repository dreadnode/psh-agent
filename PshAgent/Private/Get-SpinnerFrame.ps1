function Get-SpinnerFrame {
    <#
    .SYNOPSIS
    Get spinner animation frames
    #>
    [CmdletBinding()]
    param(
        [Parameter()]
        [int]$Index = 0
    )

    $frames = @('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')
    return $frames[$Index % $frames.Count]
}

function Start-Spinner {
    <#
    .SYNOPSIS
    Start a spinner with a message. Returns a state hashtable.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$Message = 'Working...'
    )

    $state = @{
        Message = $Message
        Index   = 0
        Active  = $true
        Timer   = $null
    }

    # Write initial spinner
    $frame = Get-SpinnerFrame -Index 0
    [Console]::Write("`r$frame $Message")

    return $state
}

function Update-Spinner {
    <#
    .SYNOPSIS
    Update spinner animation
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [hashtable]$State
    )

    if (-not $State.Active) { return }

    $State.Index++
    $frame = Get-SpinnerFrame -Index $State.Index
    [Console]::Write("`r$frame $($State.Message)")
}

function Stop-Spinner {
    <#
    .SYNOPSIS
    Stop and clear the spinner
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [hashtable]$State
    )

    $State.Active = $false
    $clearStr = ' ' * ($State.Message.Length + 4)
    [Console]::Write("`r$clearStr`r")
}
