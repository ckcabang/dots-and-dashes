"""scripts/sync-worktree merges a branch into a worktree whose .claude/ is masked.

Each test builds a throwaway repo: main moved on since feature branched, and
feature is checked out in a real `git worktree` whose .claude/ is read-only, as
the sandbox's mask leaves it. The script runs there as an agent would run it.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYNC = ROOT / "scripts" / "sync-worktree"

# Files to write, each path mapped to its content, or to None to delete it.
Files = dict[str, str | None]


def greet(word: str) -> str:
    return f'def greet():\n    return "{word}"\n'


BASE: Files = {
    ".claude/agents/spec.md": "spec\n",
    "app.py": greet("hello"),
    "notes.md": "notes\n",
}
# main changes .claude/, so a plain `git merge` would fail on the mask, and
# both sides change app.py, so the merge conflicts.
CLAUDE_CHANGE: Files = {".claude/agents/spec.md": "spec v2\n"}
MAIN_CONFLICT: Files = CLAUDE_CHANGE | {"app.py": greet("hello, main")}
FEATURE_CONFLICT: Files = {"app.py": greet("hello, feature")}
RESOLVED: Files = {"app.py": greet("hello, both")}

MARKERS = "<<<<<<<"


def write(root: Path, files: Files) -> None:
    for name, content in files.items():
        path = root / name
        if content is None:
            path.unlink()
            # As git does, leave no directory empty.
            for parent in path.relative_to(root).parents[:-1]:
                if any((root / parent).iterdir()):
                    break
                (root / parent).rmdir()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)


class Worktree:
    """feature checked out in a worktree of a repo whose main moved on."""

    def __init__(
        self,
        tmp_path: Path,
        env: dict[str, str],
        main: Files,
        feature: Files,
        base: Files | None = None,
        untracked: Files | None = None,
    ) -> None:
        self.env = env
        self.repo = tmp_path / "repo"
        self.path = tmp_path / "wt"
        self.repo.mkdir()
        self.git("init", "-q", cwd=self.repo)
        self.commit(self.repo, BASE | (base or {}), "base")
        self.git("branch", "feature", cwd=self.repo)
        self.commit(self.repo, main, "main")
        self.main = self.git("rev-parse", "main", cwd=self.repo)
        self.git("worktree", "add", "-q", str(self.path), "feature", cwd=self.repo)
        self.commit(self.path, feature, "feature")
        self.before = self.head()
        write(self.path, untracked or {})
        mask(self.path / ".claude")

    def git(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd or self.path,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.rstrip("\n")

    def commit(self, root: Path, files: Files, message: str) -> None:
        write(root, files)
        self.git("add", "-A", cwd=root)
        self.git("commit", "-q", "--allow-empty", "-m", message, cwd=root)

    def sync(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SYNC), *args], cwd=self.path, env=self.env, capture_output=True, text=True
        )

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def parents(self) -> list[str]:
        return self.git("log", "-1", "--format=%P").split()

    def status(self) -> str:
        return self.git("status", "--porcelain")

    def committed(self, name: str) -> str:
        return self.git("show", f"HEAD:{name}") + "\n"

    def tracked(self) -> list[str]:
        return self.git("ls-tree", "-r", "-z", "--name-only", "HEAD").rstrip("\0").split("\0")

    def read(self, name: str) -> str:
        return (self.path / name).read_text()

    def state(self) -> Path:
        return self.path / self.git("rev-parse", "--git-path", "sync-worktree-merge")

    def pending(self) -> bool:
        return self.state().exists()

    def assert_unchanged(self) -> None:
        """HEAD, the index and the files are where they were before the merge."""
        assert self.head() == self.before
        assert self.status() == ""
        assert not self.pending()

    def assert_merged(self, status: str = "") -> None:
        """HEAD is a merge of main, with .claude/ hidden and nothing left over."""
        assert self.parents() == [self.before, self.main]
        assert self.status() == status
        assert not self.pending()
        flags = self.git("ls-files", "-v", ".claude").splitlines()
        assert flags and all(line.startswith("S ") for line in flags)


def mask(path: Path) -> None:
    """Make path read-only, as the sandbox's mount over .claude/ does."""
    subprocess.run(["chmod", "-R", "a-w", str(path)], check=True)


