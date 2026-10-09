"""The documentation is tested: every ```python block in the README and the manual is run, in order,
in a fresh interpreter inside an empty directory, and a statement such as

    roe.value        # -> 25

is checked against the value it prints. ```csv NAME blocks are written to NAME first; a block whose
fence says `python skip` is shown but not run. docs/ratios.md must match the registries.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```[ \t]*$", re.S | re.M)
ARROW = re.compile(r"#\s*->\s*(.+?)\s*$")

PRELUDE = '''
from decimal import Decimal as _D


def _check(value, expected, where):
    ok = repr(value) == expected or str(value) == expected
    if not ok and not isinstance(value, str):
        try:
            ok = value == _D(expected)
        except Exception:
            pass
    assert ok, f"{where}: the documentation says {expected}, the code gives {value!r}"

'''


def blocks(path: Path) -> tuple[dict[str, str], str]:
    """(files to create, the program) for one markdown file."""
    files: dict[str, str] = {}
    code: list[str] = []
    text = path.read_text(encoding="utf-8")
    for info, body in FENCE.findall(text):
        parts = info.split()
        if not parts:
            continue
        if parts[0] == "csv" and len(parts) == 2:
            files[parts[1]] = body
        elif parts == ["python"]:
            code.append(instrument(body, path.name))
    return files, PRELUDE + "\n".join(code)


def instrument(source: str, name: str) -> str:
    """Turn `expr  # -> expected` lines into checks."""
    lines = source.splitlines()
    out: list[str] = []
    last = 0
    for node in ast.parse(source).body:
        end = node.end_lineno or node.lineno
        out += lines[last:node.lineno - 1]
        segment = lines[node.lineno - 1:end]
        m = ARROW.search(lines[end - 1]) if isinstance(node, ast.Expr) else None
        if m:
            expr = ast.get_source_segment(source, node.value) or ""
            out.append(f"_check({expr}, {m.group(1)!r}, '{name}:{node.lineno}')")
        else:
            out += segment
        last = end
    out += lines[last:]
    return "\n".join(out) + "\n"


def run_markdown(testcase: unittest.TestCase, relative: str) -> None:
    files, program = blocks(ROOT / relative)
    testcase.assertTrue(program.strip().splitlines()[-1:], f"{relative}: no runnable examples found")
    with tempfile.TemporaryDirectory() as d:
        for name, body in files.items():
            (Path(d) / name).write_text(body, encoding="utf-8")
        (Path(d) / "doc_example.py").write_text(program, encoding="utf-8")
        done = subprocess.run([sys.executable, "doc_example.py"], cwd=d, capture_output=True, text=True, timeout=120)
    if done.returncode:
        testcase.fail(f"{relative}: an example failed\n{textwrap.indent(done.stderr[-1500:], '    ')}")


class TestDocumentation(unittest.TestCase):
    def test_readme_examples_run_and_print_what_the_text_says(self):
        run_markdown(self, "README.md")

    def test_manual_examples_run_and_print_what_the_text_says(self):
        run_markdown(self, "docs/manual.md")

    def test_the_ratio_reference_matches_the_registries(self):
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_ratio_docs.py"), "--check"],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)


class TestDocTooling(unittest.TestCase):
    def test_arrow_comments_become_checks_and_other_lines_are_untouched(self):
        out = instrument("x = 5\nx + 1   # -> 6\nprint(x)\n", "t")
        self.assertIn("_check(x + 1, '6', 't:2')", out)
        self.assertIn("x = 5", out)
        self.assertIn("print(x)", out)

    def test_a_wrong_claim_in_the_docs_is_caught(self):
        with tempfile.TemporaryDirectory() as d:
            program = PRELUDE + instrument("x = 5\nx + 1   # -> 7\n", "t")
            Path(d, "p.py").write_text(program, encoding="utf-8")
            done = subprocess.run([sys.executable, "p.py"], cwd=d, capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("the documentation says 7", done.stderr)


if __name__ == "__main__":
    unittest.main()
