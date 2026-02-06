# ToolCall and ToolResult classes

class ToolCall {
    [string]$Id
    [string]$Name
    [hashtable]$Arguments

    ToolCall([string]$id, [string]$name, [hashtable]$arguments) {
        $this.Id = $id
        $this.Name = $name
        $this.Arguments = $arguments
    }

    static [ToolCall] Create([string]$name, [hashtable]$arguments) {
        return [ToolCall]::new([guid]::NewGuid().ToString(), $name, $arguments)
    }

    static [ToolCall] Create([string]$name, [hashtable]$arguments, [string]$id) {
        return [ToolCall]::new($id, $name, $arguments)
    }
}

class ToolResult {
    [string]$ToolCallId
    $Content  # string or hashtable
    [bool]$IsError = $false

    ToolResult([string]$toolCallId, $content) {
        $this.ToolCallId = $toolCallId
        $this.Content = $content
    }

    ToolResult([string]$toolCallId, $content, [bool]$isError) {
        $this.ToolCallId = $toolCallId
        $this.Content = $content
        $this.IsError = $isError
    }
}
