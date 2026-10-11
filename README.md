# Nebula

An updateable, language-independent repository template: security hooks, GitHub protections, CI, changelog, releases, and documentation.

```sh
uvx copier copy --vcs-ref v0.1.2 gh:CafofoLabs/nebula my-project
cd my-project
make setup
make check
```

Existing consumers update with `make template-update REF=v0.1.1` on a clean checkout. Updates produce a branch for review and preserve project changes or report conflicts.

- [Development and module guide](docs/development.md)
- [Release workflow](docs/releases.md)
- [Template maintenance](docs/template.md)

Requires Git, Python 3.11+, uv, curl, and the GitHub CLI for remote operations. No infrastructure credentials are required.
