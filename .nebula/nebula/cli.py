"""Small repository operations; credentials stay in gh's existing secure session."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
GITLEAKS_VERSION = "8.30.1"
CHECKS = ["nebula/checks"]
TITLE = re.compile(
    r"^(feat|fix|chore|docs|refactor|test|build|ci|perf|style|revert)(\([\w./-]+\))?!?: \S.+$"
)
BRANCH = re.compile(
    r"^(feature|fix|chore|docs|refactor|test|build|ci|perf|style)/[A-Za-z0-9][A-Za-z0-9._/-]*$"
)


def run(*args, capture=False, data=None, env=None):
    result = subprocess.run(
        [str(a) for a in args],
        check=True,
        text=True,
        input=data,
        stdout=subprocess.PIPE if capture else None,
        env=env,
    )
    return result.stdout.strip() if capture else ""


def git(*args):
    return run("git", *args, capture=True)


def config():
    value = tomllib.loads(Path("nebula.toml").read_text())
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", value["project"]["repository"]):
        raise ValueError("repository must be owner/repository")
    return value


def api(path, method="GET", data=None):
    args = ["gh", "api", path, "--method", method]
    if data is not None:
        args += ["--input", "-"]
    raw = run(*args, capture=True, data=json.dumps(data) if data is not None else None)
    return json.loads(raw) if raw else None


def validate_message(text):
    if not text.strip() or not TITLE.fullmatch(text.splitlines()[0]):
        raise ValueError("Use a Conventional Commit title, for example feat(module): add resource")
    if re.search(r"(?im)^co-authored-by:", text):
        raise ValueError("Co-author trailers are not allowed")


def validate_branch(name, allow_main=False):
    if allow_main and name == "main":
        return
    if "codex" in name.lower() or not BRANCH.fullmatch(name):
        raise ValueError("Use a feature/, fix/, chore/, docs/, or other documented branch prefix")


def gitleaks():
    local = TOOLS / "bin/gitleaks"
    candidate = str(local) if local.exists() else shutil.which("gitleaks")
    if candidate and run(candidate, "version", capture=True) == GITLEAKS_VERSION:
        return candidate
    system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64"}.get(platform.machine())
    if not system or not machine:
        raise ValueError("Install the pinned Gitleaks release for this platform manually")
    asset = f"gitleaks_{GITLEAKS_VERSION}_{system}_{machine}.tar.gz"
    base = f"https://github.com/gitleaks/gitleaks/releases/download/v{GITLEAKS_VERSION}"
    with tempfile.TemporaryDirectory(prefix="nebula-gitleaks-") as directory:
        folder = Path(directory)
        for name in [asset, f"gitleaks_{GITLEAKS_VERSION}_checksums.txt"]:
            run(
                "curl",
                "--proto",
                "=https",
                "--tlsv1.2",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--output",
                folder / name,
                f"{base}/{name}",
            )
        entries = (folder / f"gitleaks_{GITLEAKS_VERSION}_checksums.txt").read_text().splitlines()
        expected = next(line.split()[0] for line in entries if line.split()[-1] == asset)
        if hashlib.sha256((folder / asset).read_bytes()).hexdigest() != expected:
            raise ValueError("Gitleaks checksum mismatch")
        local.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(folder / asset) as archive:
            member = archive.getmember("gitleaks")
            with archive.extractfile(member) as source:
                local.write_bytes(source.read())
        local.chmod(0o755)
    if run(local, "version", capture=True) != GITLEAKS_VERSION:
        raise ValueError("Unexpected Gitleaks binary version")
    return str(local)


def secrets(mode):
    scanner = gitleaks()
    common = ["--redact", "--no-banner", "--ignore-gitleaks-allow", "--config", ".gitleaks.toml"]
    if mode == "staged":
        run(scanner, "git", "--pre-commit", "--staged", *common)
    elif mode == "outgoing":
        validate_branch(git("branch", "--show-current"))
        # Scan unpublished reachable commits, including secrets removed in later commits.
        run(scanner, "git", "--log-opts=HEAD --not --remotes=origin", *common)
    else:
        run(scanner, "git", "--log-opts=--all", *common)
        # Scan only Git-visible files, never ignored local credentials or tool environments.
        paths = run(
            "git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", capture=True
        )
        with tempfile.TemporaryDirectory(prefix="nebula-scan-") as directory:
            for name in paths.split("\x00"):
                source = Path(name)
                if not name or source.is_symlink() or not source.is_file():
                    continue
                destination = Path(directory) / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            run(
                scanner,
                "dir",
                "--redact",
                "--no-banner",
                "--ignore-gitleaks-allow",
                "--config",
                Path(".gitleaks.toml").resolve(),
                directory,
            )


def setup():
    values = config()["git"]
    for key, field in [("user.name", "author_name"), ("user.email", "author_email")]:
        current = subprocess.run(
            ["git", "config", "--local", "--get", key], capture_output=True, text=True
        )
        if current.returncode == 0 and current.stdout.strip() != values[field]:
            raise ValueError(f"Existing local {key} conflicts with nebula.toml; resolve explicitly")
        run("git", "config", "--local", key, values[field])
    run("git", "config", "--local", "user.useConfigOnly", "true")
    gitleaks()
    run(
        "pre-commit",
        "install",
        "--install-hooks",
        "--hook-type",
        "pre-commit",
        "--hook-type",
        "commit-msg",
        "--hook-type",
        "pre-push",
    )


def metadata():
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name == "pull_request":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        pr = event["pull_request"]
        validate_message(pr["title"])
        validate_branch(pr["head"]["ref"])
        # PRs may contain several commits; validate every new subject and all trailers.
        messages = git("log", "--format=%B%x00", f"{pr['base']['sha']}..{pr['head']['sha']}")
        for message in messages.split("\x00"):
            if message.strip():
                validate_message(message.strip())
    else:
        validate_branch(
            os.environ.get("GITHUB_REF_NAME") or git("branch", "--show-current"), allow_main=True
        )
        validate_message(git("log", "-1", "--format=%B"))


def check():
    run("ruff", "check", TOOLS)
    run("ruff", "format", "--check", TOOLS)
    run("pytest", TOOLS / "tests")
    secrets("all")
    run("sphinx-build", "-W", "--keep-going", "-b", "html", "docs", "docs/_build/html")
    for command in config().get("checks", {}).get("commands", []):
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(v, str) for v in command)
        ):
            raise ValueError("checks.commands must contain non-empty argument lists")
        run(*command)


def protection(current, require_checks):
    review = (current or {}).get("required_pull_request_reviews") or {}
    checks = (current or {}).get("required_status_checks") or {}
    desired = {
        "required_status_checks": None,
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": review.get("require_code_owner_reviews", False),
            "required_approving_review_count": review.get("required_approving_review_count", 0),
            "require_last_push_approval": review.get("require_last_push_approval", False),
        },
        "restrictions": None,
        "required_linear_history": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "required_conversation_resolution": True,
        "lock_branch": (current or {}).get("lock_branch", {}).get("enabled", False),
        "allow_fork_syncing": (current or {}).get("allow_fork_syncing", {}).get("enabled", False),
    }
    for key in ["dismissal_restrictions", "bypass_pull_request_allowances"]:
        if review.get(key):
            desired["required_pull_request_reviews"][key] = {
                kind: [
                    v["login"] if kind == "users" else v["slug"] for v in review[key].get(kind, [])
                ]
                for kind in ["users", "teams", "apps"]
            }
    restrict = (current or {}).get("restrictions")
    if restrict:
        desired["restrictions"] = {
            kind: [v["login"] if kind == "users" else v["slug"] for v in restrict.get(kind, [])]
            for kind in ["users", "teams", "apps"]
        }
    known = {item["context"]: (item.get("app_id") or -1) for item in checks.get("checks", [])}
    for context in checks.get("contexts", []):
        known.setdefault(context, -1)
    if require_checks:
        known.update({name: 15368 for name in CHECKS})  # Official GitHub Actions App.
    if known:
        desired["required_status_checks"] = {
            "strict": True,
            "checks": [{"context": name, "app_id": app} for name, app in sorted(known.items())],
        }
    return desired


def read_protection(repo):
    branch = api(f"repos/{repo}/branches/main")
    if not branch["protected"]:
        return None
    return api(f"repos/{repo}/branches/main/protection")


def normalized_policy(current):
    if not current:
        return {}
    result = {}
    for key in [
        "enforce_admins",
        "required_linear_history",
        "allow_force_pushes",
        "allow_deletions",
        "required_conversation_resolution",
        "lock_branch",
        "allow_fork_syncing",
    ]:
        result[key] = current.get(key, {}).get("enabled", False)
    review = current.get("required_pull_request_reviews")
    result["required_pull_request_reviews"] = (
        None
        if review is None
        else {
            key: review.get(key, False if key != "required_approving_review_count" else 0)
            for key in [
                "dismiss_stale_reviews",
                "require_code_owner_reviews",
                "required_approving_review_count",
                "require_last_push_approval",
            ]
        }
    )
    preserved = protection(current, False)
    for key in ["dismissal_restrictions", "bypass_pull_request_allowances"]:
        if review and key in preserved["required_pull_request_reviews"]:
            result["required_pull_request_reviews"][key] = preserved[
                "required_pull_request_reviews"
            ][key]
    result["restrictions"] = preserved["restrictions"]
    result["required_status_checks"] = preserved["required_status_checks"]
    if result["required_status_checks"]:
        result["required_status_checks"]["strict"] = current["required_status_checks"].get(
            "strict", False
        )
    return result


def repo_settings(action):
    repo = config()["project"]["repository"]
    current = read_protection(repo)
    runs = api(f"repos/{repo}/actions/runs?status=success&per_page=100")["workflow_runs"]
    ready = False
    for item in runs:
        if item["path"] != ".github/workflows/ci.yml":
            continue
        jobs = api(f"repos/{repo}/actions/runs/{item['id']}/jobs")["jobs"]
        if all(
            any(job["name"] == name and job["conclusion"] == "success" for job in jobs)
            for name in CHECKS
        ):
            ready = True
            break
    desired = protection(current, ready)
    repository = api(f"repos/{repo}")
    settings = {
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": False,
        "squash_merge_commit_title": "PR_TITLE",
        "squash_merge_commit_message": "BLANK",
        "delete_branch_on_merge": True,
    }
    drift = {key: value for key, value in settings.items() if repository.get(key) != value}
    actual = normalized_policy(current)
    protection_drift = {key: value for key, value in desired.items() if actual.get(key) != value}
    workflows = api(f"repos/{repo}/actions/permissions/workflow")
    print(
        json.dumps(
            {
                "repository": repo,
                "checks_ready": ready,
                "settings_drift": drift,
                "protection_drift": protection_drift,
                "actions_pr_permission_drift": not workflows["can_approve_pull_request_reviews"],
            },
            indent=2,
        )
    )
    if action == "apply":
        if drift:
            api(f"repos/{repo}", "PATCH", settings)
        if protection_drift:
            api(f"repos/{repo}/branches/main/protection", "PUT", desired)
        if normalized_policy(read_protection(repo)) != desired:
            raise ValueError("GitHub protection readback differs from desired configuration")
        if not workflows["can_approve_pull_request_reviews"]:
            api(
                f"repos/{repo}/actions/permissions/workflow",
                "PUT",
                {
                    "default_workflow_permissions": workflows["default_workflow_permissions"],
                    "can_approve_pull_request_reviews": True,
                },
            )
        print("GitHub settings applied and protection verified")


def cliff(*args):
    text = run("git-cliff", "--config", TOOLS / "cliff.toml", *args, capture=True)
    repo = config()["project"]["repository"]
    return re.sub(
        r"\(#(\d+)\)", lambda m: f"([#{m[1]}](https://github.com/{repo}/pull/{m[1]}))", text
    )


def next_version(bump):
    args = ["--bumped-version"]
    if bump != "auto":
        args += ["--bump", bump]
    version = cliff(*args).strip()
    if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
        raise ValueError("git-cliff did not return a stable SemVer tag")
    return version


def clean_main():
    if git("status", "--porcelain"):
        raise ValueError("A clean checkout is required")
    if git("branch", "--show-current") != "main":
        raise ValueError("Start from main")
    run("git", "fetch", "--tags", "origin", "main")
    if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
        raise ValueError("main diverged; synchronize explicitly before release/update")


def commit_identity():
    env = os.environ.copy()
    values = config()["git"]
    for kind in ["AUTHOR", "COMMITTER"]:
        env[f"GIT_{kind}_NAME"] = values["author_name"]
        env[f"GIT_{kind}_EMAIL"] = values["author_email"]
    return env


def prepare_pr(kind, bump="auto"):
    clean_main()
    repo = config()["project"]["repository"]
    version = next_version(bump) if kind == "release" else None
    if version and git("tag", "--list", version):
        print(f"{version} already exists; no new release changes")
        return None
    branch = f"chore/release-{version}" if version else "chore/changelog"
    existing = api(f"repos/{repo}/pulls?state=open&head={repo.split('/')[0]}:{branch}")
    if existing and kind == "release":
        print(existing[0]["html_url"])
        return existing[0]["number"]
    title = (
        f"chore(release): {version}" if version else "chore(changelog): refresh accepted history"
    )
    content = cliff("--tag", version) if version else cliff()
    target = Path("docs/CHANGELOG.md")
    if not version and target.exists() and target.read_text() == content + "\n":
        return None
    if existing:
        run("git", "fetch", "origin", branch)
        if git("branch", "--list", branch):
            if git("rev-parse", branch) != git("rev-parse", f"origin/{branch}"):
                raise ValueError("Local changelog branch diverged; inspect it explicitly")
            run("git", "switch", branch)
        else:
            run("git", "switch", "--track", "-c", branch, f"origin/{branch}")
        changed = git("diff", "--name-only", "origin/main...HEAD").splitlines()
        if any(name != "docs/CHANGELOG.md" for name in changed):
            raise ValueError("Changelog branch contains unrelated changes; refusing to rewrite it")
        run(
            "git",
            "merge",
            "origin/main",
            "-m",
            "chore(changelog): reconcile accepted history",
            env=commit_identity(),
        )
    else:
        if git("ls-remote", "--heads", "origin", f"refs/heads/{branch}"):
            raise ValueError(f"Remote {branch} exists without an open PR; inspect it explicitly")
        run("git", "switch", "-c", branch)
    target.write_text(content + "\n")
    files = [str(target)]
    if version:
        Path("VERSION").write_text(version.removeprefix("v") + "\n")
        files += ["VERSION"]
    run("git", "add", *files)
    if git("diff", "--cached", "--name-only"):
        run("git", "-c", "commit.gpgsign=false", "commit", "-m", title, env=commit_identity())
    run("git", "push", "-u", "origin", branch)
    body = "Generated from accepted main history. Review the changelog and run the required checks; no infrastructure deployment is included."
    pr = (
        existing[0]
        if existing
        else api(
            f"repos/{repo}/pulls",
            "POST",
            {"title": title, "head": branch, "base": "main", "body": body},
        )
    )
    print(pr["html_url"])
    # Explicit dispatch works for both human and GITHUB_TOKEN-created branches.
    api(f"repos/{repo}/actions/workflows/ci.yml/dispatches", "POST", {"ref": branch})
    return pr["number"]


def release(action, bump):
    if action == "plan":
        tag = next_version(bump)
        print(tag)
        print(cliff("--unreleased", "--tag", tag))
        return
    if action == "publish":
        publish()
        return
    pr = prepare_pr("release", bump)
    if pr is None:
        return
    repo = config()["project"]["repository"]
    info = api(f"repos/{repo}/pulls/{pr}")
    sha = info["head"]["sha"]
    for _ in range(12):
        checks = api(f"repos/{repo}/commits/{sha}/check-runs")["check_runs"]
        if all(any(item["name"] == name for item in checks) for name in CHECKS):
            break
        time.sleep(5)
    else:
        raise ValueError("Required CI checks did not appear; release PR remains open")
    run("gh", "pr", "checks", str(pr), "--repo", repo, "--watch", "--interval", "10")
    run(
        "gh",
        "pr",
        "merge",
        str(pr),
        "--repo",
        repo,
        "--squash",
        "--delete-branch",
        "--match-head-commit",
        sha,
    )
    run("git", "switch", "main")
    run("git", "pull", "--ff-only")
    print("Release PR merged. Check the Publish workflow and Read the Docs build separately.")


def publish():
    repo = config()["project"]["repository"]
    tag = "v" + Path("VERSION").read_text().strip()
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag) or tag == "v0.0.0":
        raise ValueError("VERSION must name an actual stable release")
    sha = git("rev-parse", "HEAD")
    if not git("log", "-1", "--format=%s").startswith(f"chore(release): {tag}"):
        raise ValueError("Only a validated release PR commit can be published")
    run("git", "fetch", "origin", "main", "--tags")
    run("git", "merge-base", "--is-ancestor", sha, "origin/main")
    local = git("tag", "--list", tag)
    if local:
        if git("rev-list", "-n", "1", tag) != sha:
            raise ValueError(
                "Existing release tag points to a different commit; refusing to move it"
            )
    notes = Path("docs/CHANGELOG.md").read_text()
    marker = f"## {tag}"
    if marker not in notes:
        raise ValueError("Changelog does not contain the released version")
    body = notes.split(marker, 1)[1].split("\n## ", 1)[0].strip()
    if not local:
        run("git", "tag", tag, sha)
    # Retry a failed tag push before creating release metadata.
    run("git", "push", "origin", tag)
    releases = api(f"repos/{repo}/releases?per_page=100")
    existing = next((r for r in releases if r["tag_name"] == tag), None)
    if existing:
        print(existing["html_url"])
        return
    created = api(
        f"repos/{repo}/releases",
        "POST",
        {"tag_name": tag, "target_commitish": sha, "name": tag, "body": body},
    )
    print(created["html_url"])


def template_update(ref):
    if git("status", "--porcelain"):
        raise ValueError("A clean checkout is required for template updates")
    if not Path(".copier-answers.yml").exists():
        raise ValueError("This repository has not adopted a Copier template")
    branch = "chore/template-update-" + (ref or "latest")
    validate_branch(branch)
    run("git", "switch", "-c", branch)
    args = ["copier", "update", "--defaults", "--overwrite"]
    if ref:
        args += ["--vcs-ref", ref]
    run(*args)
    # Copier can succeed while leaving merge markers; fail before a commit.
    run("git", "diff", "--check")
    if list(Path(".").rglob("*.rej")):
        raise ValueError("Template update has unresolved reject files")
    print("Review the diff, run make setup/check, and open a PR")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["setup", "check", "metadata"]:
        sub.add_parser(command)
    secret = sub.add_parser("secrets")
    secret.add_argument("mode", choices=["staged", "outgoing", "all"])
    message = sub.add_parser("message")
    message.add_argument("path")
    repo = sub.add_parser("repo")
    repo.add_argument("action", choices=["plan", "apply"])
    sub.add_parser("changelog")
    sub.add_parser("changelog-pr")
    rel = sub.add_parser("release")
    rel.add_argument("action", choices=["plan", "run", "publish"])
    rel.add_argument("--bump", choices=["auto", "patch", "minor", "major"], default="auto")
    update = sub.add_parser("template-update")
    update.add_argument("--ref")
    args = parser.parse_args()
    try:
        if args.command == "setup":
            setup()
        elif args.command == "check":
            check()
        elif args.command == "metadata":
            metadata()
        elif args.command == "message":
            validate_message(Path(args.path).read_text())
        elif args.command == "secrets":
            secrets(args.mode)
        elif args.command == "repo":
            repo_settings(args.action)
        elif args.command == "release":
            release(args.action, args.bump)
        elif args.command == "changelog":
            Path("docs/CHANGELOG.md").write_text(cliff() + "\n")
        elif args.command == "changelog-pr":
            prepare_pr("changelog")
        elif args.command == "template-update":
            template_update(args.ref)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"nebula: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
