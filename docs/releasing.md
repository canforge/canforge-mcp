# Release process

## Versioning

canforge-mcp follows [Semantic Versioning](https://semver.org/). Pre-1.0 minor
releases may change MCP tool contracts.

- **Patch** — bug fixes with no tool-contract changes.
- **Minor** — new backwards-compatible features; before 1.0, may include
  breaking changes called out in the changelog.
- **Major** — breaking tool-contract changes. Requires a migration note in the
  changelog.

## Pre-release checklist

Before tagging a release:

- [ ] All CI checks pass on `main` (Python 3.11–3.14, ruff, mypy, coverage
  ≥ 90%, build, wheel contents, and console-script metadata).
- [ ] `CHANGELOG.md`: `[Unreleased]` converted to this version with the release
  date (see format below).
- [ ] Version bumped in `pyproject.toml`, `canforge_mcp/__init__.py`, and
  `tests/test_server.py`.
- [ ] Dependency ranges in `pyproject.toml` still match the capkit, dbckit, and
  MCP versions used by the release.
- [ ] The README tool list, examples, scope, and supported formats are accurate
  for the new version.
- [ ] `docs/tools.md` accurately describes every public tool, its bounds, return
  shape, and errors.

## Steps

Publishing is tag-driven: pushing a `v*` tag triggers
`.github/workflows/release.yml`, which builds the sdist and wheel and uploads
them to PyPI via [trusted publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC, GitHub environment `pypi`) — no API tokens are involved.

```bash
# Replace X.Y.Z with the release version in every step below.

# 1. Bump the version in pyproject.toml, canforge_mcp/__init__.py, and
#    tests/test_server.py.

# 2. Update CHANGELOG.md (see format below).

# 3. Commit the release.
git add pyproject.toml canforge_mcp/__init__.py tests/test_server.py CHANGELOG.md
git commit -m "chore: release X.Y.Z"
git push origin main

# 4. Tag — this triggers the release workflow.
git tag -a vX.Y.Z -m "Release X.Y.Z"
git push origin vX.Y.Z

# 5. Verify.
gh run watch
open https://pypi.org/project/canforge-mcp/
```

Include any release-specific documentation changed during the checklist in the
release commit.

## CHANGELOG format

```markdown
## [X.Y.Z] — YYYY-MM-DD

### Added

- ...

### Fixed

- ...

### Changed

- ...

### Removed

- ...
```

Keep one `## [Unreleased]` section at the top for in-progress work. Retitle it
to the dated version when releasing.
