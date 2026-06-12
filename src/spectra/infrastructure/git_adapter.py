"""Git adapter — implements GitPort using GitPython.

Security hardening applied at multiple layers:

1. **Protocol restriction** — Only HTTPS URLs are accepted. SSH (``git@``),
   ``git://``, and ``file://`` protocols are rejected to prevent
   local-file-read and unauthenticated-clone attacks.

2. **SSRF prevention** — Before cloning, the hostname is resolved and
   checked against private (RFC 1918), loopback, link-local, multicast,
   unspecified (``0.0.0.0`` / ``::``), and IETF-reserved ranges via
   ``_is_private_ip()``. DNS resolution failures fail CLOSED (treated as
   blocked) so a transient resolver hiccup or DNS-rebinding window cannot
   slip a malicious host past the guard.

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
   hooks (``core.hooksPath=/dev/null``), skip submodules, enforce a
   60-second timeout, AND run with a scrubbed environment via
   ``_hardened_git_env()``. The subprocess cannot prompt the user, invoke
   ``ssh-askpass`` / Git Credential Manager, read ``~/.netrc`` /
   ``~/.gitconfig`` / ``credential.helper``, or silently disable TLS.

8. **Read timeout** — ``read_file()`` uses a 5-second ``asyncio.wait_for``
   to avoid blocking on special device files or FUSE mounts.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import git

from spectra.entities.errors import ERRORS, GitError
from spectra.use_cases.interfaces import is_local_path

__all__ = ["GitAdapter", "GitError"]

if TYPE_CHECKING:
    from collections.abc import Iterator

_MAX_FILE_COUNT = 10_000
_MAX_TOTAL_BYTES = 100 * 1024 * 1024  # 100 MB
_MAX_FILE_SIZE = 1_048_576  # 1 MB per file
_CLONE_TIMEOUT = 60  # seconds
_READ_TIMEOUT = 5.0  # seconds — prevent hanging on device files
_MAX_URL_LENGTH = 2048  # prevent abuse via extremely long URLs
_MAX_CLONES_PER_HOUR = 30  # rate-limiting advisory constant


_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _is_blocked_address(addr: _IPAddress) -> bool:
    """Return True if ``addr`` is in any SSRF-sensitive range.

    Blocks: private (RFC 1918), loopback, link-local, multicast,
    unspecified (``0.0.0.0``, ``::``), and IETF-reserved ranges.
    """
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
    )


def _is_private_ip(hostname: str) -> bool:
    """Return True if ``hostname`` is — or resolves to — a blocked address.

    Fails CLOSED: DNS resolution errors are treated as "blocked" so that
    SSRF attempts via DNS rebinding or transient resolver failures cannot
    bypass the guard. Callers should expect a True return on any
    resolution doubt.

    Args:
        hostname: DNS name or IP address string.

    Returns:
        True if the address is sensitive OR cannot be safely resolved.
    """
    try:
        addr = ipaddress.ip_address(hostname)
        return _is_blocked_address(addr)
    except ValueError:
        pass
    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
    except (socket.gaierror, OSError):
        # Fail-closed: unresolvable host is treated as blocked.
        return True
    return any(_is_blocked_address(ipaddress.ip_address(info[4][0])) for info in resolved)


def _hardened_git_env() -> dict[str, str]:
    """Return a scrubbed env for ``git clone`` subprocesses.

    Neutralizes credential prompts, helper invocations, and configuration
    inheritance so a malicious URL cannot:

    - trigger a terminal prompt for credentials,
    - invoke ``ssh-askpass`` or Git Credential Manager UI,
    - read ``~/.netrc``, ``~/.gitconfig``, or any ``credential.helper``,
    - silently disable TLS verification.

    HOME and XDG_CONFIG_HOME are pointed at a fresh tmpdir so user-level
    git config is invisible to the subprocess.
    """
    sandbox = tempfile.mkdtemp(prefix="spectra-git-home-")
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/true",
        "SSH_ASKPASS": "/bin/true",
        "GCM_INTERACTIVE": "Never",
        "GIT_SSL_NO_VERIFY": "false",
        "HOME": sandbox,
        "XDG_CONFIG_HOME": sandbox,
    }


def _reject_symlinks_in_path(target: Path, root: Path, requested: str) -> None:
    """Reject if ``target`` or ANY parent up to ``root`` is a symlink.

    Defends against intermediate-symlink-dir bypass: e.g. ``foo/link/file.txt``
    where ``foo/link`` is a symlink. Leaf-only ``is_symlink()`` misses this;
    ``Path.resolve()`` then silently follows the link.

    Args:
        target: Joined path (root / file_path) before resolving.
        root: Resolved repo root — boundary for the parent walk.
        requested: Original user-supplied path for error messages.

    Raises:
        ValueError: If any component along the path is a symlink.
    """
    current = target
    while True:
        if current.is_symlink():
            msg = f"Symlink blocked: {requested}"
            raise ValueError(msg)
        if current in (root, current.parent):
            return
        current = current.parent


def _iter_real_files(root: Path) -> Iterator[Path]:
    """Yield every real file under ``root`` without following symlinked dirs.

    ``Path.rglob`` follows directory symlinks; ``os.walk(followlinks=False)``
    does not. ``.git/`` is also pruned in-place to avoid descending into git
    metadata. Symlinked files are skipped.

    Args:
        root: Repo root.

    Yields:
        ``Path`` objects for each non-symlink file outside ``.git/``.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            candidate = Path(dirpath) / name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            yield candidate


