function New-OutputPatternCondition {
    <#
    .SYNOPSIS
    Stop when output matches a pattern
    .PARAMETER Pattern
    Text or regex pattern to match
    .PARAMETER CaseSensitive
    Perform case-sensitive matching
    .PARAMETER Regex
    Treat pattern as regex
    .PARAMETER Exact
    Require exact match (not substring)
    .EXAMPLE
    $cond = New-OutputPatternCondition -Pattern 'DONE'
    .EXAMPLE
    $cond = New-OutputPatternCondition -Pattern '^\d+$' -Regex
    #>
    [CmdletBinding()]
    [OutputType([StopCondition])]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Pattern,

        [Parameter()]
        [switch]$CaseSensitive,

        [Parameter()]
        [switch]$Regex,

        [Parameter()]
        [switch]$Exact
    )

    $pat = $Pattern
    $cs = [bool]$CaseSensitive
    $rx = [bool]$Regex
    $ex = [bool]$Exact

    return [StopCondition]::new(
        "stop_on_output($Pattern)",
        {
            param($steps)
            # Find last generation step
            $lastGen = $null
            for ($i = $steps.Count - 1; $i -ge 0; $i--) {
                if ($steps[$i].Type -eq [AgentEventType]::GenerationStep) {
                    $lastGen = $steps[$i]
                    break
                }
            }
            if (-not $lastGen -or -not $lastGen.Messages -or $lastGen.Messages.Count -eq 0) { return $false }

            $text = $lastGen.Messages[-1].GetText()
            if (-not $text) { return $false }

            if ($rx) {
                $opts = if ($cs) { 'None' } else { 'IgnoreCase' }
                return [regex]::IsMatch($text, $pat, $opts)
            }
            if ($ex) {
                if ($cs) { return $text -ceq $pat }
                return $text -eq $pat
            }
            # Substring containment
            if ($cs) { return $text.Contains($pat) }
            return $text.ToLower().Contains($pat.ToLower())
        }.GetNewClosure()
    )
}
