"""Application-level file capabilities, not an OS sandbox or code runner."""

import os
import re
from contextlib import contextmanager, suppress
from hashlib import sha256
from pathlib import Path
from threading import RLock

TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json"}
FILE_EXTENSIONS = TEXT_EXTENSIONS | {".xlsx", ".png", ".jpg", ".webp"}
_lock = RLock()


class SessionFiles:
    def __init__(
        self,
        root: Path,
        thread_id: str,
        *,
        max_file: int = 10_485_760,
        max_total: int = 104_857_600,
        max_files: int = 200,
        max_text: int = 262_144,
    ):
        if not re.fullmatch(r"[a-f0-9]{32}", thread_id):
            raise ValueError("Invalid session identifier")
        self.root = Path(root).absolute()
        self.thread_id = thread_id
        self.max_file, self.max_total = max_file, max_total
        self.max_files, self.max_text = max_files, max_text

    @contextmanager
    def directory(self):
        # Configured root is trusted, but none of its path components may be
        # symlinks. All model-selected files are flat names, opened via dir_fd.
        with _lock:
            for part in [*reversed(self.root.parents), self.root]:
                if part.is_symlink():
                    raise ValueError("Workspace root must not contain symbolic links")
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                with suppress(FileExistsError):
                    os.mkdir(self.thread_id, mode=0o700, dir_fd=root_fd)
                fd = os.open(
                    self.thread_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
                )
                try:
                    yield fd
                finally:
                    os.close(fd)
            finally:
                os.close(root_fd)

    @staticmethod
    def validate_name(name: str, text_only: bool = False) -> str:
        if (
            not name
            or len(name.encode()) > 200
            or name.startswith(".")
            or any(char in name for char in ("/", "\\", "\x00", ":"))
            or any(ord(char) < 32 for char in name)
        ):
            raise ValueError(
                "Use a relative filename only; directories and hidden files are forbidden"
            )
        allowed = TEXT_EXTENSIONS if text_only else FILE_EXTENSIONS
        if Path(name).suffix.lower() not in allowed:
            raise ValueError(f"Allowed extensions: {sorted(allowed)}")
        return name

    def list(self) -> list[dict]:
        import stat

        with self.directory() as fd:
            result = []
            for name in sorted(os.listdir(fd)):
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and not name.startswith("."):
                    result.append({"path": name, "size_bytes": info.st_size})
            return result

    def write(self, name: str, content: bytes, *, text_only: bool = False) -> dict:
        self.validate_name(name, text_only)
        if len(content) > (min(self.max_text, self.max_file) if text_only else self.max_file):
            raise ValueError("File exceeds workspace size limit")
        with self.directory() as fd:
            info = [os.stat(n, dir_fd=fd, follow_symlinks=False) for n in os.listdir(fd)]
            if (
                len(info) >= self.max_files
                or sum(i.st_size for i in info) + len(content) > self.max_total
            ):
                raise ValueError("Session workspace quota exceeded")
            file_fd = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
            try:
                with os.fdopen(file_fd, "wb") as file:
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())
            except BaseException:
                os.unlink(name, dir_fd=fd)
                raise
        return {
            "relative_path": name,
            "size_bytes": len(content),
            "sha256": sha256(content).hexdigest(),
        }

    def read(self, name: str, *, text_only: bool = False) -> bytes:
        import stat

        self.validate_name(name, text_only)
        limit = min(self.max_text, self.max_file) if text_only else self.max_file
        with self.directory() as fd:
            file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, "rb") as file:
                info = os.fstat(file.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
                    raise ValueError("File is not regular or exceeds read limit")
                content = file.read(limit + 1)
                if len(content) > limit:
                    raise ValueError("File exceeds read limit")
                return content
