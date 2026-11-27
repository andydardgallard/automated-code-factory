#!/usr/bin/env python3
"""
Deterministic self-test for `validate_mermaid.py` (zero LLM tokens).

Validates the structural Mermaid checker: valid flowcharts pass; missing block, unbalanced
brackets, crossed/reversed delimiters and dangling edges fail; quoted, escaped and deeply nested
labels stay valid.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import sys

import validate_mermaid as vmm


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


VALID = """```mermaid
flowchart TD
    A([BEGIN]) --> B[Step one]
    B --> C{Decision?}
    C -->|No| D[End]
    C -->|Yes| E[Next]
```
"""

MISSING_BLOCK = "# no mermaid here\n"

UNBALANCED = """```mermaid
flowchart TD
    A([BEGIN) --> B[broken]
```
"""

DANGLING_EDGE = """```mermaid
flowchart TD
    A([BEGIN]) -->
```
"""

NO_HEADER = """```mermaid
    A([BEGIN]) --> B[End]
```
"""

REVERSED = """```mermaid
flowchart TD
    A] --> B[
```
"""

CROSSED = """```mermaid
flowchart TD
    A([)] --> B[End]
```
"""

# Delimiter-shaped characters inside a quoted label are label text, never syntax.
QUOTED = r"""```mermaid
flowchart TD
    A["array[0] {x} (y) and a stray ] here"] --> B[Ok]
    B["escaped \" ] ( { quote"] --> C[Next]
```
"""

# `[(cylinder)]`, `{{hexagon}}` and `([stadium])` are legitimately nested shapes.
NESTED = """```mermaid
flowchart TD
    A[(Database)] --> B{{Hexagon}} --> C([Stadium])
```
"""


def main() -> int:
    # 1. valid block passes.
    block = vmm.extract_block(VALID)
    expect(block is not None, "valid block must be extracted")
    expect(vmm.check_block(block) == [], f"valid flowchart must have no errors: {vmm.check_block(block)}")

    # 2. missing block -> None.
    expect(vmm.extract_block(MISSING_BLOCK) is None, "missing block must be detected")

    # 3. unbalanced bracket -> error.
    expect(any("unbalanced" in e for e in vmm.check_block(vmm.extract_block(UNBALANCED))),
           "unbalanced bracket must be reported")

    # 4. dangling edge -> error.
    expect(any("empty endpoint" in e for e in vmm.check_block(vmm.extract_block(DANGLING_EDGE))),
           "dangling edge must be reported")

    # 5. missing header -> error.
    expect(any("flowchart" in e for e in vmm.check_block(vmm.extract_block(NO_HEADER))),
           "missing header must be reported")

    # 6. reversed delimiters (`A] ... B[`) have equal counts, so they need the stack.
    reversed_errors = vmm.check_block(vmm.extract_block(REVERSED))
    expect(any("closes no open delimiter" in e for e in reversed_errors),
           f"reversed delimiters must be reported: {reversed_errors}")

    # 7. crossed nesting (`([)]`) has equal counts too, and one fault is reported once.
    crossed_errors = vmm.check_block(vmm.extract_block(CROSSED))
    expect(len(crossed_errors) == 1 and "unbalanced nesting" in crossed_errors[0],
           f"crossed delimiters must be reported exactly once: {crossed_errors}")

    # 8. quoted and escaped label text never opens or closes a shape.
    quoted_errors = vmm.check_block(vmm.extract_block(QUOTED))
    expect(quoted_errors == [], f"quoted/escaped labels must stay valid: {quoted_errors}")

    # 9. legitimately nested shape pairs stay valid.
    nested_errors = vmm.check_block(vmm.extract_block(NESTED))
    expect(nested_errors == [], f"nested shape pairs must stay valid: {nested_errors}")

    print("PASS - mermaid validator detects valid, missing, unbalanced, reversed, crossed, dangling "
          "and no-header cases, and keeps quoted, escaped and nested labels valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
