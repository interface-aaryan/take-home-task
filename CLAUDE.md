# CLAUDE.md - Project Guidelines

## Build Commands
- Run application: `uv run regulation_task/main.py`
- Run web app: `uv run -m regulatory_compliance_processor.web.app`
- Run test imports: `uv run regulation_task/test_import.py`
- Run Flask test: `uv run regulation_task/test_flask.py`

## Code Style
- **Imports**: Standard lib → Third-party → Local modules (alphabetical within groups)
- **Types**: Type annotations for all parameters, return values using `typing` module
- **Docstrings**: Google-style docstrings with Args/Returns sections, triple double-quotes
- **Naming**: `snake_case` for variables/functions, `CamelCase` for classes, `UPPER_CASE` for constants
- **Error Handling**: Use specific exception types, log errors with detailed messages
- **Formatting**: 4-space indentation, ~100 max line length, blank lines between sections

## Development
- Use os env for environment variables
- Organize code by functionality in appropriate subdirectories
- Add `__init__.py` to make directories packages
- When adding modules, follow existing patterns in similar files