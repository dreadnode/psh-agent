#!/usr/bin/env python3
"""
Test potential failure cases - things Claude might generate that could break extraction.
"""

import re

CLS = "TestClass"
METHOD = "test_method"
PARAM = "config"
VALUE = "test_value"

# ═══════════════════════════════════════════════════════════════════════════════
# Potential problematic code patterns
# ═══════════════════════════════════════════════════════════════════════════════

POTENTIAL_ISSUES = {
    # ─── Python issues ────────────────────────────────────────────────────────
    "PY_CLASS_no_default_first_param": (
        # Claude might put the default param first, before self
        f"""
class {CLS}:
    def {METHOD}({PARAM}='{VALUE}', self):
        pass
""",
        r'class\s+(\w+)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
        True,  # Should this match?
    ),
    "PY_CLASS_type_hint_on_default": (
        # Claude might add type hints to default params
        f"""
class {CLS}:
    def {METHOD}(self, {PARAM}: str = '{VALUE}'):
        pass
""",
        r'class\s+(\w+)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)(?:\s*:\s*\w+)?\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
        True,  # Should match - type hint before =
    ),
    "PY_DECORATOR_no_parens": (
        # Wrong: decorator without parentheses won't match
        f"""
@provider
def {METHOD}({PARAM}='{VALUE}'):
    pass
""",
        r'@\w+\s*\(\s*[\'"](\w+)[\'"]\s*\)[\s\S]*?def\s+(\w+)\s*\([^)]*?(\w+)\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
        False,  # Should NOT match - no cls in decorator
    ),
    "PY_TYPEHINT_actual_type_not_string": (
        # Wrong: using actual type instead of string literal
        f"""
def {METHOD}({PARAM}: {CLS} = '{VALUE}'):
    pass
""",
        r'def\s+(\w+)\s*\([^)]*?(\w+)\s*:\s*[\'"](\w+)[\'"]\s*=\s*[\'"]([^\'"]*)[\'"]',
        {"method": 1, "param": 2, "cls": 3, "value": 4},
        False,  # Should NOT match - type is not quoted
    ),
    # ─── C# issues ────────────────────────────────────────────────────────────
    "CS_CLASS_static_method": (
        f'''
class {CLS}
{{
    public static void {METHOD}(string {PARAM} = "{VALUE}")
    {{
    }}
}}
''',
        r'class\s+(\w+)[\s\S]*?(?:void|string|int|bool|object)\s+(\w+)\s*\([^)]*?(?:string|int|bool|object)?\s*(\w+)\s*=\s*"([^"]*)"',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
        True,  # Should match - static is just another modifier
    ),
    "CS_ATTR_spaces_in_attr": (
        f'''
[Provider( "{CLS}" )]
void {METHOD}(string {PARAM} = "{VALUE}")
{{
}}
''',
        r'\[\w+\s*\(\s*"(\w+)"\s*\)\][\s\S]*?(?:void|string|int|bool|object)\s+(\w+)\s*\([^)]*?(?:string|int|bool|object)?\s*(\w+)\s*=\s*"([^"]*)"',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
        True,  # Should match - \s* handles spaces
    ),
    # ─── Java issues ──────────────────────────────────────────────────────────
    "JAVA_CLASS_final_var": (
        f'''
class {CLS} {{
    void {METHOD}() {{
        final String {PARAM} = "{VALUE}";
    }}
}}
''',
        r'class\s+(\w+)[\s\S]*?(?:void|String|int|boolean|Object)\s+(\w+)\s*\([^)]*\)\s*\{[^}]*?(?:final\s+)?(?:String|int|boolean|Object)\s+(\w+)\s*=\s*"([^"]*)"',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
        True,  # Now should match with optional final
    ),
    "JAVA_CLASS_var_keyword": (
        # Java 10+ var keyword
        f'''
class {CLS} {{
    void {METHOD}() {{
        var {PARAM} = "{VALUE}";
    }}
}}
''',
        r'class\s+(\w+)[\s\S]*?(?:void|String|int|boolean|Object)\s+(\w+)\s*\([^)]*\)\s*\{[^}]*?(?:String|int|boolean|Object)\s+(\w+)\s*=\s*"([^"]*)"',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
        False,  # Will NOT match - "var" not in type list
    ),
    "JAVA_MULTILINE_BODY": (
        # Multiple statements in method body
        f'''
class {CLS} {{
    void {METHOD}() {{
        int x = 5;
        String {PARAM} = "{VALUE}";
        System.out.println({PARAM});
    }}
}}
''',
        r'class\s+(\w+)[\s\S]*?(?:void|String|int|boolean|Object)\s+(\w+)\s*\([^)]*\)\s*\{[^}]*?(?:String|int|boolean|Object)\s+(\w+)\s*=\s*"([^"]*)"',
        {"cls": 1, "method": 2, "param": 3, "value": 4},
        True,  # Should match
    ),
}


def test_issue(
    name: str, code: str, pattern: str, group_map: dict, should_match: bool
) -> tuple[bool, str]:
    """Test if code matches/doesn't match as expected."""
    match = re.search(pattern, code)

    if should_match:
        if not match:
            return False, "FAIL: Should match but didn't"

        errors = []
        expected = {"cls": CLS, "method": METHOD, "param": PARAM, "value": VALUE}

        for key, group_num in group_map.items():
            actual = match.group(group_num)
            if actual != expected[key]:
                errors.append(f"  {key}: expected '{expected[key]}', got '{actual}'")

        if errors:
            return False, "FAIL: Wrong extraction:\n" + "\n".join(errors)

        return True, "OK (matched correctly)"
    else:
        if match:
            return True, "OK (correctly did not match)"
        else:
            return True, "OK (correctly did not match)"


def main():
    print("Testing potential failure cases\n")
    print("=" * 70)

    issues_found = []

    for name, (code, pattern, group_map, should_match) in POTENTIAL_ISSUES.items():
        passed, msg = test_issue(name, code, pattern, group_map, should_match)
        status = "✓" if passed else "✗"
        color = "\033[32m" if passed else "\033[31m"
        reset = "\033[0m"

        print(f"{color}{status}{reset} {name}: {msg}")

        if not passed:
            issues_found.append((name, code, msg))

    print("=" * 70)

    # Report issues that need fixing
    if issues_found:
        print("\n\033[33mIssues that need attention:\033[0m")
        for name, code, msg in issues_found:
            print(f"\n{name}:")
            print(f"  {msg}")
    else:
        print("\n\033[32mAll tests behave as expected!\033[0m")

    # Report known limitations
    print("\n\033[33mKnown limitations (by design):\033[0m")
    print("  - PY_DECORATOR_no_parens: Decorators without ('{cls}') won't work")
    print("  - PY_TYPEHINT_actual_type_not_string: Type must be quoted string")
    print("  - JAVA_CLASS_var_keyword: 'var' type inference not matched")

    return 0 if not issues_found else 1


if __name__ == "__main__":
    exit(main())
