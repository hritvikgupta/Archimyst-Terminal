import os
import tempfile
import shutil
from pathlib import Path

class IgnorantTemporaryDirectory:
    def __init__(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def __enter__(self):
        return self.temp_dir.name

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.temp_dir.cleanup()
        except (OSError, PermissionError):
            pass

class ChdirTemporaryDirectory(IgnorantTemporaryDirectory):
    def __init__(self):
        try:
            self.cwd = os.getcwd()
        except FileNotFoundError:
            self.cwd = None
        super().__init__()

    def __enter__(self):
        res = super().__enter__()
        os.chdir(Path(self.temp_dir.name).resolve())
        return res

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cwd:
            try:
                os.chdir(self.cwd)
            except FileNotFoundError:
                pass
        super().__exit__(exc_type, exc_val, exc_tb)

def make_repo(path=None):
    import git
    if not path:
        path = "."
    repo = git.Repo.init(path)
    repo.config_writer().set_value("user", "name", "ArchCode User").release()
    repo.config_writer().set_value("user", "email", "user@archcode.ai").release()
    return repo

class GitTemporaryDirectory(ChdirTemporaryDirectory):
    def __enter__(self):
        dname = super().__enter__()
        self.repo = make_repo(dname)
        return dname

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, 'repo'):
            del self.repo
        super().__exit__(exc_type, exc_val, exc_tb)
