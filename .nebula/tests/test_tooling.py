import shutil
import subprocess
from pathlib import Path

import pytest

from nebula import cli


@pytest.mark.parametrize(
    "message",
    [
        "feat(vm): create template",
        "fix: correct validation",
        "feat(api)!: change contract\n\nBREAKING CHANGE: new schema",
    ],
)
def test_valid_messages(message):
    cli.validate_message(message)


@pytest.mark.parametrize(
    "message", ["", "random change", "feat:", "feat(x): valid\n\nCo-authored-by: someone"]
)
def test_bad_messages(message):
    with pytest.raises(ValueError):
        cli.validate_message(message)


@pytest.mark.parametrize("branch", ["codex/work", "feature/codex-work", "main", "work", "feature/"])
def test_bad_branches(branch):
    with pytest.raises(ValueError):
        cli.validate_branch(branch)


def test_protection_preserves_stronger_requirements():
    current = {
        "required_pull_request_reviews": {
            "required_approving_review_count": 2,
            "require_code_owner_reviews": True,
            "require_last_push_approval": True,
        },
        "required_status_checks": {"checks": [{"context": "application/test", "app_id": 77}]},
        "restrictions": {"users": [{"login": "owner"}], "teams": [], "apps": []},
        "lock_branch": {"enabled": True},
    }
    result = cli.protection(current, True)
    assert result["required_pull_request_reviews"]["required_approving_review_count"] == 2
    assert result["required_pull_request_reviews"]["require_last_push_approval"]
    assert result["required_pull_request_reviews"]["require_code_owner_reviews"]
    assert result["restrictions"]["users"] == ["owner"]
    assert result["lock_branch"]
    assert {x["context"] for x in result["required_status_checks"]["checks"]} == {
        "application/test",
        "nebula/checks",
    }


def repository(path):
    path.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(path)], check=True, capture_output=True
    )
    for key, value in [
        ("user.name", "Fixture"),
        ("user.email", "fixture@example.invalid"),
        ("commit.gpgsign", "false"),
    ]:
        subprocess.run(["git", "-C", str(path), "config", key, value], check=True)
    return path


def commit(path, message):
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "--allow-empty",
            "-m",
            message,
        ],
        check=True,
        capture_output=True,
    )


def test_staged_and_removed_secret_are_blocked(tmp_path, monkeypatch):
    repo = repository(tmp_path / "source")
    cfg = Path.cwd() / ".gitleaks.toml"
    shutil.copy2(cfg, repo / cfg.name)
    commit(repo, "chore(test): initialize fixture")
    (repo / "fixture.txt").write_text("NEBULA_" + "TEST_SECRET_" + "A" * 24)
    subprocess.run(["git", "-C", str(repo), "add", "fixture.txt"], check=True)
    monkeypatch.chdir(repo)
    with pytest.raises(subprocess.CalledProcessError):
        cli.secrets("staged")
    commit(repo, "feat(test): add synthetic fixture")
    (repo / "fixture.txt").unlink()
    commit(repo, "fix(test): remove synthetic fixture")
    subprocess.run(["git", "switch", "-c", "feature/fixture"], check=True, capture_output=True)
    with pytest.raises(subprocess.CalledProcessError):
        cli.secrets("outgoing")


def test_release_notes_and_bump_use_git_cliff(tmp_path, monkeypatch):
    repo = repository(tmp_path / "history")
    (repo / "nebula.toml").write_text('[project]\nrepository="Example/project"\n')
    commit(repo, "chore(repository): initialize")
    subprocess.run(["git", "-C", str(repo), "tag", "v0.1.0"], check=True)
    commit(repo, "feat(api): expose resource (#3)")
    commit(repo, "fix(api): validate owner (#4)")
    monkeypatch.chdir(repo)
    assert cli.next_version("auto") == "v0.2.0"
    notes = cli.cliff("--tag", "v0.2.0")
    assert "https://github.com/Example/project/pull/3" in notes
    assert "https://github.com/Example/project/pull/4" in notes
    assert notes.count("expose resource") == 1
    assert cli.cliff("--tag", "v0.2.0") == notes


