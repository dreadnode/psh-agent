$content = Get-Content "c4_protocol/test_polymorphic.py" -Raw
$file = [PSCustomObject]@{ Name = "test_polymorphic.py" }

$results = [System.Collections.Generic.List[PSCustomObject]]::new()

# Python Polymorphic Patterns
$patterns = @(
    # 1. Standard Class Method: class {cls} ... def {method}(..., {param}='{value}')
    'class\s+(\w+)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)\s*=\s*[''"]([^''"]*)[''"]',
    
    # 2. Class Attribute: class {cls} ... {param} = '{value}' ... def {method}
    'class\s+(\w+)[\s\S]*?(\w+)\s*=\s*[''"]([^''"]*)[''"][\s\S]*?def\s+(\w+)',
    'class\s+(\w+)[\s\S]*?def\s+(\w+)[\s\S]*?(\w+)\s*=\s*[''"]([^''"]*)[''"]', # Attribute after method
    
    # 3. Decorator: @\w+("{cls}") ... def {method}(..., {param}='{value}')
    '@\w+\s*\(\s*[''"](\w+)[''"]\s*\)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)\s*=\s*[''"]([^''"]*)[''"]',
    
    # 4. Type Hint: def {method}(..., {param}: "{cls}" = "{value}")
    'def\s+(\w+)\s*\([^)]*?(\w+)\s*:\s*[''"](\w+)[''"]\s*=\s*[''"]([^''"]*)[''"]'
)

foreach ($p in $patterns) {
    $matches = [regex]::Matches($content, $p)
    foreach ($m in $matches) {
        if ($p -like "*:\s*[''"](\w+)[''"]*") {
            # Type Hint pattern: Method, Param, Class, Value
            $results.Add([PSCustomObject]@{
                Pattern      = "TypeHint"
                ClassName    = $m.Groups[3].Value
                MethodName   = $m.Groups[1].Value
                DefaultValue = $m.Groups[4].Value
            })
        }
        elseif ($p -like "*=\s*[''"]([^''"]*)[''"][\s\S]*?def*") {
            # Class Attribute pattern (Attr before Method): Class, Param, Value, Method
            $results.Add([PSCustomObject]@{
                Pattern      = "ClassAttrBefore"
                ClassName    = $m.Groups[1].Value
                MethodName   = $m.Groups[4].Value
                DefaultValue = $m.Groups[3].Value
            })
        }
        elseif ($p -like "*def\s+(\w+)[\s\S]*?(\w+)\s*=\s*[''"]*") {
            # Class Attribute pattern (Attr after Method): Class, Method, Param, Value
            $results.Add([PSCustomObject]@{
                Pattern      = "ClassAttrAfter"
                ClassName    = $m.Groups[1].Value
                MethodName   = $m.Groups[2].Value
                DefaultValue = $m.Groups[4].Value
            })
        }
        else {
            # Standard / Decorator pattern: Class, Method, Param, Value
            $results.Add([PSCustomObject]@{
                Pattern      = if ($p -like "@*") { "Decorator" } else { "Standard" }
                ClassName    = $m.Groups[1].Value
                MethodName   = $m.Groups[2].Value
                DefaultValue = $m.Groups[4].Value
            })
        }
    }
}

$results | Format-Table -AutoSize
