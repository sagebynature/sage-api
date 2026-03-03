---
name: clean-code
description: "Applies principles from Robert C. Martin's 'Clean Code' — naming, functions, error handling, formatting, and test discipline. Use when writing, reviewing, or refactoring code."
version: "1.0.0"
---

# Clean Code Principles

Apply these principles when writing or reviewing code.

## Naming
- Use intention-revealing names: `elapsed_time_in_days` not `d`
- Class names are nouns: `UserRepository`, `PaymentProcessor`
- Function names are verbs: `calculate_total`, `validate_input`
- Avoid disinformation: don't use `account_list` if it's a dict

## Functions
- **Small.** Under 20 lines. If it's longer, extract.
- **Do one thing.** A function that does two things is two functions.
- **One level of abstraction.** Don't mix business logic with string parsing.
- **Few arguments.** 0-2 is ideal. 3+ needs strong justification. Use a dataclass.
- **No side effects.** `validate_password()` should not also log the user in.

## Error Handling
- Use exceptions, not return codes
- Write try-catch-finally first to define scope
- Don't return None — raise or use Optional with explicit checks
- Don't pass None — it forces null checks everywhere

## Comments
- Don't comment bad code — rewrite it
- Code should be self-documenting
- Good comments: legal, TODO, clarification of external APIs
- Bad comments: redundant, mumbling, position markers, commented-out code

## Tests
- F.I.R.S.T.: Fast, Independent, Repeatable, Self-Validating, Timely
- One assertion per test (or one concept)
- Test names describe the scenario: `test_expired_token_returns_401`

## Formatting
- Newspaper metaphor: high-level at top, details at bottom
- Related code stays close together
- Variables declared near their usage