def conflicted(tmp_path: Path, env: dict[str, str], **kwargs: Files) -> Worktree:
    main = MAIN_CONFLICT | kwargs.pop("main", {})
    feature = FEATURE_CONFLICT | kwargs.pop("feature", {})
    return Worktree(tmp_path, env, main=main, feature=feature, **kwargs)


def test_a_branch_that_leaves_claude_alone_merges_plainly(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = Worktree(tmp_path, git_env, main={"notes.md": "notes v2\n"}, feature={"x.md": "x\n"})

    result = wt.sync("main")

    assert result.returncode == 0, result.stderr
    assert wt.parents() == [wt.before, wt.main]
    assert wt.read("notes.md") == "notes v2\n"
    assert wt.status() == ""


def test_a_clean_merge_that_changes_claude_commits_it_without_writing_it(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = Worktree(
        tmp_path,
        git_env,
        main=CLAUDE_CHANGE | {"notes.md": "notes v2\n"},
        feature={"x.md": "x\n"},
        untracked={"scratch.txt": "scratch\n"},
    )

    result = wt.sync("main")

    assert result.returncode == 0, result.stderr
    assert "Merged main" in result.stdout
    assert wt.committed(".claude/agents/spec.md") == "spec v2\n"
    assert wt.read(".claude/agents/spec.md") == "spec\n"
    assert wt.read("notes.md") == "notes v2\n"
    assert "scratch.txt" not in wt.tracked()
    wt.assert_merged(status="?? scratch.txt")


def test_a_merge_that_turns_a_directory_into_a_file_writes_the_file(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = Worktree(
        tmp_path,
        git_env,
        base={"d/x.txt": "x\n"},
        main=CLAUDE_CHANGE | {"d/x.txt": None, "d": "now a file\n"},
        feature={"y.md": "y\n"},
    )

    result = wt.sync("main")

    assert result.returncode == 0, result.stderr
    assert wt.read("d") == "now a file\n"
    wt.assert_merged()


def test_a_conflict_outside_claude_writes_markers_and_stops(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = conflicted(tmp_path, git_env)

    result = wt.sync("main")

    assert result.returncode == 1
    assert "  app.py" in result.stderr.splitlines()
    assert MARKERS in wt.read("app.py")
    assert wt.head() == wt.before
    assert wt.pending()


def test_continue_refuses_while_markers_remain_then_commits_a_merge(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = conflicted(tmp_path, git_env)
    wt.sync("main")

    refused = wt.sync("--continue")

    assert refused.returncode == 1
    assert "conflict markers remain" in refused.stderr
    assert wt.head() == wt.before

    write(wt.path, RESOLVED)
    result = wt.sync("--continue")

    assert result.returncode == 0, result.stderr
    assert wt.committed("app.py") == greet("hello, both")
    assert wt.committed(".claude/agents/spec.md") == "spec v2\n"
    wt.assert_merged()


def test_continue_commits_other_changes_made_while_resolving(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = conflicted(tmp_path, git_env, untracked={"scratch.txt": "scratch\n"})
    wt.sync("main")
    write(wt.path, RESOLVED | {"notes.md": "edited while resolving\n", "added.md": "new\n"})

    result = wt.sync("--continue")

    assert result.returncode == 0, result.stderr
    assert wt.committed("notes.md") == "edited while resolving\n"
    assert wt.committed("added.md") == "new\n"
    assert "scratch.txt" not in wt.tracked()
    wt.assert_merged(status="?? scratch.txt")


def test_a_conflict_inside_claude_changes_nothing(tmp_path: Path, git_env: dict[str, str]) -> None:
    wt = Worktree(
        tmp_path,
        git_env,
        main=MAIN_CONFLICT,
        feature=FEATURE_CONFLICT | {".claude/agents/spec.md": "spec, feature\n"},
    )

    result = wt.sync("main")

    assert result.returncode == 1
    assert "conflicts inside .claude/" in result.stderr
    assert ".claude/agents/spec.md" in result.stderr
    assert wt.read("app.py") == greet("hello, feature")
    wt.assert_unchanged()


def test_abort_restores_what_the_merge_changed_deleted_and_added(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = conflicted(tmp_path, git_env, main={"notes.md": None, "new.py": "new\n"})
    wt.sync("main")
    assert not (wt.path / "notes.md").exists()

    result = wt.sync("--abort")

    assert result.returncode == 0, result.stderr
    assert wt.read("app.py") == greet("hello, feature")
    assert wt.read("notes.md") == "notes\n"
    assert not (wt.path / "new.py").exists()
    assert wt.git("ls-files", "-v", ".claude").startswith("S ")
    wt.assert_unchanged()


def test_abort_removes_the_directories_the_merge_created(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = conflicted(tmp_path, git_env, main={"docs/guides/start.md": "start\n"})
    wt.sync("main")
    assert (wt.path / "docs/guides/start.md").exists()

    wt.sync("--abort")

    assert not (wt.path / "docs").exists()
    wt.assert_unchanged()


def test_untracked_files_where_the_branch_adds_files_change_nothing(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    mine: Files = {"new.py": "mine\n", "lib.py": "mine\n", "s p.py": "mine\n"}
    wt = conflicted(tmp_path, git_env, main=dict.fromkeys(mine, "main's\n"), untracked=mine)

    result = wt.sync("main")

    assert result.returncode == 1
    assert "would overwrite these untracked files" in result.stderr
    lines = result.stderr.splitlines()
    assert {"  new.py", "  lib.py", "  s p.py"} <= set(lines)
    assert all(wt.read(name) == "mine\n" for name in mine)
    assert wt.head() == wt.before
    assert not wt.pending()


def test_a_file_the_branch_renames_is_not_committed_back(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = conflicted(tmp_path, git_env, main={"notes.md": None, "renamed.md": "notes\n"})
    wt.sync("main")
    write(wt.path, RESOLVED)

    result = wt.sync("--continue")

    assert result.returncode == 0, result.stderr
    assert "renamed.md" in wt.tracked()
    assert "notes.md" not in wt.tracked()
    wt.assert_merged()


def test_paths_with_spaces_merge_and_abort(tmp_path: Path, git_env: dict[str, str]) -> None:
    wt = conflicted(
        tmp_path,
        git_env,
        base={"c d.txt": "space\n", "gone now.txt": "gone\n"},
        main={"a b.txt": "added\n", "c d.txt": "changed\n", "gone now.txt": None},
    )
    wt.sync("main")
    wt.sync("--abort")
    assert wt.read("c d.txt") == "space\n"
    assert wt.read("gone now.txt") == "gone\n"
    assert not (wt.path / "a b.txt").exists()
    wt.assert_unchanged()

    wt.sync("main")
    write(wt.path, RESOLVED)
    result = wt.sync("--continue")

    assert result.returncode == 0, result.stderr
    assert wt.committed("a b.txt") == "added\n"
    assert wt.committed("c d.txt") == "changed\n"
    assert "gone now.txt" not in wt.tracked()
    wt.assert_merged()


def test_a_start_that_stops_partway_must_be_aborted(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = conflicted(tmp_path, git_env, main={"docs/guide.md": "guide\n"})
    docs = wt.path / "docs"
    docs.mkdir()
    mask(docs)

    started = wt.sync("main")

    assert started.returncode != 0
    assert wt.pending()
    write(wt.path, RESOLVED)
    refused = wt.sync("--continue")
    assert refused.returncode == 1
    assert "stopped before writing its files" in refused.stderr
    assert wt.head() == wt.before

    docs.chmod(0o755)
    aborted = wt.sync("--abort")
    assert aborted.returncode == 0, aborted.stderr
    assert docs.is_dir(), "docs/ was there before the merge"
    wt.assert_unchanged()

    wt.sync("main")
    write(wt.path, RESOLVED)
    result = wt.sync("--continue")

    assert result.returncode == 0, result.stderr
    assert wt.committed("docs/guide.md") == "guide\n"
    wt.assert_merged()


def test_a_merge_message_with_several_lines_survives(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    message = "Merge main into feature\n\nPicks up the spec change.\nSecond body line."
    wt = conflicted(tmp_path, git_env)
    wt.sync("main", message)
    write(wt.path, RESOLVED)

    result = wt.sync("--continue")

    assert result.returncode == 0, result.stderr
    assert wt.git("log", "-1", "--format=%B") == message
    wt.assert_merged()


def test_a_name_with_a_star_matches_only_itself(tmp_path: Path, git_env: dict[str, str]) -> None:
    wt = conflicted(
        tmp_path,
        git_env,
        base={"x*.txt": "star\n"},
        main={"x*.txt": "star, main\n"},
        untracked={"yb.txt": "untracked before the merge\n"},
    )
    wt.sync("main")
    write(wt.path, RESOLVED | {"y*.txt": "new while resolving\n"})

    result = wt.sync("--continue")

    assert result.returncode == 0, result.stderr
    assert wt.committed("x*.txt") == "star, main\n"
    assert wt.committed("y*.txt") == "new while resolving\n"
    assert "yb.txt" not in wt.tracked()
    wt.assert_merged(status="?? yb.txt")


CAFE = "café.txt"


def test_a_conflict_at_an_unusual_name_inside_claude_changes_nothing(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    # git C-quotes a name like this one ("caf\303\251.txt") unless asked for -z.
    name = f".claude/{CAFE}"
    wt = Worktree(
        tmp_path,
        git_env,
        base={name: "v1\n"},
        main=MAIN_CONFLICT | {name: "v2\n"},
        feature=FEATURE_CONFLICT | {name: "v3\n"},
    )

    result = wt.sync("main")

    assert result.returncode == 1
    assert "conflicts inside .claude/" in result.stderr
    assert name in result.stderr
    assert wt.read("app.py") == greet("hello, feature")
    wt.assert_unchanged()


def test_continue_refuses_markers_left_in_an_unusual_name(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = conflicted(
        tmp_path,
        git_env,
        base={CAFE: "v1\n"},
        main={CAFE: "v2\n"},
        feature={CAFE: "v3\n"},
    )
    started = wt.sync("main")
    write(wt.path, RESOLVED)

    refused = wt.sync("--continue")

    assert refused.returncode == 1
    assert "conflict markers remain" in refused.stderr
    assert wt.head() == wt.before
    assert f"  {CAFE}" in started.stderr.splitlines()

    write(wt.path, {CAFE: "v4\n"})
    result = wt.sync("--continue")
    assert result.returncode == 0, result.stderr
    assert wt.committed(CAFE) == "v4\n"
    wt.assert_merged()


@pytest.mark.parametrize("flag", ["--continue", "--abort"])
def test_continue_and_abort_need_a_pending_merge(
    tmp_path: Path, git_env: dict[str, str], flag: str
) -> None:
    wt = conflicted(tmp_path, git_env)

    result = wt.sync(flag)

    assert result.returncode == 1
    assert "no merge is pending" in result.stderr


def test_continue_reads_a_merge_the_old_format_recorded(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    # Before this format, the script recorded the conflicted paths one per line.
    # A merge it started may be finished by the script that replaced it.
    wt = conflicted(tmp_path, git_env)
    wt.sync("main")
    (wt.state() / "conflicted").write_text("app.py\n")

    refused = wt.sync("--continue")

    assert refused.returncode == 1
    assert "conflict markers remain" in refused.stderr
    assert wt.head() == wt.before

    write(wt.path, RESOLVED)
    result = wt.sync("--continue")
    assert result.returncode == 0, result.stderr
    wt.assert_merged()


def test_continue_refuses_an_old_format_path_that_is_gone(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    # The old format C-quoted unusual names, so a path missing from the
    # worktree may be one that's there under its real name, markers and all.
    wt = conflicted(tmp_path, git_env)
    wt.sync("main")
    (wt.state() / "conflicted").write_text("app.py\n")
    (wt.path / "app.py").unlink()

    refused = wt.sync("--continue")

    assert refused.returncode == 1
    assert "  app.py" in refused.stderr.splitlines()
    assert wt.head() == wt.before
    assert wt.pending()


def test_continue_commits_a_conflicted_file_deleted_while_resolving(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = conflicted(
        tmp_path,
        git_env,
        main={"notes.md": "notes, main\n"},
        feature={"notes.md": "notes, feature\n"},
    )
    wt.sync("main")
    write(wt.path, RESOLVED | {"notes.md": None})

    result = wt.sync("--continue")

    assert result.returncode == 0, result.stderr
    assert "notes.md" not in wt.tracked()
    wt.assert_merged()


def test_continue_finishes_a_rename_rename_conflict(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    # merge-tree lists the source, f.txt, as conflicted, though neither side has it.
    content = "one\ntwo\nthree\n"
    wt = conflicted(
        tmp_path,
        git_env,
        base={"f.txt": content},
        main={"f.txt": None, "a.txt": content},
        feature={"f.txt": None, "b.txt": content},
    )
    started = wt.sync("main")
    assert "  f.txt" in started.stderr.splitlines()
    write(wt.path, RESOLVED | {"b.txt": None})

    result = wt.sync("--continue")

    assert result.returncode == 0, result.stderr
    assert "a.txt" in wt.tracked()
    assert "b.txt" not in wt.tracked()
    assert "f.txt" not in wt.tracked()
    wt.assert_merged()


def test_continue_refuses_markers_in_a_conflicted_file_moved_to_a_new_name(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    wt = conflicted(tmp_path, git_env)
    wt.sync("main")
    (wt.path / "app.py").rename(wt.path / "app2.py")

    refused = wt.sync("--continue")

    assert refused.returncode == 1
    assert "conflict markers remain" in refused.stderr
    assert refused.stderr.startswith("app2.py:2:<<<<<<< ")
    assert wt.head() == wt.before
    assert wt.pending()


def test_continue_commits_a_resolved_file_moved_to_a_new_name(
    tmp_path: Path, git_env: dict[str, str]
) -> None:
    # scratch.txt was untracked before the merge, so it's neither checked nor committed.
    wt = conflicted(tmp_path, git_env, untracked={"scratch.txt": MARKERS + "\n"})
    wt.sync("main")
    write(wt.path, {"app.py": None, "app2.py": greet("hello, both")})

    result = wt.sync("--continue")

    assert result.returncode == 0, result.stderr
    assert wt.committed("app2.py") == greet("hello, both")
    assert "app.py" not in wt.tracked()
    assert "scratch.txt" not in wt.tracked()
    wt.assert_merged(status="?? scratch.txt")


@dataclass(frozen=True)
class Kind:
    """One kind of conflict `git merge-tree` reports, made beside the app.py one.

    A path may name `{main}`, main's commit: merge-tree moves a file out of a
    directory's way to `<name>~<side>`, and names main's side by its commit."""

    base: Files
    main: Files
    feature: Files
    # The paths the start lists as conflicted, beside app.py.
    conflicted: list[str]
    # The ones holding conflict markers once the start writes them.
    markers: list[str]
    # Two resolutions: keeping a version of the change, and deleting.
    keep: Files
    delete: Files


TEXT = "one\ntwo\nthree\n"
KINDS = {
    "modify/modify": Kind(
        base={"f.txt": TEXT},
        main={"f.txt": TEXT + "main\n"},
        feature={"f.txt": TEXT + "feature\n"},
        conflicted=["f.txt"],
        markers=["f.txt"],
        keep={"f.txt": TEXT + "both\n"},
        delete={"f.txt": None},
    ),
    "modify/delete": Kind(
        base={"f.txt": TEXT},
        main={"f.txt": TEXT + "main\n"},
        feature={"f.txt": None},
        conflicted=["f.txt"],
        markers=[],
        keep={"f.txt": TEXT + "main\n"},
        delete={"f.txt": None},
    ),
    "delete/modify": Kind(
        base={"f.txt": TEXT},
        main={"f.txt": None},
        feature={"f.txt": TEXT + "feature\n"},
        conflicted=["f.txt"],
        markers=[],
        keep={"f.txt": TEXT + "feature\n"},
        delete={"f.txt": None},
    ),
    "rename/delete": Kind(
        base={"f.txt": TEXT},
        main={"f.txt": None, "g.txt": TEXT},
        feature={"f.txt": None},
        conflicted=["g.txt"],
        markers=[],
        keep={"g.txt": TEXT},
        delete={"g.txt": None},
    ),
    "delete/rename": Kind(
        base={"f.txt": TEXT},
        main={"f.txt": None},
        feature={"f.txt": None, "g.txt": TEXT},
        conflicted=["g.txt"],
        markers=[],
        keep={"g.txt": TEXT},
        delete={"g.txt": None},
    ),
    "rename/rename": Kind(
        base={"f.txt": TEXT},
        main={"f.txt": None, "a.txt": TEXT},
        feature={"f.txt": None, "b.txt": TEXT},
        # The source too, though neither side has it.
        conflicted=["a.txt", "b.txt", "f.txt"],
        markers=[],
        keep={"a.txt": TEXT, "b.txt": None},
        delete={"a.txt": None, "b.txt": None},
    ),
    "add/add": Kind(
        base={},
        main={"n.txt": "main\n"},
        feature={"n.txt": "feature\n"},
        conflicted=["n.txt"],
        markers=["n.txt"],
        keep={"n.txt": "both\n"},
        delete={"n.txt": None},
    ),
    "file/directory": Kind(
        base={},
        main={"d": "main\n"},
        feature={"d/x.txt": "x\n"},
        conflicted=["d~{main}"],
        markers=[],
        keep={"d~{main}": None, "d.txt": "main\n"},
        delete={"d~{main}": None},
    ),
    "directory/file": Kind(
        base={},
        main={"d/x.txt": "x\n"},
        feature={"d": "feature\n"},
        conflicted=["d~HEAD"],
        markers=[],
        keep={"d~HEAD": None, "d.txt": "feature\n"},
        delete={"d~HEAD": None},
    ),
}


def named(files: Files, main: str) -> Files:
    return {name.format(main=main): content for name, content in files.items()}


def kind_conflict(tmp_path: Path, env: dict[str, str], kind: Kind) -> Worktree:
    return conflicted(tmp_path, env, base=kind.base, main=kind.main, feature=kind.feature)


@pytest.mark.parametrize("recorded", ["NUL-separated", "one per line"])
@pytest.mark.parametrize("resolution", ["keep", "delete"])
@pytest.mark.parametrize("name", KINDS)
def test_continue_finishes_every_kind_of_conflict_once_it_is_resolved(
    tmp_path: Path, git_env: dict[str, str], name: str, resolution: str, recorded: str
) -> None:
    kind = KINDS[name]
    wt = kind_conflict(tmp_path, git_env, kind)
    paths = ["app.py", *(path.format(main=wt.main) for path in kind.conflicted)]

    started = wt.sync("main")

    assert started.returncode == 1, started.stderr
    assert {f"  {path}" for path in paths} <= set(started.stderr.splitlines())
    if recorded == "one per line":
        # How the script recorded a merge before NUL-separated paths.
        (wt.state() / "conflicted").write_text("".join(f"{path}\n" for path in paths))

    def refused_as_gone(result: subprocess.CompletedProcess[str]) -> bool:
        """An old-format path that's gone may be an unusual name, C-quoted:
        --continue refuses it however the rest is resolved."""
        gone = [path for path in paths if not (wt.path / path).exists()]
        if recorded == "NUL-separated" or not gone:
            return False
        assert result.returncode == 1
        assert {f"  {path}" for path in gone} <= set(result.stderr.splitlines())
        assert wt.head() == wt.before
        assert wt.pending()
        return True

    refused = wt.sync("--continue")
    if refused_as_gone(refused):
        return

    assert refused.returncode == 1
    assert "conflict markers remain" in refused.stderr
    assert wt.head() == wt.before

    write(wt.path, RESOLVED)
    if kind.markers:
        refused = wt.sync("--continue")
        assert refused.returncode == 1
        assert "conflict markers remain" in refused.stderr
        assert all(f"{path}:" in refused.stderr for path in kind.markers)
        assert wt.head() == wt.before

    files = named(kind.keep if resolution == "keep" else kind.delete, wt.main)
    write(wt.path, files)
    result = wt.sync("--continue")

    if refused_as_gone(result):
        return
    assert result.returncode == 0, result.stderr
    assert wt.committed("app.py") == greet("hello, both")
    for path, content in files.items():
        if content is None:
            assert path not in wt.tracked()
        else:
            assert wt.committed(path) == content
    wt.assert_merged()


@pytest.mark.parametrize("name", KINDS)
def test_abort_backs_out_of_every_kind_of_conflict(
    tmp_path: Path, git_env: dict[str, str], name: str
) -> None:
    kind = KINDS[name]
    wt = kind_conflict(tmp_path, git_env, kind)
    wt.sync("main")

    result = wt.sync("--abort")

    assert result.returncode == 0, result.stderr
    on_feature = BASE | kind.base | FEATURE_CONFLICT | kind.feature
    for path, content in on_feature.items():
        if content is None:
            assert not (wt.path / path).exists(), path
        elif not path.startswith(".claude/"):
            assert wt.read(path) == content, path
    for path in named(dict.fromkeys(kind.conflicted), wt.main):
        if path not in on_feature:
            assert not (wt.path / path).exists(), path
    wt.assert_unchanged()
