---
name: codebase-conventions
description: "Project-specific coding conventions for the demo workspace. Follow these patterns when implementing code in this project."
version: "1.0.0"
---

# Codebase Conventions

These are the specific conventions for this project. Follow them exactly.

## File Organization
- Application entry point: `app.py`
- Utility/helper functions: `utils.py`
- Tests mirror source: `tests/test_<module>.py`

## Naming
- Functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private: prefix with `_`

## Imports
- Standard library first, then third-party, then local
- One import per line
- Absolute imports only (no relative)

## Error Handling Pattern
```python
class AppError(Exception):
    """Base application error."""
    def __init__(self, message: str, code: str = "UNKNOWN") -> None:
        self.message = message
        self.code = code
        super().__init__(message)

class ValidationError(AppError):
    """Input validation failed."""
    def __init__(self, message: str) -> None:
        super().__init__(message, code="VALIDATION_ERROR")
```

## Function Pattern
```python
def process_item(item: dict[str, str]) -> Result:
    """Process a single item and return the result.

    Args:
        item: Dictionary containing 'name' and 'value' keys.

    Returns:
        Result object with processed data.

    Raises:
        ValidationError: If item is missing required keys.
    """
    _validate_item(item)
    return _transform(item)
```

## Test Pattern
```python
class TestProcessItem:
    """Tests for process_item function."""

    def test_valid_item_returns_result(self) -> None:
        item = {"name": "test", "value": "42"}
        result = process_item(item)
        assert result.name == "test"

    def test_missing_key_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="missing required key"):
            process_item({"name": "test"})
```
