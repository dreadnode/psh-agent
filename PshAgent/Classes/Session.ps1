# Session persistence class

class PshAgentSession {
    [string]$Id
    [string]$Name
    [datetime]$Created
    [datetime]$Updated
    [Message[]]$Messages = @()
    [int]$TotalTokens = 0
    [string]$ConnectionString

    PshAgentSession() {
        $this.Id = "session-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString().Substring(0, 6))"
        $this.Name = "Session $(Get-Date -Format 'g')"
        $this.Created = [datetime]::UtcNow
        $this.Updated = [datetime]::UtcNow
    }

    PshAgentSession([string]$name) {
        $this.Id = "session-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString().Substring(0, 6))"
        $this.Name = $name
        $this.Created = [datetime]::UtcNow
        $this.Updated = [datetime]::UtcNow
    }

    [void] AddMessage([Message]$message) {
        $this.Messages += $message
        $this.Updated = [datetime]::UtcNow
    }

    [void] UpdateTokens([int]$tokens) {
        $this.TotalTokens += $tokens
    }

    # Get session directory path
    static [string] GetSessionDir() {
        $dir = Join-Path ([System.Environment]::GetFolderPath('UserProfile')) '.psh-agent' 'sessions'
        if (-not (Test-Path $dir)) {
            $null = New-Item -Path $dir -ItemType Directory -Force
        }
        return $dir
    }

    # Get config directory
    static [string] GetConfigDir() {
        $dir = Join-Path ([System.Environment]::GetFolderPath('UserProfile')) '.psh-agent'
        if (-not (Test-Path $dir)) {
            $null = New-Item -Path $dir -ItemType Directory -Force
        }
        return $dir
    }

    # Serialize to hashtable
    [hashtable] ToHashtable() {
        return @{
            id               = $this.Id
            name             = $this.Name
            created          = $this.Created.ToString('o')
            updated          = $this.Updated.ToString('o')
            totalTokens      = $this.TotalTokens
            connectionString = $this.ConnectionString
            messages         = @($this.Messages | ForEach-Object { $_.ToHashtable() })
        }
    }

    # Deserialize from hashtable
    static [PshAgentSession] FromHashtable([hashtable]$data) {
        $session = [PshAgentSession]::new()
        $session.Id = $data.id
        $session.Name = $data.name
        $session.Created = [datetime]::Parse($data.created)
        $session.Updated = [datetime]::Parse($data.updated)
        $session.TotalTokens = [int]$data.totalTokens
        $session.ConnectionString = $data.connectionString

        if ($data.messages) {
            $session.Messages = @($data.messages | ForEach-Object {
                [Message]::FromHashtable($_)
            })
        }

        return $session
    }
}
