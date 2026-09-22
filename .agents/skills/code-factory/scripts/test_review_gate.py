#!/usr/bin/env python3
"""
Deterministic self-test for the canonical review-gate policy (zero LLM tokens).

The review gate is stated as ONE marked block:

    <!-- review-gate-policy: begin -->
    ...policy...
    <!-- review-gate-policy: end -->

copied VERBATIM into five documents: `references/code-review.md`,
`agents/code-factory.md`, `skills/code-factory/SKILL.md`, `AGENTS.md` and
`.agents/README.md`. Five prose copies drift, one machine-checked copy does not: this test reads
the marked block out of every file and fails when a file is missing it, carries it twice, or
holds a block that differs by even one byte from the others. It also asserts that the block still
carries the policy's key markers (`unverified_review`, `conditional pass`, `hitl`, `auto`), so
the gate cannot be watered down by rewriting all five documents at once.

The comparison lives in `find_discrepancies()`, which takes plain paths, so the negative
self-check can tamper with throwaway copies in a temp directory and prove the drift IS detected
without ever touching the real documents.

Usage:
  python3 test_review_gate.py [path ...]   # default: the five canonical documents
  Paths are resolved against the repository root when they are relative.

Exit code 0 = every checked file carries the identical canonical block, 1 = a discrepancy.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

# scripts/ -> code-factory/ -> skills/ -> .agents/ -> repository root
ROOT = pathlib.Path(__file__).resolve().parents[4]

DEFAULT_FILES = (
    "AGENTS.md",
    ".agents/README.md",
    ".agents/agents/code-factory.md",
    ".agents/skills/code-factory/SKILL.md",
    ".agents/skills/code-factory/references/code-review.md",
)

BEGIN = "<!-- review-gate-policy: begin -->"
END = "<!-- review-gate-policy: end -->"
REQUIRED_MARKERS = ("unverified_review", "conditional pass", "hitl", "auto")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def extract_block(text: str) -> str | None:
    """Inner text of the single marked review-gate block; None when it is absent/duplicated."""
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        return None
    start = text.index(BEGIN) + len(BEGIN)
    end = text.index(END)
    if end <= start:
        return None
    block = text[start:end].strip()
    return block or None


def read_block(path) -> str | None:
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    return extract_block(text)


def find_discrepancies(paths) -> tuple[str | None, list[str]]:
    """Compare the marked blocks of `paths`; return (canonical block, list of problems)."""
    problems: list[str] = []
    blocks: dict[str, str] = {}
    for path in paths:
        block = read_block(path)
        if block is None:
            problems.append(f"{path}: review-gate block is missing, duplicated or unreadable")
        else:
            blocks[str(path)] = block
    if not blocks:
        return None, problems
    ref_path, canonical = next(iter(blocks.items()))
    for path, block in blocks.items():
        if block != canonical:
            problems.append(f"{path}: review-gate block differs from {ref_path}")
    for marker in REQUIRED_MARKERS:
        if marker not in canonical:
            problems.append(f"{ref_path}: canonical block lost the marker {marker!r}")
    return canonical, problems


def _fixture(path: pathlib.Path, block: str, extra: str = "") -> pathlib.Path:
    path.write_text(f"# doc\n\n{BEGIN}\n{block}\n{END}\n{extra}", encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    paths = [pathlib.Path(p) for p in argv] or [ROOT / name for name in DEFAULT_FILES]
    paths = [p if p.is_absolute() else ROOT / p for p in paths]

    # 1. every document carries the block exactly once and all blocks are byte-identical.
    canonical, problems = find_discrepancies(paths)
    expect(canonical is not None, f"no file carries the review-gate block: {problems}")
    expect(not problems, "review-gate block is not identical everywhere: " + "; ".join(problems))

    # 2. the block still states the policy's key markers.
    for marker in REQUIRED_MARKERS:
        expect(marker in canonical, f"canonical review-gate block must mention {marker!r}")

    # 3. extraction rejects the degenerate shapes.
    expect(extract_block("no markers here") is None, "a file without markers must yield no block")
    expect(extract_block(f"{BEGIN}\nonly the begin marker\n") is None,
           "a lone begin marker must be rejected")
    expect(extract_block(f"{BEGIN}\n{END}\n{BEGIN}\nx\n{END}\n") is None,
           "a duplicated block must be rejected")
    expect(extract_block(f"{END}\nx\n{BEGIN}\n") is None,
           "markers in the wrong order must be rejected")
    expect(extract_block(f"{BEGIN}\n  padded  \n{END}\n") == "padded",
           "the block must be compared stripped")

    # 4. negative self-check on throwaway copies: drift and deletion ARE detected.
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = pathlib.Path(tmp)
        good = [_fixture(tmpdir / f"copy{i}.md", canonical) for i in range(2)]
        _, clean = find_discrepancies(good)
        expect(clean == [], f"identical fixture copies must not be reported: {clean}")

        tampered = _fixture(tmpdir / "tampered.md", canonical + " extra clause")
        _, drift = find_discrepancies([*good, tampered])
        expect(any("differs" in p for p in drift),
               f"a tampered copy must be reported as a discrepancy: {drift}")

        weakened = _fixture(tmpdir / "weakened.md",
                            canonical.replace(REQUIRED_MARKERS[0], "TODO"))
        _, weakened_problems = find_discrepancies([*good, weakened])
        expect(any("differs" in p for p in weakened_problems),
               f"a copy with a dropped policy marker must be reported: {weakened_problems}")

        empty = (tmpdir / "empty.md")
        empty.write_text("no review-gate block at all\n", encoding="utf-8")
        _, missing = find_discrepancies([*good, empty])
        expect(any("missing" in p for p in missing),
               f"a file without the block must be reported as missing: {missing}")

    print(f"PASS - canonical review-gate block is identical in {len(paths)} documents "
          f"({len(canonical)} chars) and drift is detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
