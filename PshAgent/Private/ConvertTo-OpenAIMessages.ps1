function ConvertTo-OpenAIMessages {
    <#
    .SYNOPSIS
    Convert Message[] to OpenAI API format
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [Message[]]$Messages,

        [Parameter()]
        [hashtable]$Tools
    )

    $apiMessages = [System.Collections.Generic.List[hashtable]]::new()

    foreach ($msg in $Messages) {
        switch ($msg.Role) {
            'system' {
                $apiMessages.Add(@{
                    role    = 'system'
                    content = $msg.GetText()
                })
            }
            'user' {
                $apiMessages.Add(@{
                    role    = 'user'
                    content = $msg.GetText()
                })
            }
            'assistant' {
                if ($msg.HasToolCalls()) {
                    $toolCalls = @($msg.ToolCalls | ForEach-Object {
                        @{
                            id       = $_.Id
                            type     = 'function'
                            function = @{
                                name      = $_.Name
                                arguments = ($_.Arguments | ConvertTo-Json -Compress -Depth 10)
                            }
                        }
                    })
                    $m = @{
                        role       = 'assistant'
                        content    = $msg.GetText()
                        tool_calls = $toolCalls
                    }
                    if (-not $m.content) { $m.content = $null }
                    $apiMessages.Add($m)
                }
                else {
                    $apiMessages.Add(@{
                        role    = 'assistant'
                        content = $msg.GetText()
                    })
                }
            }
            'tool' {
                $apiMessages.Add(@{
                    role         = 'tool'
                    content      = $msg.GetText()
                    tool_call_id = $msg.ToolCallId
                })
            }
        }
    }

    # Build tool definitions
    $toolDefs = $null
    if ($Tools -and $Tools.Count -gt 0) {
        $toolDefs = @($Tools.GetEnumerator() | ForEach-Object {
            @{
                type     = 'function'
                function = @{
                    name        = $_.Key
                    description = $_.Value.Description
                    parameters  = $_.Value.Parameters
                }
            }
        })
    }

    return @{
        Messages = @($apiMessages)
        Tools    = $toolDefs
    }
}
