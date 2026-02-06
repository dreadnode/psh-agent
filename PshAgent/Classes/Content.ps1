# Content helpers - text extraction from content (string or content parts)

class TextContent {
    [string]$Type = 'text'
    [string]$Text

    TextContent([string]$text) {
        $this.Text = $text
    }
}

class ImageContent {
    [string]$Type = 'image'
    [hashtable]$Source

    ImageContent([hashtable]$source) {
        $this.Source = $source
    }

    static [ImageContent] FromUrl([string]$url) {
        return [ImageContent]::new(@{ type = 'url'; url = $url })
    }

    static [ImageContent] FromBase64([string]$data, [string]$mediaType) {
        return [ImageContent]::new(@{ type = 'base64'; mediaType = $mediaType; data = $data })
    }
}

class ToolUseContent {
    [string]$Type = 'tool_use'
    [string]$Id
    [string]$Name
    [hashtable]$Input

    ToolUseContent([string]$id, [string]$name, [hashtable]$input) {
        $this.Id = $id
        $this.Name = $name
        $this.Input = $input
    }
}

class ToolResultContent {
    [string]$Type = 'tool_result'
    [string]$ToolUseId
    $Content  # string or array
    [bool]$IsError = $false

    ToolResultContent([string]$toolUseId, $content) {
        $this.ToolUseId = $toolUseId
        $this.Content = $content
    }
}

function Get-ContentText {
    <#
    .SYNOPSIS
    Extract text from content (string or content parts array)
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        $Content
    )

    if ($Content -is [string]) {
        return $Content
    }

    if ($Content -is [array]) {
        $texts = @()
        foreach ($part in $Content) {
            if ($part -is [TextContent]) {
                $texts += $part.Text
            }
            elseif ($part -is [hashtable] -and $part.type -eq 'text') {
                $texts += $part.text
            }
        }
        return ($texts -join '')
    }

    return [string]$Content
}
