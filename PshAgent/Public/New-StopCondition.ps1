function New-StopCondition {
    <#
    .SYNOPSIS
    Create a custom stop condition
    .PARAMETER Name
    Name for this stop condition
    .PARAMETER Fn
    Scriptblock that receives an array of step events and returns $true to stop
    .PARAMETER CatchErrors
    If true, catch errors and return DefaultValue
    .PARAMETER DefaultValue
    Value to return if CatchErrors is true and an error occurs
    .EXAMPLE
    $cond = New-StopCondition -Name 'my_condition' -Fn {
        param($steps)
        $steps.Count -ge 5
    }
    #>
    [CmdletBinding()]
    [OutputType([StopCondition])]
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [scriptblock]$Fn,

        [Parameter()]
        [switch]$CatchErrors,

        [Parameter()]
        [bool]$DefaultValue = $false
    )

    return [StopCondition]::new($Name, $Fn, [bool]$CatchErrors, $DefaultValue)
}
