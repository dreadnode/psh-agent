function Invoke-StreamingRequest {
    <#
    .SYNOPSIS
    SSE streaming HTTP helper using System.Net.Http.HttpClient with ResponseHeadersRead
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Uri,

        [Parameter(Mandatory)]
        [hashtable]$Headers,

        [Parameter(Mandatory)]
        [string]$Body
    )

    $httpClient = $null
    $response = $null
    $stream = $null
    $reader = $null

    try {
        $handler = [System.Net.Http.HttpClientHandler]::new()
        $httpClient = [System.Net.Http.HttpClient]::new($handler)
        $httpClient.Timeout = [System.TimeSpan]::FromMinutes(5)

        $request = [System.Net.Http.HttpRequestMessage]::new(
            [System.Net.Http.HttpMethod]::Post,
            $Uri
        )

        $request.Content = [System.Net.Http.StringContent]::new(
            $Body,
            [System.Text.Encoding]::UTF8,
            'application/json'
        )

        foreach ($key in $Headers.Keys) {
            if ($key -eq 'Content-Type') { continue }
            $null = $request.Headers.TryAddWithoutValidation($key, $Headers[$key])
        }

        # Use ResponseHeadersRead to start processing before full response
        $response = $httpClient.SendAsync(
            $request,
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()

        if (-not $response.IsSuccessStatusCode) {
            $errorBody = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            throw "HTTP $([int]$response.StatusCode): $errorBody"
        }

        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $reader = [System.IO.StreamReader]::new($stream)

        $currentEvent = $null

        while (-not $reader.EndOfStream) {
            $line = $reader.ReadLineAsync().GetAwaiter().GetResult()

            if ($null -eq $line) { break }

            # Empty line = end of SSE event
            if ([string]::IsNullOrEmpty($line)) {
                $currentEvent = $null
                continue
            }

            # Event type line
            if ($line.StartsWith('event: ')) {
                $currentEvent = $line.Substring(7).Trim()
                continue
            }

            # Data line
            if ($line.StartsWith('data: ')) {
                $dataStr = $line.Substring(6)

                if ($dataStr -eq '[DONE]') {
                    continue
                }

                try {
                    $parsed = $dataStr | ConvertFrom-Json
                    [PSCustomObject]@{
                        Event = $currentEvent
                        Data  = $parsed
                    }
                }
                catch {
                    # Skip unparseable data
                }
            }
        }
    }
    finally {
        if ($reader) { $reader.Dispose() }
        if ($stream) { $stream.Dispose() }
        if ($response) { $response.Dispose() }
        if ($httpClient) { $httpClient.Dispose() }
    }
}
