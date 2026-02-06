function ConvertFrom-PowerShellType {
    <#
    .SYNOPSIS
    Map a .NET type to a JSON Schema type definition
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [Type]$Type
    )

    # Unwrap Nullable<T>
    $underlying = [System.Nullable]::GetUnderlyingType($Type)
    if ($underlying) {
        $Type = $underlying
    }

    # Switch parameter
    if ($Type -eq [System.Management.Automation.SwitchParameter]) {
        return @{ type = 'boolean' }
    }

    # Boolean
    if ($Type -eq [bool]) {
        return @{ type = 'boolean' }
    }

    # Integer types
    if ($Type -in @([int], [long], [short], [byte], [sbyte], [uint16], [uint32], [uint64], [System.Numerics.BigInteger])) {
        return @{ type = 'integer' }
    }

    # Number types
    if ($Type -in @([double], [float], [decimal])) {
        return @{ type = 'number' }
    }

    # String
    if ($Type -eq [string]) {
        return @{ type = 'string' }
    }

    # DateTime
    if ($Type -eq [datetime]) {
        return @{ type = 'string'; format = 'date-time' }
    }

    # Enum
    if ($Type.IsEnum) {
        return @{ type = 'string'; enum = @([System.Enum]::GetNames($Type)) }
    }

    # Array types
    if ($Type.IsArray) {
        $elementType = $Type.GetElementType()
        $itemSchema = ConvertFrom-PowerShellType -Type $elementType
        return @{ type = 'array'; items = $itemSchema }
    }

    # Generic collections (List<T>, IEnumerable<T>, etc.)
    if ($Type.IsGenericType) {
        $genericArgs = $Type.GetGenericArguments()
        if ($genericArgs.Count -eq 1) {
            $ifaces = $Type.GetInterfaces()
            $isEnumerable = $ifaces | Where-Object {
                $_.IsGenericType -and $_.GetGenericTypeDefinition() -eq [System.Collections.Generic.IEnumerable[object]].GetGenericTypeDefinition()
            }
            if ($isEnumerable) {
                $itemSchema = ConvertFrom-PowerShellType -Type $genericArgs[0]
                return @{ type = 'array'; items = $itemSchema }
            }
        }
    }

    # Hashtable / PSObject / PSCustomObject → object
    if ($Type -in @([hashtable], [System.Collections.Specialized.OrderedDictionary], [psobject], [pscustomobject])) {
        return @{ type = 'object' }
    }

    # IDictionary types
    if ($Type.GetInterface('IDictionary')) {
        return @{ type = 'object' }
    }

    # Fallback to string
    return @{ type = 'string' }
}
