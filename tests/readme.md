# Testing Guide - Momentum Tracker

This directory contains the test suite to verify technical calculations, CrewAI agent configuration wiring, and string parser structures.

---

## Running Unit Tests

Unit tests are fast, completely stateless, and mock external API/LLM calls to run instantly without network/disk I/O or token expenditure.

To prevent module import errors (`ModuleNotFoundError`), you must set the `PYTHONPATH` environment variable to include the project directory before running `pytest`.

### 1. Windows PowerShell (Recommended)
```powershell
$env:PYTHONPATH=".;crew;app;momentum_tracker"
pytest tests/unit/ -v
```

### 2. Windows Command Prompt (CMD)
```cmd
set PYTHONPATH=.;crew;app;momentum_tracker
pytest tests/unit/ -v
```

### 3. macOS / Linux / Git Bash
```bash
export PYTHONPATH=".:crew:app:momentum_tracker"
pytest tests/unit/ -v
```

---

## Unit Test Coverage

- **[test_technical_indicators.py](./unit/test_technical_indicators.py)**: Stateless math verification of indicators (EMA, Wilder RSI, ROC, Composite ROC, CCI, MFI, Vivek Bajaj RS-N Ratio, Smoothed RS-MA, Simple interest cash).
- **[test_scheduler_and_crew.py](./unit/test_scheduler_and_crew.py)**: Validates text parsers (scan rows, picks, alerts) and mocks LLM config loading to ensure agents/tasks compile correctly under pydantic schemas.
- **[test_momentum_tool_unit.py](./unit/test_momentum_tool_unit.py)**: Validates Backbone tool parameter parsing, stock trend filters, metadata formatting, and validation error branches.

---

## Running Integration Tests (Slow, hits yfinance APIs)

*Note: Requires active API credentials and a warm cache.*
```bash
pytest tests/integration/ -v -s
```