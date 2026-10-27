# Workflows

## Release build (`release.yml`)
Runs on pushes to `main` and on `v*` tag pushes. Runs the test suite, builds the
sdist/wheel, uploads them as workflow artifacts, and creates a GitHub release
with the artifacts attached (tag pushes only).

## Publish to PyPI (`pypi-publish.yml`)
Runs when a GitHub release is published (and via manual dispatch). Runs the
test suite, builds the sdist/wheel, and publishes them to PyPI using
[trusted publishing](https://docs.pypi.org/trusted-publishers/) (OIDC — no API
token stored in GitHub).

### One-time PyPI setup required
1. Create the project on https://pypi.org/manage/projects/ (name: `checkit`).
2. Go to the project's **Publishing** settings and add a GitHub trusted
   publisher:
   - Owner: `ezstyle42`
   - Repository: `checkit`
   - Workflow: `pypi-publish.yml`
   - Environment: `pypi`
3. Optionally create the `pypi` environment in the repo's
   **Settings → Environments** and add a required reviewer for extra safety.

After that, publishing a GitHub release (e.g. tag `v0.1.0`) publishes the
package to PyPI automatically.
