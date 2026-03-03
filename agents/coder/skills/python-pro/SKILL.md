---
name: python-pro
description: "Modern Python 3.12+ patterns, type hints, dataclasses, async, testing with pytest, and modern tooling (ruff, mypy, uv). Use when writing or reviewing Python code."
version: "1.0.0"
---

# Python Pro — Modern Python Patterns

## Type Hints
- Every function signature gets type hints
- Use `str | None` instead of `Optional[str]` (Python 3.10+)
- Use `list[str]` instead of `List[str]` (Python 3.9+)
- Use `Self` for fluent APIs (Python 3.11+)

## Dataclasses & Pydantic
- Prefer `@dataclass` for plain data containers
- Use `pydantic.BaseModel` when you need validation
- Use `field(default_factory=list)` not mutable defaults

```python
from dataclasses import dataclass, field

@dataclass
class ServerConfig:
    host: str = "localhost"
    port: int = 8080
    tags: list[str] = field(default_factory=list)
```

## Error Handling
- Custom exceptions inherit from a project-specific base
- Use `raise ValueError("msg") from original` for chained exceptions
- Context managers for resource cleanup

```python
class AppError(Exception):
    """Base exception for the application."""

class NotFoundError(AppError):
    """Raised when a resource is not found."""
```

## Modern Idioms
- f-strings for formatting (not `.format()` or `%`)
- `pathlib.Path` instead of `os.path`
- Walrus operator `:=` when it improves readability
- `match/case` for structural pattern matching
- Generator expressions for lazy evaluation

## Testing with pytest
- Use fixtures for setup/teardown
- Parametrize for multiple test cases
- Use `tmp_path` fixture for file tests
- Mark slow tests with `@pytest.mark.slow`

```python
import pytest

@pytest.fixture
def sample_config():
    return ServerConfig(host="test", port=9090)

@pytest.mark.parametrize("port,valid", [(80, True), (-1, False), (65536, False)])
def test_port_validation(port: int, valid: bool) -> None:
    if valid:
        assert validate_port(port)
    else:
        with pytest.raises(ValueError):
            validate_port(port)
```

## Project Structure
```
project/
├── pyproject.toml      # Single config source
├── src/project/         # Source code
│   ├── __init__.py
│   └── module.py
├── tests/               # Mirror source structure
│   ├── conftest.py
│   └── test_module.py
└── README.md
```
