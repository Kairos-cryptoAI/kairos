# Contributing to Kairos

## Conventions
- **Conventional Commits** (`feat:`, `fix:`, `chore:`, `test:`, `docs:`, `refactor:`, `ci:`).
- Python 3.11+, type-hinted, `ruff` + `mypy` clean, `pytest` green.
- Every layer depends on `kairos-core` for contracts — never redefine a message locally.
- Deterministic layers (Router, Risk, Execution) must keep ≥1 test per rule.

## Local dev
```bash
pip install -e ../kairos-core        # shared lib first
pip install -e ".[dev]"
make test
```

## Safety
- Execution defaults to `DRY_RUN=true`. Never commit secrets; use `.env` (git-ignored).
- Risk rules and the circuit breaker are not optional — do not bypass them.
