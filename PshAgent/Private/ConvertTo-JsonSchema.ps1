function ConvertTo-JsonSchema {
    <#
    .SYNOPSIS
    Normalize tool parameter schemas to JSON Schema format
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [hashtable]$Schema
    )

    # If already has 'type' key, assume it's a valid JSON schema
    if ($Schema.ContainsKey('type')) {
        return $Schema
    }

    # Wrap bare properties into object schema
    if ($Schema.ContainsKey('properties')) {
        $result = @{
            type       = 'object'
            properties = $Schema.properties
        }
        if ($Schema.ContainsKey('required')) {
            $result.required = $Schema.required
        }
        return $result
    }

    # Return as-is if it doesn't match expected patterns
    return $Schema
}
