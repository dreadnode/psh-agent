function Invoke-AnthropicApi {
    <#
    .SYNOPSIS
    Call Anthropic Messages API (non-streaming and streaming)
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [PshGenerator]$Generator,

        [Parameter(Mandatory)]
        [Message[]]$Messages,

        [Parameter()]
        [hashtable]$Options = @{},

        [Parameter()]
        [switch]$Stream
    )

    $apiKey = $Generator.GetApiKey()
    $model = $Generator.ModelId
    $maxTokens = if ($Options.max_tokens) { $Options.max_tokens } else { 4096 }

    # Convert messages
    $toolsDef = $null
    if ($Options.tools) { $toolsDef = $Options.tools }
    $converted = ConvertTo-AnthropicMessages -Messages $Messages -Tools $toolsDef

    # Build request body
    $body = @{
        model      = $model
        max_tokens = $maxTokens
        messages   = $converted.Messages
    }

    if ($converted.System) {
        $body.system = $converted.System
    }
    if ($converted.Tools) {
        $body.tools = $converted.Tools
    }
    if ($Options.temperature) {
        $body.temperature = $Options.temperature
    }

    $headers = @{
        'Content-Type'      = 'application/json'
        'x-api-key'         = $apiKey
        'anthropic-version' = '2023-06-01'
    }

    if ($Stream) {
        $body.stream = $true
        return Invoke-AnthropicStreamInternal -Body $body -Headers $headers
    }

    $jsonBody = $body | ConvertTo-Json -Depth 20 -Compress
    $response = Invoke-RestMethod -Uri 'https://api.anthropic.com/v1/messages' `
        -Method Post -Headers $headers -Body $jsonBody -ContentType 'application/json'

    # Parse response
    $content = ''
    $toolCalls = [System.Collections.Generic.List[ToolCall]]::new()

    foreach ($block in $response.content) {
        if ($block.type -eq 'text') {
            $content = $block.text
        }
        elseif ($block.type -eq 'tool_use') {
            $args = @{}
            if ($block.input -is [System.Management.Automation.PSCustomObject]) {
                foreach ($p in $block.input.PSObject.Properties) {
                    $args[$p.Name] = $p.Value
                }
            }
            elseif ($block.input -is [hashtable]) {
                $args = $block.input
            }
            $toolCalls.Add([ToolCall]::new($block.id, $block.name, $args))
        }
    }

    $usage = [Usage]::new(
        [int]($response.usage.input_tokens),
        [int]($response.usage.output_tokens)
    )

    $stopReason = switch ($response.stop_reason) {
        'end_turn' { 'stop' }
        'tool_use' { 'tool_calls' }
        'max_tokens' { 'length' }
        default { $response.stop_reason }
    }

    $assistantMsg = if ($toolCalls.Count -gt 0) {
        [Message]::Assistant($content, $toolCalls.ToArray())
    }
    else {
        [Message]::Assistant($content)
    }

    return @{
        Message    = $assistantMsg
        Usage      = $usage
        StopReason = $stopReason
        Raw        = $response
    }
}

function Invoke-AnthropicStreamInternal {
    [CmdletBinding()]
    param(
        [hashtable]$Body,
        [hashtable]$Headers
    )

    $jsonBody = $Body | ConvertTo-Json -Depth 20 -Compress
    $chunks = Invoke-StreamingRequest -Uri 'https://api.anthropic.com/v1/messages' `
        -Headers $Headers -Body $jsonBody

    $fullText = ''
    $toolCalls = [System.Collections.Generic.List[ToolCall]]::new()
    $currentToolId = $null
    $currentToolName = $null
    $currentToolJson = ''
    $inputTokens = 0
    $outputTokens = 0

    foreach ($chunk in $chunks) {
        $eventType = $chunk.Event
        $data = $chunk.Data

        switch ($eventType) {
            'message_start' {
                if ($data.message -and $data.message.usage) {
                    $inputTokens = [int]$data.message.usage.input_tokens
                }
            }
            'content_block_start' {
                if ($data.content_block.type -eq 'tool_use') {
                    $currentToolId = $data.content_block.id
                    $currentToolName = $data.content_block.name
                    $currentToolJson = ''
                }
            }
            'content_block_delta' {
                if ($data.delta.type -eq 'text_delta') {
                    $fullText += $data.delta.text
                    [PSCustomObject]@{
                        Type      = 'text-delta'
                        TextDelta = $data.delta.text
                    }
                }
                elseif ($data.delta.type -eq 'input_json_delta') {
                    $currentToolJson += $data.delta.partial_json
                }
            }
            'content_block_stop' {
                if ($currentToolId) {
                    $args = @{}
                    if ($currentToolJson) {
                        try {
                            $parsed = $currentToolJson | ConvertFrom-Json
                            foreach ($p in $parsed.PSObject.Properties) {
                                $args[$p.Name] = $p.Value
                            }
                        }
                        catch {
                            $args = @{ _raw = $currentToolJson }
                        }
                    }
                    $tc = [ToolCall]::new($currentToolId, $currentToolName, $args)
                    $toolCalls.Add($tc)
                    [PSCustomObject]@{
                        Type     = 'tool-call'
                        ToolCall = $tc
                    }
                    $currentToolId = $null
                    $currentToolName = $null
                    $currentToolJson = ''
                }
            }
            'message_delta' {
                if ($data.usage) {
                    $outputTokens = [int]$data.usage.output_tokens
                }
                $stopReason = switch ($data.delta.stop_reason) {
                    'end_turn' { 'stop' }
                    'tool_use' { 'tool_calls' }
                    'max_tokens' { 'length' }
                    default { $data.delta.stop_reason }
                }
            }
            'message_stop' {
                $usage = [Usage]::new($inputTokens, $outputTokens)
                $assistantMsg = if ($toolCalls.Count -gt 0) {
                    [Message]::Assistant($fullText, $toolCalls.ToArray())
                }
                else {
                    [Message]::Assistant($fullText)
                }
                [PSCustomObject]@{
                    Type   = 'finish'
                    Result = @{
                        Message    = $assistantMsg
                        Usage      = $usage
                        StopReason = $stopReason
                    }
                }
            }
        }
    }
}
