function New-Tool {
    <#
    .SYNOPSIS
    Define a tool with name, description, JSON schema params, and execute scriptblock
    .PARAMETER Name
    Unique tool name
    .PARAMETER Description
    Tool description for the LLM
    .PARAMETER Parameters
    JSON Schema hashtable for parameters
    .PARAMETER Execute
    Scriptblock that receives a hashtable of arguments and returns a result
    .EXAMPLE
    $calc = New-Tool -Name 'calculator' -Description 'Do math' -Parameters @{
        type = 'object'
        properties = @{
            expression = @{ type = 'string'; description = 'Math expression' }
        }
        required = @('expression')
    } -Execute {
        param($args)
        Invoke-Expression $args.expression
    }
    #>
    [CmdletBinding()]
    [OutputType([PshAgentTool])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$Description,

        [Parameter(Mandatory)]
        [hashtable]$Parameters,

        [Parameter(Mandatory)]
        [scriptblock]$Execute
    )

    $schema = ConvertTo-JsonSchema -Schema $Parameters
    return [PshAgentTool]::new($Name, $Description, $schema, $Execute)
}
