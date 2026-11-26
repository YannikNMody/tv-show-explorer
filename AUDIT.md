# Audit

Before publishing, this repository was audited for public release with an AI coding assistant (Claude), using the course audit prompt word for word. The audit is read-only: it prints no secret values, changes no files and runs no project code.

| Pass | Date | State audited |
|---|---|---|
| 1 | 24 Nov 2026 | `main` as finished after building (10 commits, full history) |
| 2 | 26 Nov 2026 | `submission-prep` after the fixes below |

Both passes ran on a fresh clone of the GitHub repository, so files that exist only on the author's computer were not visible to them.

## What was checked

- **Secrets and credentials:** every commit in the history, searched for API keys, tokens, passwords, private keys and common key formats.
- **Personal data:** commit metadata, local paths, the watch-tracker file, screenshots (including image metadata).
- **Files that should not be published:** local configuration, caches, virtual environments, generated files, files deleted from history.
- **`.gitignore`:** whether the rules cover the files above, and whether any tracked file is matched by them.
- **Reproducibility:** dependencies, setup instructions, configuration.
- **README:** the seven required topics and a screenshot.

## Pass 1 findings and what was done

No secrets, credentials or files that should be excluded were found, in the current files or in the history.

| # | Finding | Decision | Fixed in |
|---|---|---|---|
| C1 | The README predates the submission requirements: not organised by the required topics, no Learning section, AI assistance in one line, no screenshot. | **Fixed.** Restructured into the seven sections; screenshots and Learning added; AI use and other sources disclosed. | `6e1eff4`, `68fd1d9`, `9bfca22` |
| R1 | Setup did not mention that the app needs internet access or the optional `TRACKER_PATH` setting. | **Fixed** in the README. | `6e1eff4` |
| R2 | No defensive `.gitignore` rules for local secrets and editor folders (not used by this project). | **Fixed.** Added `.env`, `.env.*`, `.streamlit/secrets.toml`, `.vscode/`, `.idea/`. | `1559273` |
| R3 | Dependencies only set minimum versions. | **Fixed** with a "tested with" line, using the versions the GitHub Actions run installed. Splitting test-only dependencies was judged not worth changing the CI workflow. | `6e1eff4` |
| R4 | No LICENSE file. | **Decision, no file.** Coursework published for grading; the README states "no license, all rights reserved". | `6e1eff4` |
| — | The author's email address is in every commit and becomes public. | **Accepted, no action.** Not a secret; removing it would mean rewriting the history. | — |

## Pass 2 result

All changes since pass 1 were checked again: no secrets (every match was README text), no tracked file matched by `.gitignore`, no metadata in the screenshots, all seven README sections present. The only confirmed issue was that the README linked to this file before it existed. The test suite passed on GitHub Actions for the audited commit.

## Remaining limitations

- Files that exist only on the author's computer (`data/tracker.json`, `.venv/`) were not inspected; the `.gitignore` rules exclude them.
- The audits did not run the app; the automated tests and the author's manual check did.
- An audit that finds nothing does not prove the project is safe.
