# Contributing

Thanks for helping. This project cares about exactness and honesty more than breadth, so a few
rules matter more than usual.

## Set up

```bash
git clone https://github.com/Am1n1602/calcfinc && cd calcfinc
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"      # Windows: .venv\Scripts\python
.venv/bin/python -m pytest && .venv/bin/ruff check . && .venv/bin/mypy
```

All three must pass. CI runs them on Python 3.11, 3.12 and 3.13 on Linux, Windows and macOS.

## The rules

1. **No floats.** Numbers are `Decimal`, `int` or `str`. Anything that lets a float through to a
   result is a bug. Arithmetic goes through `calcfinc.num`.
2. **Missing is `None` with a reason.** Never zero, never an estimate. If a definition needs a
   substitute, make it a labelled fallback so the result announces it.
3. **The core stays generic.** No country, exchange, regulator or vendor names in `src/calcfinc`
   outside `adapters/` (a test enforces this). Country-specific inputs and ratios belong in an
   adapter (see `adapters/ind_as_xbrl/vocab.py`).
4. **Standard library only** at runtime. The network may be used only in
   `adapters/sec_companyfacts/fetch.py` (a test enforces this).
5. **No real data in the repository.** Test and example data is synthetic and written for the test.
   Do not commit exchange, SEC or vendor data or anything derived from it.
6. **Definitions need evidence.** A new or changed ratio comes with the source of its definition.
   If regulators or standards disagree, say so in the pull request and in the ratio's `label`, and
   pick one with a reason. Changing an existing definition bumps its `version`.

## Tests

Write a test when there is behaviour to pin down, with expected values **worked out by hand**
(show the arithmetic in a comment), never copied from the code's output. Fix the code, not the
test, when they disagree. A bug fix comes with a test that fails without it.

The documentation is tested too: every ```` ```python ```` block in `README.md` and
`docs/manual.md` is run, and `expr  # -> value` lines are checked. `docs/ratios.md` is generated;
after changing a ratio or metric run

```bash
python scripts/gen_ratio_docs.py
```

and commit the result (a test fails if it is stale).

## Adding a source adapter

An adapter reads one source's tags and conventions and produces `FinancialFact`s through the
loaders; it never changes how a ratio is computed. Test it on synthetic data in the repository and,
if you can, on real filings *outside* it, and record what was and was not verified in
`docs/adapters.md`.

## Style

`ruff` (line length 120) and `mypy --strict` are the style guide. Comments explain why, not what.

## Releasing (maintainers)

1. Set `__version__` in `src/calcfinc/__init__.py`, move the changelog entry from "Unreleased" to the
   new version, regenerate `docs/ratios.md`, and make sure CI is green on `main`.
2. One-time setup: on PyPI (and on TestPyPI) add a **trusted publisher** for owner `Am1n1602`,
   repository `calcfinc`, workflow `release.yml`, environment `pypi` (`testpypi` on TestPyPI), and create
   those two environments in the repository settings. No API token is ever stored.
3. Dry run: Actions, "release", **Run workflow** publishes the build to TestPyPI. Install it with
   `pip install --index-url https://test.pypi.org/simple/ --no-deps calcfinc` and try it.
4. Release: `git tag v0.1.0 && git push origin v0.1.0`. The workflow refuses to publish if the tag
   and `__version__` disagree.

## Pull requests

Keep one concern per PR, update `CHANGELOG.md` for anything a user would notice, and describe
how you checked it. By contributing you agree your work is released under the MIT licence.
