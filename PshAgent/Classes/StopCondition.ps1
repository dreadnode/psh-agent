# StopCondition class with .And()/.Or()/.Not() composition

class StopCondition {
    [string]$Name
    [scriptblock]$Fn
    [bool]$CatchErrors = $false
    [bool]$DefaultValue = $false

    StopCondition([string]$name, [scriptblock]$fn) {
        $this.Name = $name
        $this.Fn = $fn
    }

    StopCondition([string]$name, [scriptblock]$fn, [bool]$catchErrors, [bool]$defaultValue) {
        $this.Name = $name
        $this.Fn = $fn
        $this.CatchErrors = $catchErrors
        $this.DefaultValue = $defaultValue
    }

    [bool] Evaluate([array]$steps) {
        try {
            return (& $this.Fn $steps)
        }
        catch {
            if ($this.CatchErrors) {
                Write-Warning "[StopCondition] Error evaluating $($this.Name): $_"
                return $this.DefaultValue
            }
            throw
        }
    }

    [StopCondition] And([StopCondition]$other) {
        $self = $this
        $otherRef = $other
        return [StopCondition]::new(
            "($($this.Name) & $($other.Name))",
            { param($steps) $self.Evaluate($steps) -and $otherRef.Evaluate($steps) }.GetNewClosure()
        )
    }

    [StopCondition] Or([StopCondition]$other) {
        $self = $this
        $otherRef = $other
        return [StopCondition]::new(
            "($($this.Name) | $($other.Name))",
            { param($steps) $self.Evaluate($steps) -or $otherRef.Evaluate($steps) }.GetNewClosure()
        )
    }

    [StopCondition] Not() {
        $self = $this
        return [StopCondition]::new(
            "~$($this.Name)",
            { param($steps) -not $self.Evaluate($steps) }.GetNewClosure()
        )
    }
}
