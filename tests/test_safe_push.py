from pathlib import Path
from contextlib import ExitStack
from tempfile import TemporaryDirectory
import unittest

from git import Repo

from scripts._common import DataRepoManager


class SafePush(unittest.TestCase):
    def test_selected_output_deletions_are_committed(self):
        with TemporaryDirectory() as directory, ExitStack() as resources:
            repo = Repo.init(directory)
            resources.callback(repo.close)
            with repo.config_writer() as config:
                config.set_value("user", "name", "Test")
                config.set_value("user", "email", "test@example.invalid")
            status = Path(directory) / "unity/.parse-status.json"
            status.parent.mkdir()
            status.write_text("stale")
            (status.parent / "config.json").write_text("{}")
            repo.index.add(["unity/.parse-status.json", "unity/config.json"])
            repo.index.commit("old status")
            manager = DataRepoManager.from_checkout(directory)
            resources.callback(manager.repo.close)
            status.unlink()
            self.assertTrue(manager.commit("clear validated status", files=["unity"]))
            self.assertEqual(
                manager.repo.git.ls_tree("-r", "--name-only", "HEAD"),
                "unity/config.json",
            )
            (Path(directory) / "unrelated").write_text("leave uncommitted")
            self.assertFalse(
                manager.commit("must not create empty commit", files=["unity"])
            )

    def test_admin_advance_preserved_and_data_advance_blocks(self):
        for path, allowed in [
            (".github/workflows/test.yml", True),
            ("unity/new.json", False),
        ]:
            with (
                self.subTest(path=path),
                TemporaryDirectory() as directory,
                ExitStack() as resources,
            ):
                root = Path(directory)
                origin = Repo.init(root / "origin.git", bare=True)
                resources.callback(origin.close)
                one = Repo.clone_from(origin.git_dir, root / "one")
                resources.callback(one.close)
                with one.config_writer() as config:
                    config.set_value("user", "name", "Test")
                    config.set_value("user", "email", "test@example.invalid")
                (root / "one/base").write_text("base")
                one.index.add(["base"])
                one.index.commit("base")
                one.git.branch("-M", "main")
                one.git.push("origin", "HEAD:refs/heads/main")
                other = Repo.clone_from(origin.git_dir, root / "other", branch="main")
                resources.callback(other.close)
                with other.config_writer() as config:
                    config.set_value("user", "name", "Test")
                    config.set_value("user", "email", "test@example.invalid")
                manager = DataRepoManager.from_checkout(str(root / "one"))
                resources.callback(manager.repo.close)
                (root / "one/resource").write_text("validated")
                one.index.add(["resource"])
                one.index.commit("resource")
                remote_file = root / "other" / path
                remote_file.parent.mkdir(parents=True, exist_ok=True)
                remote_file.write_text("remote")
                other.index.add([path])
                other.index.commit("advance")
                other.git.push("origin", "HEAD:refs/heads/main")
                if allowed:
                    self.assertTrue(manager.push(branch="main"))
                    self.assertEqual((root / "one" / path).read_text(), "remote")
                else:
                    with self.assertRaisesRegex(RuntimeError, "Remote data changed"):
                        manager.push(branch="main")
                manager.repo.close()
                one.close()
                other.close()
                origin.close()
