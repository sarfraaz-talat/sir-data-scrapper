# Release Process

## Creating a Release

### 1. Update Version

Update version in:
- `pyproject.toml` (if publishing to PyPI)
- `docs/CHANGELOG.md` (move `[Unreleased]` to versioned section)

### 2. Commit Changes

```bash
git add .
git commit -m "Bump version to v1.0.0"
```

### 3. Create Tag and Push

```bash
# Create annotated tag
git tag -a v1.0.0 -m "Release v1.0.0"

# Push tag (triggers release workflow)
git push origin v1.0.0
```

### 4. GitHub Actions Will:

- ✅ Run CI tests
- ✅ Create GitHub Release
- ✅ (Optional) Publish to PyPI if configured

## Versioning

Follow [Semantic Versioning](https://semver.org/):
- **MAJOR** (1.0.0): Breaking changes
- **MINOR** (0.1.0): New features, backward compatible
- **PATCH** (0.0.1): Bug fixes, backward compatible

## PyPI Publishing (Optional)

If you want to publish to PyPI:

1. Create account on [PyPI](https://pypi.org)
2. Set up trusted publishing or API token
3. Add to GitHub Secrets:
   - `PYPI_API_TOKEN` (if using token)
4. Push a tag - workflow will auto-publish

## Manual Release

If you prefer manual releases:

1. Go to GitHub → Releases → Draft a new release
2. Choose tag (or create new)
3. Fill release notes from CHANGELOG.md
4. Publish release

