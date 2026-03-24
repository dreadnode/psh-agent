#!/usr/bin/env python3
"""
Test edge cases and variations that Claude might produce.
"""

import re

CLS = "TestClass"
METHOD = "test_method"
PARAM = "config"
VALUE = "test_value"

# ═══════════════════════════════════════════════════════════════════════════════
# Edge case code variations
# ═══════════════════════════════════════════════════════════════════════════════

EDGE_CASES = {
    # ─── Python CLASS_METHOD variations ───────────────────────────────────────
    "PY_CLASS_multiline": (
        f'''
class {CLS}:
    """Docstring here."""

    def __init__(self):
        pass

    def {METHOD}(self, {PARAM}='{VALUE}'):
        return None
''',
        r'class\s+(\w+)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    "PY_CLASS_double_quotes": (
        f'''
class {CLS}:
    def {METHOD}(self, {PARAM}="{VALUE}"):
        pass
''',
        r'class\s+(\w+)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    "PY_CLASS_multiple_params": (
        f"""
class {CLS}:
    def {METHOD}(self, other_param, {PARAM}='{VALUE}', another=None):
        pass
""",
        r'class\s+(\w+)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    # ─── Python DECORATOR variations ──────────────────────────────────────────
    "PY_DECORATOR_with_imports": (
        f"""
from decorators import provider

@provider('{CLS}')
def {METHOD}({PARAM}='{VALUE}'):
    pass
""",
        r'@\w+\s*\(\s*[\'"](\w+)[\'"]\s*\)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    "PY_DECORATOR_newline_before_def": (
        f"""
@provider('{CLS}')

def {METHOD}({PARAM}='{VALUE}'):
    pass
""",
        r'@\w+\s*\(\s*[\'"](\w+)[\'"]\s*\)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    "PY_DECORATOR_double_quotes": (
        f'''
@provider("{CLS}")
def {METHOD}({PARAM}="{VALUE}"):
    pass
''',
        r'@\w+\s*\(\s*[\'"](\w+)[\'"]\s*\)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    # ─── Python TYPE_HINT variations ──────────────────────────────────────────
    "PY_TYPEHINT_with_return": (
        f"""
def {METHOD}({PARAM}: '{CLS}' = '{VALUE}') -> None:
    pass
""",
        r'def\s+(\w+)\s*\([^)]*?(\w+)\s*:\s*[\'"](\w+)[\'"]\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"method": 1, "param": 2, "cls": 3, "value": 4},
    ),
    "PY_TYPEHINT_double_quotes": (
        f'''
def {METHOD}({PARAM}: "{CLS}" = "{VALUE}"):
    pass
''',
        r'def\s+(\w+)\s*\([^)]*?(\w+)\s*:\s*[\'"](\w+)[\'"]\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"method": 1, "param": 2, "cls": 3, "value": 4},
    ),
    # ─── C# CLASS variations ──────────────────────────────────────────────────
    "CS_CLASS_with_namespace": (
        f'''
namespace MyApp
{{
    public class {CLS}
    {{
        public void {METHOD}(string {PARAM} = "{VALUE}")
        {{
            Console.WriteLine({PARAM});
        }}
    }}
}}
''',
        r'class\s+(\w+)[\s\S]*?(?:void|string|int|bool|object)\s+(\w+)\s*\([^)]*?(?:string|int|bool|object)?\s*(\w+)\s*=\s*"([^"]*)"',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    "CS_CLASS_private_method": (
        f'''
class {CLS}
{{
    private void {METHOD}(string {PARAM} = "{VALUE}")
    {{
    }}
}}
''',
        r'class\s+(\w+)[\s\S]*?(?:void|string|int|bool|object)\s+(\w+)\s*\([^)]*?(?:string|int|bool|object)?\s*(\w+)\s*=\s*"([^"]*)"',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    # ─── C# ATTRIBUTE variations ──────────────────────────────────────────────
    "CS_ATTR_multiple_attrs": (
        f'''
[Obsolete]
[Provider("{CLS}")]
public void {METHOD}(string {PARAM} = "{VALUE}")
{{
}}
''',
        r'\[\w+\s*\(\s*"(\w+)"\s*\)\][\s\S]*?(?:void|string|int|bool|object)\s+(\w+)\s*\([^)]*?(?:string|int|bool|object)?\s*(\w+)\s*=\s*"([^"]*)"',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    # ─── Java CLASS variations ────────────────────────────────────────────────
    "JAVA_CLASS_public": (
        f'''
public class {CLS} {{
    public void {METHOD}() {{
        String {PARAM} = "{VALUE}";
        System.out.println({PARAM});
    }}
}}
''',
        r'class\s+(\w+)[\s\S]*?(?:void|String|int|boolean|Object)\s+(\w+)\s*\([^)]*\)\s*\{[^}]*?(?:final\s+)?(?:String|int|boolean|Object)\s+(\w+)\s*=\s*"([^"]*)"',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    "JAVA_CLASS_with_package": (
        f'''
package com.example;

public class {CLS} {{
    void {METHOD}() {{
        String {PARAM} = "{VALUE}";
    }}
}}
''',
        r'class\s+(\w+)[\s\S]*?(?:void|String|int|boolean|Object)\s+(\w+)\s*\([^)]*\)\s*\{[^}]*?(?:final\s+)?(?:String|int|boolean|Object)\s+(\w+)\s*=\s*"([^"]*)"',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
    # ─── Java ANNOTATION variations ───────────────────────────────────────────
    "JAVA_ANNOT_with_class": (
        f'''
public class MyService {{
    @Provider("{CLS}")
    public void {METHOD}() {{
        String {PARAM} = "{VALUE}";
    }}
}}
''',
        r'@\w+\s*\(\s*"(\w+)"\s*\)[\s\S]*?(?:void|String|int|boolean|Object)\s+(\w+)\s*\([^)]*\)\s*\{[^}]*?(?:final\s+)?(?:String|int|boolean|Object)\s+(\w+)\s*=\s*"([^"]*)"',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
    ),
}


def test_edge_case(
    name: str, code: str, pattern: str, group_map: dict
) -> tuple[bool, str]:
    """Test if code matches the regex and extracts correct values."""
    match = re.search(pattern, code)
    if not match:
        return False, "Pattern did not match"

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
    print("Testing edge cases and variations\n")
    print("=" * 70)

    all_passed = True

    for name, (code, pattern, group_map) in EDGE_CASES.items():
        passed, msg = test_edge_case(name, code, pattern, group_map)
        status = "✓" if passed else "✗"
        color = "\033[32m" if passed else "\033[31m"
        reset = "\033[0m"

        print(f"{color}{status}{reset} {name}: {msg}")

        if not passed:
            all_passed = False
            print(f"   Code:\n{code}")

    print("=" * 70)

    if all_passed:
        print("\n\033[32mAll edge case tests passed!\033[0m")
        return 0
    else:
        print("\n\033[31mSome edge case tests failed!\033[0m")
        return 1


if __name__ == "__main__":
    exit(main())
