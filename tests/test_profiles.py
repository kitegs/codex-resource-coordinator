import subprocess

from coordinator.profiles import repository_key, ue_plan
from coordinator.store import conflicts


def test_ue_profiles_use_real_conflict_keys(tmp_path):
    (tmp_path / "Source").mkdir()
    compile_only = ue_plan(tmp_path, "compile-only")["resources"]
    editor = ue_plan(tmp_path, "editor-test")["resources"]
    cold = ue_plan(tmp_path, "cold-build")["resources"]
    performance = ue_plan(tmp_path, "performance")["resources"]
    assert not conflicts(compile_only, editor)
    assert conflicts(cold, editor)
    assert conflicts(compile_only, performance)
    assert conflicts(editor, performance)
    assert conflicts(ue_plan(tmp_path, "integrate")["resources"], compile_only)


def test_repository_identity_is_shared_but_source_outputs_are_independent(tmp_path):
    repo, branch = tmp_path / "main", tmp_path / "worktree"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test Fixture", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", "isolated", str(branch)], check=True, capture_output=True)
    assert repository_key(repo) == repository_key(branch)
    a = ue_plan(repo, "integrate")["resources"]
    b = ue_plan(branch, "integrate")["resources"]
    assert not conflicts(a, b)
