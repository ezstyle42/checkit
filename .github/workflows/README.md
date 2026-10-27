# Workflows

## Release build (`release.yml`)
Runs on pushes to `main` and on `v*` tag pushes. It:

1. **test** — installs the package with test extras and runs the pytest suite,
   then builds the sdist/wheel.
2. **build-gui** — a matrix job over `ubuntu-latest`, `windows-latest` and
   `macos-latest` that builds the **self-contained GUI application** with
   PyInstaller (`packaging/checkit.spec`) and packages it:
   - Linux: `checkit-linux-x64.tar.gz` (onefile binary)
   - Windows: `checkit-windows-x64.zip` (onefile `checkit.exe`)
   - macOS: `checkit-macos.zip` (`checkit.app` bundle)
3. **release** (tag pushes only) — downloads all artifacts and creates a
   GitHub release with the sdist/wheel and the three GUI apps attached.

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