def test_existing_tag_cannot_be_moved(tmp_path, monkeypatch):
    repo = repository(tmp_path / "publish")
    (repo / "nebula.toml").write_text('[project]\nrepository="Example/project"\n')
    (repo / "VERSION").write_text("0.1.0\n")
    commit(repo, "chore(repository): initialize")
    subprocess.run(["git", "-C", str(repo), "tag", "v0.1.0"], check=True)
    commit(repo, "chore(release): v0.1.0 (#1)")
    monkeypatch.chdir(repo)
    original = cli.run

    def run(*args, **kwargs):
        if args[:2] in [("git", "fetch"), ("git", "merge-base"), ("git", "push")]:
            return ""
        return original(*args, **kwargs)

    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(ValueError, match="different commit"):
        cli.publish()


def test_template_copy_and_update_preserve_customizations(tmp_path, monkeypatch):
    from copier import run_copy

    root = Path.cwd()
    if not (root / "copier.yml").exists():
        pytest.skip("Template lifecycle is tested in the template source repository")
    source = tmp_path / "template"
    shutil.copytree(
        root,
        source,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "bin", "__pycache__", "_build", ".pytest_cache", ".ruff_cache"
        ),
    )
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(source)], check=True, capture_output=True
    )
    for key, value in [
        ("user.name", "Fixture"),
        ("user.email", "fixture@example.invalid"),
        ("commit.gpgsign", "false"),
    ]:
        subprocess.run(["git", "-C", str(source), "config", key, value], check=True)
    commit(source, "feat(template): foundation")
    subprocess.run(["git", "-C", str(source), "tag", "v0.1.0"], check=True)
    target = tmp_path / "consumer"
    answers = {
        "project_name": "Fixture",
        "repository": "Example/fixture",
        "documentation": "private",
        "author_name": "Fixture",
        "author_email": "fixture@example.invalid",
    }
    run_copy(str(source), target, data=answers, defaults=True, vcs_ref="v0.1.0")
    assert (target / "VERSION").read_text() == "0.0.0\n"
    assert not (target / ".nebula").is_symlink()
    assert (target / ".nebula/nebula/cli.py").exists()
    assert not (target / ".readthedocs.yaml").exists()
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(target)], check=True, capture_output=True
    )
    for key, value in [
        ("user.name", "Fixture"),
        ("user.email", "fixture@example.invalid"),
        ("commit.gpgsign", "false"),
    ]:
        subprocess.run(["git", "-C", str(target), "config", key, value], check=True)
    commit(target, "chore(template): adopt")
    (target / "README.md").write_text("# Custom consumer\n")
    (target / "Makefile.project").write_text("custom:\n\t@true\n")
    config = target / "nebula.toml"
    config.write_text(config.read_text().replace("commands = []", 'commands = [["true"]]'))
    commit(target, "feat(project): customize consumer")
    guide = source / "docs/development.md"
    guide.write_text(guide.read_text() + "\nNew template behavior.\n")
    commit(source, "docs(template): add upgrade guidance")
    subprocess.run(["git", "-C", str(source), "tag", "v0.1.1"], check=True)
    monkeypatch.chdir(target)
    cli.template_update("v0.1.1")
    assert (target / "README.md").read_text() == "# Custom consumer\n"
    assert (target / "Makefile.project").exists()
    assert 'commands = [["true"]]' in config.read_text()
    assert "New template behavior" in (target / "docs/development.md").read_text()
    assert "v0.1.1" in (target / ".copier-answers.yml").read_text()


def test_policy_normalization_detects_missing_enforcement():
    policy = cli.protection(None, False)
    raw = {key: {"enabled": value} for key, value in policy.items() if isinstance(value, bool)}
    raw["enforce_admins"] = {"enabled": False}
    raw["required_pull_request_reviews"] = policy["required_pull_request_reviews"]
    assert cli.normalized_policy(raw)["enforce_admins"] is False
    assert cli.normalized_policy(raw) != policy


