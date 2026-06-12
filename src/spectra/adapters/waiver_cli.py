"""CLI subcommands for waiver authoring (#18) — ``spectra waive`` + ``spectra approver register``.

Layer 3 adapter. Composes the entity-layer Waiver/Approver models with
the infrastructure-layer ``YamlWaiverAdapter`` (signing) and two injected
ports: a keyring backend (private-key storage) and a ``SignerPort``
(Ed25519 keypair generation + public-key derivation). Both ports are
deferred behind setters so unit tests swap fakes in without touching the
OS keychain or the real ``cryptography`` stack.

Brand-voice: every ``✗`` line is ≤80 chars and explains what to do next.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import typer
import yaml
from rich.console import Console

from spectra.adapters.brand import AMBER, GREEN, RED, VIOLET
from spectra.entities.models import (
    Approver,
    Waiver,
    compute_finding_signature,
)
from spectra.use_cases.interfaces import SignerPort

console = Console()


_KEYRING_SERVICE = "spectra-approvers"
_DEFAULT_WAIVERS_FILE = Path(".spectra-waivers.yml")
_DEFAULT_APPROVERS_FILE = Path(".spectra-approvers.yml")


# ── Keyring backend (injectable for tests) ────────────────────


class KeyringBackend(Protocol):
    """Subset of the ``keyring`` module surface we consume here."""

    def get_password(self, service: str, account: str) -> str | None: ...

    def set_password(self, service: str, account: str, password: str) -> None: ...


class InMemoryKeyring:
    """Pure-memory keyring used in tests; satisfies ``KeyringBackend``."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self._store.get((service, account))

    def set_password(self, service: str, account: str, password: str) -> None:
        self._store[(service, account)] = password


_backend: KeyringBackend | None = None


def set_keyring_backend(backend: KeyringBackend | None) -> KeyringBackend | None:
    """Inject a keyring backend; returns the previous one for restore."""
    global _backend  # noqa: PLW0603
    previous = _backend
    _backend = backend
    return previous


def _get_backend() -> KeyringBackend:
    """Return the active backend (real keyring on first call if unset)."""
    global _backend  # noqa: PLW0603
    if _backend is None:
        try:
            import keyring as _kr
        except ImportError as exc:
            console.print(f"[{RED}]✗[/] keyring module unavailable: pip install keyring")
            raise typer.Exit(code=1) from exc
        _backend = _kr
    return _backend


# ── Signer port (injectable for tests) ────────────────────────


_signer: SignerPort | None = None


def set_signer(signer: SignerPort | None) -> SignerPort | None:
    """Inject a ``SignerPort`` implementation; returns the previous one for restore.

    The composition root wires the real ``Ed25519SignerAdapter``; tests
    pass an in-memory fake. Keeping the seam at the adapter boundary
    closes the dependency-rule break that previously had this module
    importing ``cryptography`` directly (Fix R3-Arch-3).
    """
    global _signer  # noqa: PLW0603
    previous = _signer
    _signer = signer
    return previous


def _get_signer() -> SignerPort:
    """Return the active signer (lazily binds the real adapter on first call)."""
    global _signer  # noqa: PLW0603
    if _signer is None:
        # Deferred import — ``cryptography`` lives in Layer 4 and would
        # otherwise create an adapters→infrastructure import cycle at
        # module load.
        from spectra.infrastructure.ed25519_signer import Ed25519SignerAdapter

        _signer = Ed25519SignerAdapter()
    return _signer


# ── Approver subcommands ──────────────────────────────────────

approver_app = typer.Typer(help="Manage signed-waiver approvers (#18)")


@approver_app.command("register")
def approver_register(
    name: str = typer.Option(..., "--name", help="Display name (matches Waiver.waived_by)"),
    email: str = typer.Option(..., "--email", help="Contact email recorded in .spectra-approvers.yml"),
    approvers_file: Path = typer.Option(  # noqa: B008
        _DEFAULT_APPROVERS_FILE,
        "--approvers-file",
        help="Path to .spectra-approvers.yml",
    ),
) -> None:
    """Generate an Ed25519 keypair and register the approver.

    Public key is appended to ``.spectra-approvers.yml``; the private
    key seed is stored in the OS keyring under ``spectra-approvers/<name>``.

    Both the keypair generation and the public-key re-derivation flow
    through the injected ``SignerPort`` — this module no longer imports
    ``cryptography`` directly (Fix R3-Arch-3).
    """
    backend = _get_backend()
    signer = _get_signer()
    existing_priv = backend.get_password(_KEYRING_SERVICE, name)
    if existing_priv is not None:
        console.print(f"[{AMBER}]⚠[/] Approver {name!r} already has a registered key; reusing it")
        priv_hex = existing_priv
        pub_hex = signer.derive_public_key(priv_hex)
    else:
        priv_hex, pub_hex = signer.generate_keypair()
        backend.set_password(_KEYRING_SERVICE, name, priv_hex)

    approver = Approver(name=name, email=email, public_key=pub_hex)
    _append_approver(approvers_file, approver)
    console.print(f"  [{GREEN}]✓[/] Registered approver {name} -> {approvers_file}")
    console.print(f"  [{VIOLET}]pubkey[/] {pub_hex}")


