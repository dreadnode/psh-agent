# PshGenerator - connection string parsing and provider dispatch

class PshGenerator {
    [string]$Provider
    [string]$ModelId
    [string]$ConnectionString
    [hashtable]$Defaults

    PshGenerator([string]$connectionString) {
        $this.ConnectionString = $connectionString
        $this.Defaults = @{}
        $this._ParseConnectionString($connectionString)
    }

    PshGenerator([string]$connectionString, [hashtable]$defaults) {
        $this.ConnectionString = $connectionString
        $this.Defaults = $defaults
        $this._ParseConnectionString($connectionString)
    }

    hidden [void] _ParseConnectionString([string]$cs) {
        # Support both / and : separator: 'anthropic/claude-sonnet-4-20250514' or 'anthropic:claude-sonnet-4-20250514'
        $separator = if ($cs.Contains('/')) { '/' } else { ':' }
        $parts = $cs.Split($separator, 2)

        if ($parts.Count -lt 2) {
            throw "Invalid connection string '$cs'. Expected format: provider/model (e.g., anthropic/claude-sonnet-4-20250514)"
        }

        $this.Provider = $parts[0].ToLower()
        $this.ModelId = $parts[1]
    }

    # Get API key from environment
    [string] GetApiKey() {
        $envVarMap = @{
            'anthropic' = 'ANTHROPIC_API_KEY'
            'openai'    = 'OPENAI_API_KEY'
        }

        $envVar = $envVarMap[$this.Provider]
        if (-not $envVar) {
            $envVar = "$($this.Provider.ToUpper())_API_KEY"
        }

        $key = [System.Environment]::GetEnvironmentVariable($envVar)
        if (-not $key) {
            throw "No API key found. Set environment variable $envVar"
        }
        return $key
    }

    # Non-streaming generation
    [hashtable] Generate([Message[]]$messages, [hashtable]$options) {
        $merged = @{}
        foreach ($k in $this.Defaults.Keys) { $merged[$k] = $this.Defaults[$k] }
        if ($options) {
            foreach ($k in $options.Keys) { $merged[$k] = $options[$k] }
        }

        switch ($this.Provider) {
            'anthropic' {
                return Invoke-AnthropicApi -Generator $this -Messages $messages -Options $merged
            }
            'openai' {
                return Invoke-OpenAIApi -Generator $this -Messages $messages -Options $merged
            }
            default {
                # Try OpenAI-compatible for unknown providers
                return Invoke-OpenAIApi -Generator $this -Messages $messages -Options $merged
            }
        }
    }

    # Streaming generation
    [System.Collections.Generic.IEnumerable[hashtable]] Stream([Message[]]$messages, [hashtable]$options) {
        $merged = @{}
        foreach ($k in $this.Defaults.Keys) { $merged[$k] = $this.Defaults[$k] }
        if ($options) {
            foreach ($k in $options.Keys) { $merged[$k] = $options[$k] }
        }

        switch ($this.Provider) {
            'anthropic' {
                return Invoke-AnthropicApi -Generator $this -Messages $messages -Options $merged -Stream
            }
            'openai' {
                return Invoke-OpenAIApi -Generator $this -Messages $messages -Options $merged -Stream
            }
            default {
                return Invoke-OpenAIApi -Generator $this -Messages $messages -Options $merged -Stream
            }
        }
    }
}
