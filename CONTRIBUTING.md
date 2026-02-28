# Contributing to ArchCode Terminal CLI

Thank you for your interest in contributing to ArchCode Terminal CLI. This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Style Guidelines](#style-guidelines)
- [Testing](#testing)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Pull Request Process](#pull-request-process)
- [Community](#community)

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/Archimyst.git
   cd Archimyst/backend/archcode-terminal
   ```
3. **Create a branch** for your contribution:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

### Prerequisites

- Python 3.10 or higher
- pip package manager
- ripgrep (rg) installed on your system
- Git

### Environment Setup

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -r requirements-dev.txt
```

### Running Locally

```bash
# Run the CLI locally
python -m archcode-cli

# Or use the shell script
./archcode.sh
```

## How to Contribute

### Reporting Bugs

Before creating a bug report, please:

1. Check the [existing issues](https://github.com/hritvikgupta/Archimyst/issues) to avoid duplicates
2. Use the latest version to verify the bug still exists
3. Collect relevant information about the bug

When submitting a bug report, include:

- **Clear title and description**
- **Steps to reproduce** the issue
- **Expected behavior** vs actual behavior
- **Environment details** (OS, Python version, CLI version)
- **Screenshots or logs** if applicable
- **Code samples** that demonstrate the issue

### Suggesting Features

Feature requests are welcome. Please:

1. Check if the feature has already been suggested
2. Provide a clear use case and justification
3. Describe how it would benefit users
4. Consider implementation complexity

### Contributing Code

#### Areas Where Contributions Are Welcome

- **Bug fixes**: Address issues in existing functionality
- **New features**: Add capabilities that enhance the CLI
- **Documentation**: Improve README, docstrings, or guides
- **Tests**: Increase test coverage
- **Performance**: Optimize existing code
- **Skills**: Add new MCP skills or integrations

#### Areas That Require Discussion First

- Breaking changes to existing APIs
- Major architectural changes
- Changes to core indexing or search algorithms
- New AI provider integrations

## Style Guidelines

### Python Code Style

We follow PEP 8 with some modifications:

- **Line length**: 100 characters maximum
- **Imports**: Grouped by standard library, third-party, local
- **Docstrings**: Google-style docstrings for all public functions
- **Type hints**: Use type hints for function signatures
- **Naming**: 
  - `snake_case` for functions and variables
  - `PascalCase` for classes
  - `UPPER_CASE` for constants

### Example

```python
def process_symbol(symbol: str, codebase_path: Path) -> Dict[str, Any]:
    """Process a code symbol and return its metadata.

    Args:
        symbol: The symbol name to process.
        codebase_path: Root path of the codebase.

    Returns:
        Dictionary containing symbol metadata including
        file location, type, and references.

    Raises:
        SymbolNotFoundError: If the symbol doesn't exist in the codebase.
    """
    # Implementation here
    pass
```

### Code Organization

```
archcode-cli/
├── app/
│   ├── core/           # Core business logic
│   ├── runtime/        # CLI runtime and orchestration
│   ├── skills/         # MCP skill implementations
│   └── utils/          # Utility functions
├── core/               # Legacy core modules
├── tests/              # Test suite
└── docs/               # Documentation
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=archcode-cli

# Run specific test file
pytest tests/test_search.py

# Run with verbose output
pytest -v
```

### Writing Tests

- Use pytest for all tests
- Name test files with `test_` prefix
- Name test functions with `test_` prefix
- Use fixtures for common setup
- Mock external dependencies

```python
import pytest
from app.core.search import SymbolSearcher

def test_symbol_search_finds_class():
    searcher = SymbolSearcher()
    results = searcher.find("UserService")
    assert len(results) > 0
    assert results[0].type == "class"
```

### Test Coverage

Aim for at least 80% coverage for new code. Critical paths should have 100% coverage.

## Commit Message Guidelines

We follow conventional commits:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation changes
- **style**: Code style changes (formatting, no logic change)
- **refactor**: Code refactoring
- **test**: Adding or updating tests
- **chore**: Maintenance tasks

### Examples

```
feat(search): add fuzzy matching to symbol search

Implement Levenshtein distance algorithm for matching
misspelled symbol names. Improves UX when users make
typos in their queries.

Closes #123
```

```
fix(indexer): handle unicode files in tree-sitter parser

Previously, files with non-ASCII characters would cause
encoding errors during indexing. Now properly handle
UTF-8 encoded source files.

Fixes #456
```

## Pull Request Process

1. **Ensure all tests pass** before submitting
2. **Update documentation** if needed (README, docstrings, etc.)
3. **Add tests** for new functionality
4. **Update CHANGELOG.md** with your changes
5. **Link related issues** in the PR description
6. **Request review** from maintainers

### PR Checklist

- [ ] Code follows style guidelines
- [ ] Tests added/updated and passing
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] Commit messages follow conventions
- [ ] No breaking changes without discussion
- [ ] PR description explains the change

### Review Process

- All PRs require at least one review from a maintainer
- Address review comments promptly
- Squash commits if requested
- Be open to feedback and constructive criticism

## Community

### Communication Channels

- **GitHub Issues**: Bug reports and feature requests
- **GitHub Discussions**: General questions and community chat
- **Documentation**: [archimyst.com/documentation](https://www.archimyst.com/documentation)

### Recognition

Contributors will be:
- Listed in the README contributors section
- Mentioned in release notes for significant contributions
- Given credit in commit messages for their work

## Educational Use

This project is available for educational purposes. When using this codebase for:

- **Learning**: Study the code, architecture, and patterns
- **Teaching**: Use as examples in courses or workshops
- **Research**: Academic papers or thesis work

Please provide attribution to the original project.

## License

By contributing, you agree that your contributions will be licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

**Thank you for contributing to ArchCode Terminal CLI!**
