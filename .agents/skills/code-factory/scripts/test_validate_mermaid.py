#!/usr/bin/env python3
"""
Deterministic self-test for `validate_mermaid.py` (zero LLM tokens).

Verifies the structural Mermaid checker: valid flowcharts pass; missing block, unbalanced
brackets and dangling edges fail.

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

    print("PASS - mermaid validator detects valid, missing, unbalanced, dangling and no-header cases.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
