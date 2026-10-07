# Contributing

Thanks for taking the time to help. Bug reports, fixes, docs and new checks are all welcome.

## Reporting a bug

[Open an issue](https://github.com/NilkanthSuthar/toolproof/issues/new/choose) with:

- the toolproof version (`toolproof --version`), Python version and operating system
- the command you ran and your `toolproof.yaml`, trimmed to the smallest case that shows the problem
- the full output

If the problem only shows up with one MCP server, say which one and how to run it. For security problems, don't open an issue; follow the [security policy](https://github.com/NilkanthSuthar/toolproof/blob/main/SECURITY.md).

## Suggesting a feature

Open an issue describing the problem you want solved before writing code for anything large, so we can agree on the approach first.

## Development setup

```bash
git clone https://github.com/NilkanthSuthar/toolproof
cd toolproof
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev,docs]"
pre-commit install
```

## Checks

The same checks run in CI on Linux and Windows for every supported Python version:

```bash
ruff check .
ruff format --check .
mypy
coverage run -m pytest
coverage report               # fails under 90%
mkdocs build --strict         # the docs site
```

The tests start the example servers in `examples/` for real, over stdio and HTTP, so they take a couple of minutes. To run one file: `pytest tests/test_fuzz.py`.

## Making a change

1. Create a branch from `main`.
2. Make the change with tests. Bug fixes need a test that fails without the fix.
3. Update the docs in `docs/` if behaviour, options or output change.
4. Add a line under **Unreleased** in [CHANGELOG.md](https://github.com/NilkanthSuthar/toolproof/blob/main/CHANGELOG.md).
5. Open a pull request and fill in the template.

### Style

- Code is formatted with ruff and type-checked with mypy in strict mode.
- Keep it readable: clear names, short functions, docstrings on public functions, comments that explain *why*.
- Don't add a dependency without discussing it first.
- Public API is what `toolproof/__init__.py` exports, plus the CLI, the YAML format and the report formats. Changing any of it needs a changelog entry, and breaking it needs a deprecation first (see [Versioning](https://nilkanthsuthar.github.io/toolproof/about/versioning/)).

## Releasing

Maintainers only.

1. Move the **Unreleased** entries in `CHANGELOG.md` under a new version heading and update the compare links.
2. Bump `version` in `pyproject.toml` and `__version__` in `src/toolproof/__init__.py`.
3. Commit, then tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. The release workflow builds, checks and publishes to PyPI with trusted publishing.
5. Create the GitHub release from the changelog entry.

## Code of conduct

This project follows the [code of conduct](https://github.com/NilkanthSuthar/toolproof/blob/main/CODE_OF_CONDUCT.md). By taking part you agree to it.
