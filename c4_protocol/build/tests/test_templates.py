#!/usr/bin/env python3
"""
Test that each template family produces code that matches the implant's regex patterns.
This validates the template→regex alignment.
"""

import re

# Sample values for testing
CLS = "TestClass"
METHOD = "test_method"
PARAM = "config"
VALUE = "test_value"

# ═══════════════════════════════════════════════════════════════════════════════
# Expected code output for each template family
# These represent what Claude should generate from the templates
# ═══════════════════════════════════════════════════════════════════════════════

EXPECTED_CODE = {
    # Python: CLASS_METHOD
    "CLASS_METHOD": f"""
class {CLS}:
    def {METHOD}(self, {PARAM}='{VALUE}'):
        pass
""",
    # Python: DECORATOR
    "DECORATOR": f"""
@provider('{CLS}')
def {METHOD}({PARAM}='{VALUE}'):
    pass
""",
    # Python: TYPE_HINT
    "TYPE_HINT": f"""
def {METHOD}({PARAM}: '{CLS}' = '{VALUE}'):
    pass
""",
    # C#: CSHARP_CLASS
    "CSHARP_CLASS": f'''
class {CLS}
{{
    void {METHOD}(string {PARAM} = "{VALUE}")
    {{
    }}
}}
''',
    # C#: CSHARP_ATTRIBUTE
    "CSHARP_ATTRIBUTE": f'''
[Provider("{CLS}")]
void {METHOD}(string {PARAM} = "{VALUE}")
{{
}}
''',
    # Java: JAVA_CLASS
    "JAVA_CLASS": f'''
class {CLS} {{
    void {METHOD}() {{
        String {PARAM} = "{VALUE}";
    }}
}}
''',
    # Java: JAVA_ANNOTATION
    "JAVA_ANNOTATION": f'''
@Provider("{CLS}")
void {METHOD}() {{
    String {PARAM} = "{VALUE}";
}}
''',
}

# ═══════════════════════════════════════════════════════════════════════════════
# Regex patterns from the implant (converted to Python regex syntax)
# ═══════════════════════════════════════════════════════════════════════════════

PATTERNS = {
    # Python patterns (updated to handle optional type hints)
    "CLASS_METHOD": (
        r'class\s+(\w+)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)(?:\s*:\s*\w+)?\s*=\s*[\'"]([^\'"]*)[\'"]',
        # Groups: 1=class, 2=method, 3=param, 4=value
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    "DECORATOR": (
        r'@\w+\s*\(\s*[\'"](\w+)[\'"]\s*\)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)(?:\s*:\s*\w+)?\s*=\s*[\'"]([^\'"]*)[\'"]',
        # Groups: 1=cls, 2=method, 3=param, 4=value
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    "TYPE_HINT": (
        r'def\s+(\w+)\s*\([^)]*?(\w+)\s*:\s*[\'"](\w+)[\'"]\s*=\s*[\'"]([^\'"]*)[\'"]',
        # Groups: 1=method, 2=param, 3=cls, 4=value
        {"method": 1, "param": 2, "cls": 3, "value": 4},
    ),
    # C# patterns
    "CSHARP_CLASS": (
        r'class\s+(\w+)[\s\S]*?(?:void|string|int|bool|object)\s+(\w+)\s*\([^)]*?(?:string|int|bool|object)?\s*(\w+)\s*=\s*"([^"]*)"',
        # Groups: 1=class, 2=method, 3=param, 4=value
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    "CSHARP_ATTRIBUTE": (
        r'\[\w+\s*\(\s*"(\w+)"\s*\)\][\s\S]*?(?:void|string|int|bool|object)\s+(\w+)\s*\([^)]*?(?:string|int|bool|object)?\s*(\w+)\s*=\s*"([^"]*)"',
        # Groups: 1=cls, 2=method, 3=param, 4=value
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    # Java patterns (updated to handle optional final keyword)
    "JAVA_CLASS": (
        r'class\s+(\w+)[\s\S]*?(?:void|String|int|boolean|Object)\s+(\w+)\s*\([^)]*\)\s*\{[^}]*?(?:final\s+)?(?:String|int|boolean|Object)\s+(\w+)\s*=\s*"([^"]*)"',
        # Groups: 1=class, 2=method, 3=param, 4=value
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    "JAVA_ANNOTATION": (
        r'@\w+\s*\(\s*"(\w+)"\s*\)[\s\S]*?(?:void|String|int|boolean|Object)\s+(\w+)\s*\([^)]*\)\s*\{[^}]*?(?:final\s+)?(?:String|int|boolean|Object)\s+(\w+)\s*=\s*"([^"]*)"',
        # Groups: 1=cls, 2=method, 3=param, 4=value
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
}


def test_pattern(family: str) -> tuple[bool, str]:
    """Test if expected code matches the regex and extracts correct values."""
    code = EXPECTED_CODE[family]
    pattern, group_map = PATTERNS[family]

    match = re.search(pattern, code)
    if not match:
        return False, f"Pattern did not match code:\n{code}"

    # Verify extracted values
    errors = []
    expected = {"cls": CLS, "method": METHOD, "param": PARAM, "value": VALUE}

    for key, group_num in group_map.items():
        actual = match.group(group_num)
        if actual != expected[key]:
            errors.append(f"  {key}: expected '{expected[key]}', got '{actual}'")

    if errors:
        return False, "Extraction errors:\n" + "\n".join(errors)

    return True, "OK"


def main():
    print("Testing template→regex alignment\n")
    print("=" * 60)

    all_passed = True

    for family in EXPECTED_CODE.keys():
        passed, msg = test_pattern(family)
        status = "✓" if passed else "✗"
        color = "\033[32m" if passed else "\033[31m"
        reset = "\033[0m"

        print(f"{color}{status}{reset} {family}: {msg}")

        if not passed:
            all_passed = False

    print("=" * 60)

    if all_passed:
        print("\n\033[32mAll tests passed!\033[0m")
        return 0
    else:
        print("\n\033[31mSome tests failed!\033[0m")
        return 1


if __name__ == "__main__":
    exit(main())
