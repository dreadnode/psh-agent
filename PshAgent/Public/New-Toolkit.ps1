function New-Toolkit {
    <#
    .SYNOPSIS
    Collect tools into a toolkit
    .PARAMETER Tools
    Array of PshAgentTool objects
    .EXAMPLE
    $toolkit = New-Toolkit -Tools @($readFile, $writeFile, $runCommand)
    #>
    [CmdletBinding()]
    [OutputType([PshAgentToolkit])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [PshAgentTool[]]$Tools
    )

    return [PshAgentToolkit]::new($Tools)
}
