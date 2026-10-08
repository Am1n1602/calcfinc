# calcfinc

Turn periodic financial statements for any entity (company, SME, business unit, project) into
auditable metrics: ratios, growth, CAGR, valuation, margin decomposition, segment attribution.

Every result carries its value, unit, formula, the exact input facts, and a plain-language
limitation when it cannot be computed. A missing input yields `None` plus a reason, never zero
and never an estimate.

Zero runtime dependencies. Python >= 3.11.

> **Status: pre-alpha, under construction.** No public API yet.

Results are calculations, not investment advice.

## Development

```
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m pytest
```

## Licence

MIT
