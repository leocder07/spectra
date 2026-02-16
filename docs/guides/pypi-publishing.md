# Publishing Spectra to PyPI

Step-by-step guide to publish `spectra-cli` to the Python Package Index.

---

## Prerequisites

Install the build and upload tools:

```bash
pip install build twine
```

Verify they are available:

```bash
python -m build --version
twine --version
```

---

## 1. Create a PyPI Account

1. Go to [https://pypi.org/account/register/](https://pypi.org/account/register/) and create an account.
2. Enable two-factor authentication (required for new accounts).
3. Go to [https://pypi.org/manage/account/token/](https://pypi.org/manage/account/token/) and create an API token.
   - Scope: "Entire account" for first upload, then restrict to `spectra-cli` after.
   - Save the token (starts with `pypi-`) -- you only see it once.

For TestPyPI (recommended for first-time testing):

1. Create a separate account at [https://test.pypi.org/account/register/](https://test.pypi.org/account/register/).
2. Create an API token at [https://test.pypi.org/manage/account/token/](https://test.pypi.org/manage/account/token/).

---

## 2. Build the Package

From the repository root:

```bash
# Clean previous builds
rm -rf dist/ build/ src/*.egg-info

# Build source distribution and wheel
python -m build
```

This produces two files in `dist/`:

```
dist/
  spectra_cli-0.1.0.tar.gz      # Source distribution
  spectra_cli-0.1.0-py3-none-any.whl  # Wheel (binary)
```

Verify the build:

```bash
# Check the package metadata
twine check dist/*
```

---

## 3. Test Upload (TestPyPI)

Upload to TestPyPI first to verify everything works:

```bash
twine upload --repository testpypi dist/*
```

You will be prompted for credentials:

- **Username:** `__token__`
- **Password:** your TestPyPI API token (the full `pypi-...` string)

Verify the test upload:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ spectra-cli
spectra --help
```

> The `--extra-index-url` flag pulls real dependencies from production PyPI since
> TestPyPI does not host all packages.

---

## 4. Production Upload

Once the test upload succeeds:

```bash
twine upload dist/*
```

Credentials:

- **Username:** `__token__`
- **Password:** your production PyPI API token

---

## 5. Verify the Production Install

```bash
pip install spectra-cli
spectra --help
spectra --version
```

The package page will be live at [https://pypi.org/project/spectra-cli/](https://pypi.org/project/spectra-cli/).

---

## 6. Automate with GitHub Actions

The repository includes a GitHub Actions workflow at `.github/workflows/publish.yml` that automatically publishes to PyPI when you create a release tag.

### How it works

1. Push a version tag:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

2. Or create a release in the GitHub UI:
   - Go to **Releases** > **Draft a new release**
   - Create tag `v0.1.0`
   - Fill in release notes
   - Click **Publish release**

3. The workflow triggers automatically, builds the package, and publishes to PyPI using trusted publishing (OIDC -- no API token secrets needed).

### Setting up Trusted Publishing (OIDC)

Trusted publishing eliminates the need for API token secrets. Set it up once:

1. Go to [https://pypi.org/manage/project/spectra-cli/settings/publishing/](https://pypi.org/manage/project/spectra-cli/settings/publishing/)
2. Add a new publisher:
   - **Owner:** `leocder07`
   - **Repository:** `spectra`
   - **Workflow name:** `publish.yml`
   - **Environment:** `pypi`
3. Click **Add**

> **Note:** For the first publish you need to create the project on PyPI manually
> (via `twine upload`) before you can configure trusted publishing. After that,
> the GitHub Action handles everything.

### The Workflow YAML

```yaml
# .github/workflows/publish.yml
name: Publish to PyPI

on:
  push:
    tags:
      - "v*"

permissions:
  contents: read
  id-token: write  # Required for OIDC trusted publishing

jobs:
  build:
    name: Build distribution
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install build tools
        run: pip install build

      - name: Build package
        run: python -m build

      - name: Upload build artifacts
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish:
    name: Publish to PyPI
    runs-on: ubuntu-latest
    needs: build
    environment:
      name: pypi
      url: https://pypi.org/project/spectra-cli/
    steps:
      - name: Download build artifacts
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

---

## Version Bump Checklist

Before each release:

1. Update `version` in `pyproject.toml`
2. Update `__version__` in `src/spectra/__init__.py`
3. Update the version string in `src/spectra/adapters/cli_controller.py` (`_version_callback`)
4. Commit and push
5. Create and push the tag: `git tag v0.X.Y && git push origin v0.X.Y`
6. The GitHub Action handles the rest

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `twine check` fails | Fix metadata warnings in `pyproject.toml` |
| Name already taken on PyPI | Choose a different `name` in `pyproject.toml` |
| 403 on upload | Check your API token scope and project ownership |
| Missing dependencies on install | Verify `dependencies` list in `pyproject.toml` |
| `spectra` command not found | Check `[project.scripts]` entry points and reinstall |
