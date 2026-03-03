---
name: architect-review
description: "Software architecture review — separation of concerns, dependency direction, SOLID principles, and API design. Use when reviewing system design or major code changes."
version: "1.0.0"
---

# Architecture Review Principles

## Separation of Concerns
- Each module has a single, well-defined responsibility
- Business logic is separate from I/O (database, HTTP, filesystem)
- Configuration is separate from code
- No god classes or god functions

## Dependency Direction
- Dependencies point inward (toward domain/business logic)
- Outer layers (HTTP, DB) depend on inner layers (domain), never the reverse
- Use dependency injection to invert control
- Interfaces at boundaries, implementations behind them

## SOLID in Practice
- **S**ingle Responsibility: One reason to change per class/module
- **O**pen/Closed: Extend behavior without modifying existing code
- **L**iskov Substitution: Subtypes are substitutable for their base types
- **I**nterface Segregation: Small, focused interfaces over large ones
- **D**ependency Inversion: Depend on abstractions, not concretions

## API Design
- Consistent naming across endpoints
- Proper HTTP status codes (don't return 200 for errors)
- Validate input at the boundary, trust it inside
- Version your APIs when breaking changes are unavoidable
- Return structured errors with actionable messages

## Code Smells to Flag
- Circular imports → wrong module boundaries
- God class (> 300 lines, > 10 methods) → needs decomposition
- Feature envy (method uses another class's data more than its own) → move it
- Shotgun surgery (one change requires edits across 5+ files) → missing abstraction
- Long parameter lists (> 3 params) → introduce a config/params object

## Review Checklist
- [ ] Are module boundaries well-defined?
- [ ] Do dependencies flow in one direction?
- [ ] Is business logic testable without I/O?
- [ ] Are abstractions at the right level?
- [ ] Could a new team member understand this in 10 minutes?
