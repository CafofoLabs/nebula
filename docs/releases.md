# Releases and changelog

Merged PR titles are preserved as Conventional Commit squash subjects. git-cliff, reused from the Jarvis approach, derives SemVer and changelog groups. Release/changelog bookkeeping commits are excluded. PR numbers become links to their project repository.

`make release-plan` previews the next version and notes without writing. `make release BUMP=auto` prepares a release branch, commits VERSION and docs/CHANGELOG.md, opens a PR, waits for checks, and merges through normal protection. BUMP can be patch, minor, or major when explicitly requested. No tag is created on the temporary branch.

The publication workflow runs after VERSION reaches main. It verifies required files and checks, creates an immutable tag on that commit, and publishes identical release notes. Rerunning publication validates the existing tag target and fills in only missing publication steps. A tag pointing at a different commit is an error. A release never deploys infrastructure.

The main-history changelog workflow prepares one changelog PR after accepted changes. Bot-created PRs explicitly dispatch the read-only CI workflow. The repository must allow GitHub Actions to create PRs; repo-apply configures this when supported. The workflow never pushes directly to main and never bypasses protection. It does not automatically merge changelog PRs.

An operator can use the GitHub Actions release publication workflow's manual dispatch to retry publication on a validated main commit. `make release` skips an already published unchanged release. Do not move or delete release tags to recover from a failed job.

Read the Docs builds activated tags via its repository webhook. Publication and hosted documentation status are separate; verify the tag's successful hosted build before claiming its documentation is published. Missing account linking does not block local documentation checks.