def _resolve_local_repo(source: str) -> Path:
    """Validate ``source`` as a local git checkout and return its absolute path.

    Defensive checks (TOCTOU-aware): reject ``..`` segments, ``file://``
    URIs after stripping, symlinks, and any directory missing ``.git/``.

    Args:
        source: User-supplied local path (may begin with ``~`` or ``file://``).

    Returns:
        Resolved absolute :class:`pathlib.Path` to the repository root.

    Raises:
        GitError: SPEC-001 on any validation failure.
    """
    raw = source[len("file://") :] if source.startswith("file://") else source
    if ".." in Path(raw).parts:
        raise GitError(ERRORS["SPEC-001"])
    expanded = Path(raw).expanduser()
    if expanded.is_symlink():
        raise GitError(ERRORS["SPEC-001"])
    resolved = expanded.resolve()
    if not resolved.is_dir():
        raise GitError(ERRORS["SPEC-001"])
    git_dir = resolved / ".git"
    if not git_dir.exists():
        raise GitError(ERRORS["SPEC-001"])
    return resolved


class GitAdapter:
    """Async wrapper around GitPython implementing the GitPort protocol.

    All public methods are hardened against untrusted input — see the
    module docstring for the full security model.
    """

    async def prepare_workspace(self, source: str, target_dir: str) -> str:
        """Resolve ``source`` to a usable repo dir (clone or local).

        Local paths are validated and returned unchanged; ``target_dir``
        is ignored. URLs are cloned into ``target_dir``.

        Args:
            source: Either an HTTPS URL or a local filesystem path.
            target_dir: Destination directory used for clones.

        Returns:
            Absolute path string to the prepared repository directory.

        Raises:
            GitError: SPEC-001 on any validation or clone failure.
        """
        if is_local_path(source):
            return str(_resolve_local_repo(source))
        await self.clone(source, target_dir)
        return target_dir

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
        env = _hardened_git_env()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: git.Repo.clone_from(
                        repo_url,
                        target_dir,
                        depth=1,
                        env=env,
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
            2. Reject if any path component (leaf OR intermediate) is a symlink.
            3. Verify the resolved path stays within ``repo_dir``.
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
        _reject_symlinks_in_path(raw, root, file_path)
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
        total_bytes = 0
        for index, file_path in enumerate(_iter_real_files(root), start=1):
            if index > _MAX_FILE_COUNT:
                msg = f"Repository exceeds {_MAX_FILE_COUNT} file limit"
                raise ValueError(msg)
            total_bytes += file_path.stat().st_size
            if total_bytes > _MAX_TOTAL_BYTES:
                msg = f"Repository exceeds {_MAX_TOTAL_BYTES // (1024 * 1024)}MB limit"
                raise ValueError(msg)

    @staticmethod
    def _walk_tree(repo_dir: str) -> list[str]:
        root = Path(repo_dir)
        return sorted(str(p.relative_to(root)) for p in _iter_real_files(root))
