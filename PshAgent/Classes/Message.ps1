# Message class - represents a single message in a conversation

class Message {
    [MessageRole]$Role
    $Content  # string or array of content parts
    [string]$Name
    [ToolCall[]]$ToolCalls
    [string]$ToolCallId

    Message([MessageRole]$role, $content) {
        $this.Role = $role
        $this.Content = $content
    }

    # System message factory
    static [Message] System([string]$content) {
        return [Message]::new([MessageRole]::system, $content)
    }

    # User message factory
    static [Message] User($content) {
        return [Message]::new([MessageRole]::user, $content)
    }

    # User message with name
    static [Message] User($content, [string]$name) {
        $msg = [Message]::new([MessageRole]::user, $content)
        $msg.Name = $name
        return $msg
    }

    # Assistant message factory
    static [Message] Assistant($content) {
        return [Message]::new([MessageRole]::assistant, $content)
    }

    # Assistant message with tool calls
    static [Message] Assistant($content, [ToolCall[]]$toolCalls) {
        $msg = [Message]::new([MessageRole]::assistant, $content)
        $msg.ToolCalls = $toolCalls
        return $msg
    }

    # Tool result message factory
    static [Message] Tool([string]$toolCallId, $content) {
        $msg = [Message]::new([MessageRole]::tool, $content)
        $msg.ToolCallId = $toolCallId
        return $msg
    }

    # Get text content
    [string] GetText() {
        return Get-ContentText -Content $this.Content
    }

    # Check if message has tool calls
    [bool] HasToolCalls() {
        return ($null -ne $this.ToolCalls -and $this.ToolCalls.Count -gt 0)
    }

    # Convert to hashtable for serialization
    [hashtable] ToHashtable() {
        $h = @{
            role    = $this.Role.ToString()
            content = $this.Content
        }
        if ($this.Name) { $h.name = $this.Name }
        if ($this.ToolCalls) {
            $h.toolCalls = @($this.ToolCalls | ForEach-Object {
                @{ id = $_.Id; name = $_.Name; arguments = $_.Arguments }
            })
        }
        if ($this.ToolCallId) { $h.toolCallId = $this.ToolCallId }
        return $h
    }

    # Create from hashtable
    static [Message] FromHashtable([hashtable]$data) {
        $msg = [Message]::new([MessageRole]($data.role), $data.content)
        if ($data.name) { $msg.Name = $data.name }
        if ($data.toolCallId) { $msg.ToolCallId = $data.toolCallId }
        if ($data.toolCalls) {
            $msg.ToolCalls = @($data.toolCalls | ForEach-Object {
                [ToolCall]::new($_.id, $_.name, $_.arguments)
            })
        }
        return $msg
    }
}
