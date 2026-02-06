function New-ToolUseCondition {
    <#
    .SYNOPSIS
    Stop when a specific tool has been used N times
    .PARAMETER ToolName
    Name of the tool to watch
    .PARAMETER Count
    Number of uses before stopping (default: 1)
    .EXAMPLE
    $cond = New-ToolUseCondition -ToolName 'submit'
    #>
    [CmdletBinding()]
    [OutputType([StopCondition])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$ToolName,

        [Parameter()]
        [int]$Count = 1
    )

    $tName = $ToolName
    $tCount = $Count
    return [StopCondition]::new(
        "stop_on_tool_use($ToolName, $Count)",
        {
            param($steps)
            $uses = @($steps | Where-Object {
                $_.Type -eq [AgentEventType]::ToolStep -and $_.ToolCall.Name -eq $tName
            }).Count
            $uses -ge $tCount
        }.GetNewClosure()
    )
}
