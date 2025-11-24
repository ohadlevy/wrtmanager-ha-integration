# Release Automation Guide

This document explains how to use the automated release process for the WRT Manager Home Assistant Integration.

## How to Create a Release

### 1. Manual Trigger (Recommended)

1. Go to GitHub Actions in your repository
2. Click on "Release Automation" workflow
3. Click "Run workflow"
4. Choose your release type:
   - **Patch** (0.8.0 → 0.8.1): Bug fixes, small improvements
   - **Minor** (0.8.0 → 0.9.0): New features, backwards compatible
   - **Major** (0.8.0 → 1.0.0): Breaking changes
   - **Custom**: Specify exact version (e.g., 1.0.0-beta.1)

### 2. What Happens Automatically

The workflow will:

1. **Create a release branch** (`release/vX.Y.Z`)
2. **Update version numbers** in:
   - `pyproject.toml`
   - `custom_components/wrtmanager/manifest.json`
3. **Create a Pull Request** with the version bump
4. **Run all CI checks** (tests, linting, security scans)
5. **Wait for PR review and merge**

### 3. After PR Merge

Once you merge the release PR to `main`:

1. **Git tag** (`vX.Y.Z`) is created automatically
2. **GitHub Release** is published with auto-generated changelog
3. **Release notes** are created from commits since last release

## Release Checklist

Before merging the release PR:

- [ ] All CI checks pass
- [ ] Version numbers are correct in both files
- [ ] Changes look good for release
- [ ] Any manual testing completed

## Troubleshooting

### Version Mismatch Error
If you see version mismatch errors, the workflow ensures consistency between:
- `pyproject.toml` project version
- `manifest.json` integration version

### CI Failures
The release process requires all CI checks to pass:
- Tests
- Code quality (linting)
- Security scans
- Home Assistant validation

### Failed Release Creation
If GitHub release creation fails:
- Check the GitHub Actions logs
- Verify repository permissions
- Ensure the tag was created properly

## Manual Release (Emergency)

If automation fails, you can create a release manually:

```bash
# 1. Update version in both files
# 2. Commit and push to main
git add pyproject.toml custom_components/wrtmanager/manifest.json
git commit -m "Bump version to X.Y.Z"
git push origin main

# 3. Create and push tag
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z

# 4. Create GitHub release manually through web UI
```

## Version Strategy

This project follows [Semantic Versioning](https://semver.org/):

- **MAJOR**: Breaking changes to the integration API
- **MINOR**: New features, new device support, backwards compatible
- **PATCH**: Bug fixes, documentation updates, small improvements