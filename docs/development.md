# Development and module guide

## Setup and local safeguards

Run `make setup` after cloning. It installs the locked Python tooling and pre-commit, commit-msg, and pre-push hooks. The project Git identity comes from the non-secret `nebula.toml` configuration; setup refuses a conflicting existing local identity. Never use a corporate identity for personal projects.

Setup checks the exact Gitleaks version. If needed, it installs the pinned official release into ignored `.nebula/bin`, validates the archive against the release checksum manifest, and repeats safely. Hooks can be bypassed locally; CI repeats the controls.

Staged scanning uses Gitleaks against the index. Pre-push scans every commit reachable from the outgoing branch that is not reachable from a known origin ref, so adding then removing a secret does not evade it. CI scans full reachable history with redacted output. Secret detection blocks the operation; repair history and rotate any exposed credential separately. No scanner proves that every possible secret is absent.

Commit messages and PR titles use Conventional Commits. Branches use feature/, fix/, chore/, docs/, refactor/, test/, build/, ci/, perf/, or style/. Names containing codex and co-author trailers are rejected. The main branch is allowed only for CI and initial repository bootstrap; protected main prevents normal direct pushes.

## Checks and extension

`make check` runs Python lint/format checks, tooling tests, full-history secret scanning, documentation build, and the argument-list commands in `nebula.toml` under checks.commands. Commands are executed without a shell. The Python tooling lives in `.nebula`; application tooling remains independent. Add application targets in `Makefile.project` to preserve the shared Makefile during template updates.

Every module must document purpose, inputs/outputs, privileges, execution, repeated-run behavior, verification, and recovery. This page documents the shared repository modules; project-specific modules belong in their own docs pages.

## GitHub configuration

`make repo-plan` reads remote settings and reports drift. `make repo-apply` converges them, then reads back the result. Both use the authenticated gh session and project.repository in nebula.toml. Apply needs repository administration privileges; it does not read credential values.

The policy requires PRs, linear history, resolved discussions, blocked deletion/force pushes, administrator enforcement, and squash-only merges using the PR title. It preserves higher review counts, existing required checks, and push/dismissal restrictions. Checks become required only after a successful GitHub run exposes the expected names. Unsupported plan features are explicit errors. Never weaken a rule to finish a merge.

CI has read-only permissions and no infrastructure credentials. The stable required check is `nebula/checks`; metadata validation is also repeated inside that job. Workflow dispatch supports checks on automation-created PR branches, avoiding dependence on recursively triggered GITHUB_TOKEN events.

Verify with repo-plan, GitHub's protection read API, and a PR's checks. Recovery means restoring the previous declared settings through the same plan/apply interface, rather than deleting protection.

## Documentation

`make docs` builds Markdown through MyST/Sphinx with warnings as errors. README is the only root Markdown document; other Markdown belongs under docs. The hosted integration uses `.readthedocs.yaml` and the same frozen lock file. Read the Docs account linking is a one-time operator action. Enable SemVer tag activation and the stable alias in Read the Docs; a GitHub release alone is not proof that hosted documentation built.

Private consumers build docs locally and in GitHub CI. They do not get a public Read the Docs configuration or a hosted build without an explicit separate decision.