def _append_approver(path: Path, approver: Approver) -> None:
    """Write or append the approver entry to ``path`` as YAML."""
    data = _read_yaml_or_default(path, default={"version": 1, "approvers": []})
    entries: list[dict[str, str]] = list(data.get("approvers", []))
    # Replace existing entry with same name so re-registration is idempotent
    entries = [e for e in entries if e.get("name") != approver.name]
    entries.append({"name": approver.name, "email": approver.email, "public_key": approver.public_key})
    path.write_text(
        yaml.safe_dump({"version": 1, "approvers": entries}, sort_keys=False),
        encoding="utf-8",
    )


def _read_yaml_or_default(path: Path, *, default: dict[str, object]) -> dict[str, object]:
    """Read YAML at ``path`` or return ``default`` for missing/empty files."""
    if not path.exists():
        return default
    raw = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    if parsed is None:
        return default
    if not isinstance(parsed, dict):
        return default
    return parsed


# ── waive subcommand ─────────────────────────────────────────


def waive_command(
    file: str = typer.Option(..., "--file", help="Repo-relative path of the finding"),
    rule_id: str = typer.Option(..., "--rule-id", help="Finding rule_id to waive"),
    severity: str = typer.Option(..., "--severity", help="Severity literal (critical|high|medium|low|info)"),
    reason: str = typer.Option(..., "--reason", help="Justification (>=10 chars)"),
    waived_by: str = typer.Option(..., "--waived-by", help="Approver name (must be registered)"),
    waivers_file: Path = typer.Option(  # noqa: B008
        _DEFAULT_WAIVERS_FILE,
        "--waivers-file",
        help="Path to .spectra-waivers.yml",
    ),
    repo_signature: str = typer.Option(
        "0" * 32,
        "--repo-signature",
        help="32-hex repo signature (pin if known; default zero-pad for portability)",
    ),
) -> None:
    """Sign + append a waiver suppressing a single finding.

    The private key for ``--waived-by`` must already be registered via
    ``spectra approver register``. The waiver expires 180 days from now.
    """
    backend = _get_backend()
    private_hex = backend.get_password(_KEYRING_SERVICE, waived_by)
    if private_hex is None:
        console.print(
            f"[{RED}]✗[/] No registered key for {waived_by!r}: "
            "run 'spectra approver register --name "
            f"{waived_by} --email <email>' first"
        )
        raise typer.Exit(code=1)

    finding_sig = compute_finding_signature(file, rule_id, severity)
    now = datetime.now(UTC)
    try:
        waiver = Waiver(
            repo_signature=repo_signature,
            finding_signature=finding_sig,
            reason=reason,
            waived_by=waived_by,
            waived_at=now,
        )
    except ValueError as exc:
        console.print(f"[{RED}]✗[/] Invalid waiver: {exc}: see 'spectra waive --help'")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        # Pydantic ValidationError on reason length etc.
        console.print(f"[{RED}]✗[/] Invalid waiver: {exc}: reason needs >=10 chars")
        raise typer.Exit(code=1) from exc

    # Deferred import — break the adapters↔infrastructure circular at module load
    from spectra.infrastructure.yaml_waiver_adapter import YamlWaiverAdapter

    adapter = YamlWaiverAdapter()
    sig_hex = adapter.sign_waiver(waiver, private_hex)
    signed = waiver.model_copy(update={"signature": sig_hex})
    _append_waiver(waivers_file, signed)
    console.print(f"  [{GREEN}]✓[/] Waiver signed and appended to {waivers_file}")
    console.print(f"  [{VIOLET}]finding[/] {file}:{rule_id} ({severity})")


def _append_waiver(path: Path, waiver: Waiver) -> None:
    """Append a serialised waiver entry to ``path`` (creating it as needed)."""
    data = _read_yaml_or_default(path, default={"version": 1, "waivers": []})
    entries: list[dict[str, object]] = list(data.get("waivers", []))
    entries.append(
        {
            "repo_signature": waiver.repo_signature,
            "finding_signature": waiver.finding_signature,
            "reason": waiver.reason,
            "waived_by": waiver.waived_by,
            "waived_at": waiver.waived_at.isoformat(),
            "expires_at": waiver.expires_at.isoformat(),
            "signature": waiver.signature,
        }
    )
    path.write_text(
        yaml.safe_dump({"version": 1, "waivers": entries}, sort_keys=False),
        encoding="utf-8",
    )


__all__ = [
    "InMemoryKeyring",
    "approver_app",
    "set_keyring_backend",
    "set_signer",
    "waive_command",
]
