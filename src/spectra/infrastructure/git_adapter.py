"""Git adapter — implements GitPort using GitPython.

Security hardening applied at multiple layers:

1. **Protocol restriction** — Only HTTPS URLs are accepted. SSH (``git@``),
   ``git://``, and ``file://`` protocols are rejected to prevent
   local-file-read and unauthenticated-clone attacks.

2. **SSRF prevention** — Before cloning, the hostname is resolved and
   checked against private (RFC 1918), loopback (127.x), and link-local
   (169.254.x) IP ranges via ``_is_private_ip()``. This blocks requests
   to internal services even when hidden behind DNS.

3. **URL length cap** — URLs longer than 2 048 characters are rejected to
   prevent header-overflow and log-injection attacks.

4. **Path traversal protection** — ``read_file()`` resolves the requested
   path *after* joining it with the repo root, then verifies the resolved
   path is still within the repo via ``Path.is_relative_to()``. Paths
   containing null bytes or starting with ``/`` are also rejected.

5. **Symlink blocking** — Symlinks are skipped during tree walks and
   explicitly rejected in ``read_file()`` to prevent symlink-based
   directory-escape attacks.

6. **Size limits** — Individual files are capped at 1 MB; repositories
   are capped at 10 000 files and 100 MB total to prevent resource
   exhaustion (zip-bomb style repos).

7. **Clone hardening** — Clones are shallow (``depth=1``), disable Git
   hooks (``core.hooksPath=/dev/null``), skip submodules, and enforce a
   60-second timeout to prevent hanging on slow or malicious remotes.

8. **Read timeout** — ``read_file()`` uses a 5-second ``asyncio.wait_for``
   to avoid blocking on special device files or FUSE mounts.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

import git

from spectra.entities.errors import ERRORS, GitError

_MAX_FILE_COUNT = 10_000
_MAX_TOTAL_BYTES = 100 * 1024 * 1024  # 100 MB
_MAX_FILE_SIZE = 1_048_576  # 1 MB per file
_CLONE_TIMEOUT = 60  # seconds
_READ_TIMEOUT = 5.0  # seconds — prevent hanging on device files
_MAX_URL_LENGTH = 2048  # prevent abuse via extremely long URLs
_MAX_CLONES_PER_HOUR = 30  # rate-limiting advisory constant


def _is_private_ip(hostname: str) -> bool:
    """Return True if hostname resolves to a private/loopback/link-local IP.

    Prevents SSRF by blocking clones to internal network addresses.

    Args:
        hostname: DNS name or IP address string.

    Returns:
        True if the address is private, loopback, or link-local.
    """
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        pass
    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
        return any(
            ipaddress.ip_address(info[4][0]).is_private
            or ipaddress.ip_address(info[4][0]).is_loopback
            or ipaddress.ip_address(info[4][0]).is_link_local
            for info in resolved
        )
    except (socket.gaierror, OSError):
        return False


class GitAdapter:
    """Async wrapper around GitPython implementing the GitPort protocol.

    All public methods are hardened against untrusted input — see the
    module docstring for the full security model.
    """

    async def clone(self, repo_url: str, target_dir: str) -> None:
        """Clone a repository with security hardening.

        Security checks applied (in order):
            1. URL length ≤ 2 048 characters.
            2. Protocol must be ``https://``.
            3. Hostname resolved and checked against private/loopback IPs.
            4. Shallow clone (``depth=1``), Git hooks disabled, no submodules.
            5. 60-second timeout via ``asyncio.wait_for``.

        Raises:
            GitError: SPEC-001 on any validation or clone failure.
        """
        if len(repo_url) > _MAX_URL_LENGTH:
            raise GitError(ERRORS["SPEC-001"])
        if not repo_url.startswith("https://"):
            raise GitError(ERRORS["SPEC-001"])
        parsed = urlparse(repo_url)
        hostname = parsed.hostname or ""
        if not hostname or _is_private_ip(hostname):
            raise GitError(ERRORS["SPEC-001"])
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: git.Repo.clone_from(
                        repo_url,
                        target_dir,
                        depth=1,
                        allow_unsafe_options=True,
                        multi_options=[
                            "--config core.hooksPath=/dev/null",
                            "--no-recurse-submodules",
                        ],
                    ),
                ),
                timeout=_CLONE_TIMEOUT,
            )
        except TimeoutError:
            raise GitError(ERRORS["SPEC-001"]) from None
        except git.GitCommandError as exc:
            raise GitError(ERRORS["SPEC-001"]) from exc

    async def get_file_tree(self, repo_dir: str) -> list[str]:
        """Return a sorted list of all file paths in the repository.

        Args:
            repo_dir: Absolute path to the cloned repo.

        Returns:
            Sorted repository-relative file paths (excludes ``.git/``).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._walk_tree, repo_dir)

    async def read_file(self, repo_dir: str, file_path: str) -> str:
        """Read a single file from the cloned repository.

        Security checks applied (in order):
            1. Reject null bytes and absolute paths.
            2. Reject symlinks (before resolving).
            3. Resolve and verify the path stays within ``repo_dir``.
            4. Reject files larger than 1 MB.
            5. 5-second read timeout.

        Raises:
            ValueError: On any security violation or size limit breach.
        """
        if "\0" in file_path or file_path.startswith("/"):
            msg = f"Invalid file path: {file_path!r}"
            raise ValueError(msg)
        root = Path(repo_dir).resolve()
        raw = root / file_path
        if raw.is_symlink():
            msg = f"Symlink blocked: {file_path}"
            raise ValueError(msg)
        full = raw.resolve()
        if not full.is_relative_to(root):
            msg = f"Path traversal blocked: {file_path}"
            raise ValueError(msg)
        if full.stat().st_size > _MAX_FILE_SIZE:
            msg = f"File exceeds {_MAX_FILE_SIZE} byte limit: {file_path}"
            raise ValueError(msg)
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, full.read_text, "utf-8"),
            timeout=_READ_TIMEOUT,
        )

    async def validate_repo_size(self, repo_dir: str) -> None:
        """Reject repos exceeding file count or total size limits.

        Args:
            repo_dir: Absolute path to the cloned repo.

        Raises:
            ValueError: If the repo exceeds 10K files or 100 MB.
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._check_size, repo_dir)

    @staticmethod
    def _check_size(repo_dir: str) -> None:
        root = Path(repo_dir)
        count = 0
        total_bytes = 0
        for p in root.rglob("*"):
            if p.is_symlink() or not p.is_file() or ".git" in p.parts:
                continue
            count += 1
            if count > _MAX_FILE_COUNT:
                msg = f"Repository exceeds {_MAX_FILE_COUNT} file limit"
                raise ValueError(msg)
            total_bytes += p.stat().st_size
            if total_bytes > _MAX_TOTAL_BYTES:
                msg = f"Repository exceeds {_MAX_TOTAL_BYTES // (1024 * 1024)}MB limit"
                raise ValueError(msg)

    @staticmethod
    def _walk_tree(repo_dir: str) -> list[str]:
        root = Path(repo_dir)
        return sorted(
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.is_file() and not p.is_symlink() and ".git" not in p.parts
        )