def test_publication_retry_does_not_duplicate_release(tmp_path, monkeypatch):
    repo = repository(tmp_path / "retry")
    (repo / "nebula.toml").write_text('[project]\nrepository="Example/project"\n')
    (repo / "VERSION").write_text("0.1.0\n")
    (repo / "docs").mkdir()
    (repo / "docs/CHANGELOG.md").write_text("# Changelog\n\n## v0.1.0\n\n- A change\n")
    commit(repo, "chore(release): v0.1.0 (#1)")
    subprocess.run(["git", "-C", str(repo), "tag", "v0.1.0"], check=True)
    monkeypatch.chdir(repo)
    original = cli.run
    releases = []

    def run(*args, **kwargs):
        if args[:2] in [("git", "fetch"), ("git", "merge-base"), ("git", "push")]:
            return ""
        return original(*args, **kwargs)

    def api(path, method="GET", data=None):
        if method == "POST":
            releases.append({**data, "html_url": "https://example.invalid/release"})
            return releases[-1]
        return releases

    monkeypatch.setattr(cli, "run", run)
    monkeypatch.setattr(cli, "api", api)
    cli.publish()
    cli.publish()
    assert len(releases) == 1


def test_invalid_notes_do_not_create_a_tag(tmp_path, monkeypatch):
    repo = repository(tmp_path / "invalid-notes")
    (repo / "nebula.toml").write_text('[project]\nrepository="Example/project"\n')
    (repo / "VERSION").write_text("0.1.0\n")
    (repo / "docs").mkdir()
    (repo / "docs/CHANGELOG.md").write_text("# Changelog\n")
    commit(repo, "chore(release): v0.1.0 (#1)")
    monkeypatch.chdir(repo)
    original = cli.run

    def run(*args, **kwargs):
        if args[:2] in [("git", "fetch"), ("git", "merge-base")]:
            return ""
        return original(*args, **kwargs)

    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(ValueError, match="Changelog"):
        cli.publish()
    assert not cli.git("tag", "--list", "v0.1.0")


def test_changelog_refresh_after_release_preserves_main_and_retries(tmp_path, monkeypatch):
    repo = repository(tmp_path / "refresh")
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(remote)], check=True)
    (repo / "nebula.toml").write_text(
        '[project]\nrepository="Example/project"\n[git]\nauthor_name="Fixture"\nauthor_email="fixture@example.invalid"\n'
    )
    (repo / "docs").mkdir()
    target = repo / "docs/CHANGELOG.md"
    target.write_text("Original generated history\n")
    commit(repo, "feat(repository): initialize")
    subprocess.run(
        ["git", "-C", str(repo), "push", "-u", "origin", "main"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "switch", "-c", "chore/changelog"], check=True, capture_output=True
    )
    target.write_text("Unreleased generated history\n")
    commit(repo, "chore(changelog): refresh accepted history")
    subprocess.run(
        ["git", "-C", str(repo), "push", "-u", "origin", "chore/changelog"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(repo), "switch", "main"], check=True, capture_output=True)
    target.write_text("Released generated history\n")
    (repo / "application.txt").write_text("Accepted main change\n")
    commit(repo, "chore(release): v0.1.0")
    subprocess.run(["git", "-C", str(repo), "push"], check=True, capture_output=True)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "cliff", lambda *args: "Complete generated history")
    monkeypatch.setattr(
        cli, "api", lambda path, *args: [{"number": 1, "html_url": "https://example.invalid/pr"}]
    )
    assert cli.prepare_pr("changelog") == 1
    assert target.read_text() == "Complete generated history\n"
    assert (repo / "application.txt").read_text() == "Accepted main change\n"
    first = cli.git("rev-parse", "HEAD")
    subprocess.run(["git", "switch", "main"], check=True, capture_output=True)
    assert cli.prepare_pr("changelog") == 1
    assert cli.git("rev-parse", "HEAD") == first
