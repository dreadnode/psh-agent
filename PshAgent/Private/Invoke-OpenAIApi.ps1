function Invoke-OpenAIApi {
    <#
    .SYNOPSIS
    Call OpenAI Chat Completions API (non-streaming and streaming)
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

    # Determine base URL
    $baseUrl = if ($Options.base_url) { $Options.base_url } else { 'https://api.openai.com/v1' }

    # Convert messages
    $toolsDef = $null
    if ($Options.tools) { $toolsDef = $Options.tools }
    $converted = ConvertTo-OpenAIMessages -Messages $Messages -Tools $toolsDef

    # Build request body
    $body = @{
        model    = $model
        messages = $converted.Messages
    }
    if ($converted.Tools) {
        $body.tools = $converted.Tools
    }
    if ($Options.temperature) {
        $body.temperature = $Options.temperature
    }
    if ($Options.max_tokens) {
        $body.max_tokens = $Options.max_tokens
    }

    $headers = @{
        'Content-Type'  = 'application/json'
        'Authorization' = "Bearer $apiKey"
    }

    if ($Stream) {
        $body.stream = $true
        return Invoke-OpenAIStreamInternal -Body $body -Headers $headers -BaseUrl $baseUrl
    }

    $jsonBody = $body | ConvertTo-Json -Depth 20 -Compress
    $response = Invoke-RestMethod -Uri "$baseUrl/chat/completions" `
        -Method Post -Headers $headers -Body $jsonBody -ContentType 'application/json'

    # Parse response
    $choice = $response.choices[0]
    $message = $choice.message

    $content = if ($message.content) { $message.content } else { '' }
    $toolCalls = [System.Collections.Generic.List[ToolCall]]::new()

    if ($message.tool_calls) {
        foreach ($tc in $message.tool_calls) {
            $args = @{}
            try {
                $parsed = $tc.function.arguments | ConvertFrom-Json
                foreach ($p in $parsed.PSObject.Properties) {
                    $args[$p.Name] = $p.Value
                }
            }
            catch {
                $args = @{ _raw = $tc.function.arguments }
            }
            $toolCalls.Add([ToolCall]::new($tc.id, $tc.function.name, $args))
        }
    }

    $usage = if ($response.usage) {
        [Usage]::new(
            [int]($response.usage.prompt_tokens),
            [int]($response.usage.completion_tokens)
        )
    }
    else {
        [Usage]::Zero()
    }

    $stopReason = switch ($choice.finish_reason) {
        'stop' { 'stop' }
        'tool_calls' { 'tool_calls' }
        'length' { 'length' }
        'content_filter' { 'content_filter' }
        default { $choice.finish_reason }
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

function Invoke-OpenAIStreamInternal {
    [CmdletBinding()]
    param(
        [hashtable]$Body,
        [hashtable]$Headers,
        [string]$BaseUrl
    )

    $jsonBody = $Body | ConvertTo-Json -Depth 20 -Compress
    $chunks = Invoke-StreamingRequest -Uri "$BaseUrl/chat/completions" `
        -Headers $Headers -Body $jsonBody

    $fullText = ''
    $toolCalls = [System.Collections.Generic.List[ToolCall]]::new()
    $toolCallMap = @{}  # index -> {id, name, arguments_json}
    $inputTokens = 0
    $outputTokens = 0
    $finishReason = 'stop'

    foreach ($chunk in $chunks) {
        $data = $chunk.Data

        if ($null -eq $data -or $data -eq '[DONE]') {
            continue
        }

        if ($null -eq $data.choices -or $data.choices.Count -eq 0) {
            # Usage chunk at end
            if ($data.usage) {
                $inputTokens = [int]$data.usage.prompt_tokens
                $outputTokens = [int]$data.usage.completion_tokens
            }
            continue
        }

        $delta = $data.choices[0].delta
        $finish = $data.choices[0].finish_reason

        if ($delta.content) {
            $fullText += $delta.content
            [PSCustomObject]@{
                Type      = 'text-delta'
                TextDelta = $delta.content
            }
        }

        if ($delta.tool_calls) {
            foreach ($tcDelta in $delta.tool_calls) {
                $idx = [int]$tcDelta.index
                if (-not $toolCallMap.ContainsKey($idx)) {
                    $toolCallMap[$idx] = @{
                        id             = $tcDelta.id
                        name           = $tcDelta.function.name
                        arguments_json = ''
                    }
                }
                if ($tcDelta.function.arguments) {
                    $toolCallMap[$idx].arguments_json += $tcDelta.function.arguments
                }
            }
        }

        if ($finish) {
            $finishReason = $finish
        }
    }

    # Build final tool calls
    foreach ($idx in ($toolCallMap.Keys | Sort-Object)) {
        $entry = $toolCallMap[$idx]
        $args = @{}
        if ($entry.arguments_json) {
            try {
                $parsed = $entry.arguments_json | ConvertFrom-Json
                foreach ($p in $parsed.PSObject.Properties) {
                    $args[$p.Name] = $p.Value
                }
            }
            catch {
                $args = @{ _raw = $entry.arguments_json }
            }
        }
        $tc = [ToolCall]::new($entry.id, $entry.name, $args)
        $toolCalls.Add($tc)
        [PSCustomObject]@{
            Type     = 'tool-call'
            ToolCall = $tc
        }
    }

    # Emit finish
    $usage = [Usage]::new($inputTokens, $outputTokens)
    $stopReason = switch ($finishReason) {
        'stop' { 'stop' }
        'tool_calls' { 'tool_calls' }
        'length' { 'length' }
        'content_filter' { 'content_filter' }
        default { $finishReason }
    }
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
