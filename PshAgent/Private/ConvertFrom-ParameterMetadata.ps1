function ConvertFrom-ParameterMetadata {
    <#
    .SYNOPSIS
    Convert CommandInfo parameters to a JSON Schema object
    .DESCRIPTION
    Inspects parameter metadata from a PowerShell command and generates
    a JSON Schema suitable for LLM tool definitions.
    #>
    [CmdletBinding()]
    [OutputType([hashtable])]
    param(
        [Parameter(Mandatory)]
        [System.Management.Automation.CommandInfo]$CommandInfo,

        [Parameter()]
        [string[]]$ExcludeParameter,

        [Parameter()]
        [string[]]$IncludeParameter
    )

    # Common parameters to always exclude
    $commonParams = @(
        'Verbose', 'Debug', 'ErrorAction', 'WarningAction', 'InformationAction',
        'ErrorVariable', 'WarningVariable', 'InformationVariable', 'OutVariable',
        'OutBuffer', 'PipelineVariable', 'Confirm', 'WhatIf',
        'ProgressAction'
    )

    $properties = [ordered]@{}
    $required = [System.Collections.Generic.List[string]]::new()
    $switchParams = [System.Collections.Generic.List[string]]::new()

    # Try to get help for descriptions
    $helpInfo = $null
    try {
        $helpInfo = Get-Help -Name $CommandInfo.Name -Full -ErrorAction SilentlyContinue
    } catch { }

    # Build a lookup of help parameter descriptions
    $helpDescriptions = @{}
    if ($helpInfo -and $helpInfo.parameters -and $helpInfo.parameters.parameter) {
        foreach ($hp in $helpInfo.parameters.parameter) {
            if ($hp.name -and $hp.description) {
                $descText = ($hp.description | ForEach-Object { $_.Text }) -join ' '
                if ($descText) {
                    $helpDescriptions[$hp.name] = $descText.Trim()
                }
            }
        }
    }

    foreach ($param in $CommandInfo.Parameters.Values) {
        $paramName = $param.Name

        # Skip common parameters
        if ($paramName -in $commonParams) { continue }

        # Apply include filter
        if ($IncludeParameter -and $paramName -notin $IncludeParameter) { continue }

        # Apply exclude filter
        if ($ExcludeParameter -and $paramName -in $ExcludeParameter) { continue }

        # Track switch parameters for execution
        if ($param.ParameterType -eq [System.Management.Automation.SwitchParameter]) {
            $switchParams.Add($paramName)
        }

        # Convert type to JSON Schema
        $propSchema = ConvertFrom-PowerShellType -Type $param.ParameterType

        # Extract description from HelpMessage attribute or Get-Help
        $description = $null
        foreach ($attr in $param.Attributes) {
            if ($attr -is [System.Management.Automation.ParameterAttribute] -and $attr.HelpMessage) {
                $description = $attr.HelpMessage
                break
            }
        }
        if (-not $description -and $helpDescriptions.ContainsKey($paramName)) {
            $description = $helpDescriptions[$paramName]
        }
        if ($description) {
            $propSchema['description'] = $description
        }

        # Extract ValidateSet → enum
        foreach ($attr in $param.Attributes) {
            if ($attr -is [System.Management.Automation.ValidateSetAttribute]) {
                $propSchema['enum'] = @($attr.ValidValues)
                break
            }
        }

        # Extract ValidateRange → minimum/maximum
        foreach ($attr in $param.Attributes) {
            if ($attr -is [System.Management.Automation.ValidateRangeAttribute]) {
                if ($null -ne $attr.MinRange) { $propSchema['minimum'] = $attr.MinRange }
                if ($null -ne $attr.MaxRange) { $propSchema['maximum'] = $attr.MaxRange }
                break
            }
        }

        # Extract ValidatePattern → pattern
        foreach ($attr in $param.Attributes) {
            if ($attr -is [System.Management.Automation.ValidatePatternAttribute]) {
                $propSchema['pattern'] = $attr.RegexPattern
                break
            }
        }

        # Use snake_case for property names
        $schemaName = ConvertTo-SnakeCase -Name $paramName
        $properties[$schemaName] = $propSchema

        # Check if mandatory (in any parameter set)
        $isMandatory = $false
        foreach ($attr in $param.Attributes) {
            if ($attr -is [System.Management.Automation.ParameterAttribute] -and $attr.Mandatory) {
                $isMandatory = $true
                break
            }
        }
        if ($isMandatory) {
            $required.Add($schemaName)
        }
    }

    $schema = @{
        type       = 'object'
        properties = $properties
    }
    if ($required.Count -gt 0) {
        $schema['required'] = @($required)
    }

    # Return schema plus metadata for execution
    return @{
        Schema       = $schema
        SwitchParams = @($switchParams)
    }
}
