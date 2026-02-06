function ConvertTo-SnakeCase {
    <#
    .SYNOPSIS
    Convert a PowerShell command name to snake_case tool name
    .DESCRIPTION
    Handles Verb-Noun format (Get-ChildItem → get_child_item) and
    PascalCase (MyFunction → my_function)
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Name
    )

    # Replace hyphens with underscores (Verb-Noun → Verb_Noun)
    $result = $Name -replace '-', '_'

    # Insert underscore before uppercase letters that follow lowercase letters or digits
    # e.g. ChildItem → Child_Item, getProcess2Name → get_Process2_Name
    $result = $result -replace '([a-z0-9])([A-Z])', '$1_$2'

    # Insert underscore between consecutive uppercase followed by lowercase
    # e.g. HTMLParser → HTML_Parser
    $result = $result -replace '([A-Z]+)([A-Z][a-z])', '$1_$2'

    return $result.ToLowerInvariant()
}
