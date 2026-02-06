function ConvertTo-AnthropicMessages {
    <#
    .SYNOPSIS
    Convert Message[] to Anthropic API format
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [Message[]]$Messages,

        [Parameter()]
        [hashtable]$Tools
    )

    $systemPrompt = $null
    $apiMessages = [System.Collections.Generic.List[hashtable]]::new()

    foreach ($msg in $Messages) {
        switch ($msg.Role) {
            'system' {
                $systemPrompt = $msg.GetText()
            }
            'user' {
                $apiMessages.Add(@{
                    role    = 'user'
                    content = $msg.GetText()
                })
            }
            'assistant' {
                if ($msg.HasToolCalls()) {
                    $contentBlocks = [System.Collections.Generic.List[hashtable]]::new()
                    $text = $msg.GetText()
                    if ($text) {
                        $contentBlocks.Add(@{ type = 'text'; text = $text })
                    }
                    foreach ($tc in $msg.ToolCalls) {
                        $contentBlocks.Add(@{
                            type  = 'tool_use'
                            id    = $tc.Id
                            name  = $tc.Name
                            input = $tc.Arguments
                        })
                    }
                    $apiMessages.Add(@{
                        role    = 'assistant'
                        content = @($contentBlocks)
                    })
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
                    role    = 'user'
                    content = @(@{
                        type        = 'tool_result'
                        tool_use_id = $msg.ToolCallId
                        content     = $msg.GetText()
                    })
                })
            }
        }
    }

    # Build tool definitions
    $toolDefs = $null
    if ($Tools -and $Tools.Count -gt 0) {
        $toolDefs = @($Tools.GetEnumerator() | ForEach-Object {
            @{
                name         = $_.Key
                description  = $_.Value.Description
                input_schema = $_.Value.Parameters
            }
        })
    }

    return @{
        System   = $systemPrompt
        Messages = @($apiMessages)
        Tools    = $toolDefs
    }
}
