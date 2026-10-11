# Template maintenance

Copier creates consumers from tagged Nebula releases and records non-secret answers plus the exact template commit in `.copier-answers.yml`. No post-render tasks run implicitly.

On a clean consumer checkout, `make template-update REF=vX.Y.Z` creates a chore branch and runs Copier update. Review its diff, run make setup/check, then open a PR. Without REF, Copier selects the latest compatible stable template tag. Conflicts stop the update; Copier merges against the recorded template version; no destructive recopy is used.

README, VERSION, and the existing changelog are preserved during adoption and upgrades. Shared tooling and workflow changes receive Copier's merge behavior. Existing project files outside the template are untouched. Add custom Makefile targets in Makefile.project and application checks in nebula.toml.

The template uses symlinks into the canonical tooling in this repository; Copier dereferences them into standalone files in consumers. Tests render from Git snapshots and exercise an upgrade with an independently customized consumer. Generated consumers have no runtime dependency on the source checkout.

To recover an update, inspect git status and discard only the changes created on its new branch. Never reset an unrelated dirty tree. Complete unresolved merges before committing.
