function New-Message {
    <#
    .SYNOPSIS
    Message factory function
    .PARAMETER Role
    Message role: system, user, assistant, tool
    .PARAMETER Content
    Message content (string or content parts)
    .PARAMETER ToolCalls
    Tool calls (for assistant messages)
    .PARAMETER ToolCallId
    Tool call ID (for tool result messages)
    .EXAMPLE
    $msg = New-Message -Role user -Content 'Hello'
    $msg = New-Message -Role system -Content 'You are a helpful assistant.'
    #>
    [CmdletBinding()]
    [OutputType([Message])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [MessageRole]$Role,

        [Parameter(Mandatory, Position = 1)]
        $Content,

        [Parameter()]
        [ToolCall[]]$ToolCalls,

        [Parameter()]
        [string]$ToolCallId
    )

    switch ($Role) {
        'system' { return [Message]::System($Content) }
        'user' { return [Message]::User($Content) }
        'assistant' {
            if ($ToolCalls) {
                return [Message]::Assistant($Content, $ToolCalls)
            }
            return [Message]::Assistant($Content)
        }
        'tool' { return [Message]::Tool($ToolCallId, $Content) }
    }
}
