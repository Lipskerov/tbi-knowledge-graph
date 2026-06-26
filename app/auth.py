"""
Shared-password authentication for the TBI Knowledge Graph web app.

The app is gated behind a single lab-wide password. We never store the password
itself — only a salted PBKDF2-HMAC-SHA256 hash. Secrets live in environment
variables (loaded from a gitignored project-root `.env` for local/uvicorn runs;
injected by docker-compose `env_file` in the container):

    TBI_AUTH_PASSWORD_HASH   pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>
    TBI_SESSION_SECRET       random key that signs the session cookie
    TBI_HTTPS_ONLY           "1" to set the Secure cookie flag (enable behind TLS)
    TBI_SESSION_MAX_AGE      session lifetime in seconds (default 28800 = 8h)

Set or rotate the password with:

    python -m app.auth set-password            # prompts (hidden input)
    python -m app.auth set-password "secret"   # non-interactive

That writes the hash (and generates a session secret if absent) into `.env`,
then you restart the app:  docker compose up -d --build
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

PBKDF2_ITERATIONS = 600_000          # OWASP 2023 floor for PBKDF2-HMAC-SHA256
SESSION_MAX_AGE_DEFAULT = 28_800     # 8 hours

# Brute-force throttle (per client IP, in-process — resets on restart).
_LOCK_THRESHOLD = 5                  # failures before lockout kicks in
_LOCK_WINDOW = 300                   # seconds: failures older than this are forgotten
_LOCK_BASE = 30                      # base lockout seconds, doubles per extra failure
_LOCK_CAP = 900                      # max lockout (15 min)
_failures: dict[str, list[float]] = {}
_locked_until: dict[str, float] = {}


# ── .env loading ─────────────────────────────────────────────────────────────

def _load_dotenv() -> None:
    """Populate os.environ from project-root .env (without overriding real env)."""
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()


# ── password hashing ─────────────────────────────────────────────────────────

def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Return a self-describing PBKDF2 hash: pbkdf2_sha256:iters:salt:hash.

    The ``:`` delimiter (rather than the more common ``$``) is deliberate: this
    value is stored in ``.env`` and docker-compose treats ``$`` as variable
    interpolation, which would corrupt the hash before it reaches the container.
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256:{}:{}:{}".format(
        iterations, salt.hex(), dk.hex()
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify a password against a stored PBKDF2 hash."""
    try:
        scheme, iters_s, salt_hex, hash_hex = stored.split(":")
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


# ── config accessors ─────────────────────────────────────────────────────────

def get_password_hash() -> str | None:
    return os.environ.get("TBI_AUTH_PASSWORD_HASH") or None


def is_configured() -> bool:
    return bool(get_password_hash())


def get_session_secret() -> str:
    """Signing key for the session cookie. Generate an ephemeral one if unset
    (sessions then reset on restart) and warn — set TBI_SESSION_SECRET to persist."""
    sk = os.environ.get("TBI_SESSION_SECRET")
    if sk:
        return sk
    print(
        "[auth] WARNING: TBI_SESSION_SECRET not set — using an ephemeral key; "
        "logins will not survive a restart. Run `python -m app.auth set-password` "
        "to generate a persistent one.",
        file=sys.stderr,
    )
    return secrets.token_urlsafe(48)


def https_only() -> bool:
    return os.environ.get("TBI_HTTPS_ONLY", "0").lower() in ("1", "true", "yes", "on")


def session_max_age() -> int:
    try:
        return int(os.environ.get("TBI_SESSION_MAX_AGE", SESSION_MAX_AGE_DEFAULT))
    except ValueError:
        return SESSION_MAX_AGE_DEFAULT


# ── brute-force throttle ─────────────────────────────────────────────────────

def check_rate_limit(client: str) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds). Blocks a client during lockout."""
    now = time.monotonic()
    until = _locked_until.get(client, 0.0)
    if until > now:
        return False, int(until - now) + 1
    return True, 0


def register_failure(client: str) -> None:
    now = time.monotonic()
    hits = [t for t in _failures.get(client, []) if now - t < _LOCK_WINDOW]
    hits.append(now)
    _failures[client] = hits
    if len(hits) >= _LOCK_THRESHOLD:
        over = len(hits) - _LOCK_THRESHOLD
        lock = min(_LOCK_BASE * (2 ** over), _LOCK_CAP)
        _locked_until[client] = now + lock


def reset_rate_limit(client: str) -> None:
    _failures.pop(client, None)
    _locked_until.pop(client, None)


# ── .env writer + CLI ────────────────────────────────────────────────────────

def _write_env(updates: dict[str, str]) -> None:
    """Create/update keys in .env, preserving any other lines."""
    lines: list[str] = []
    seen: set[str] = set()
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            key = raw.split("=", 1)[0].strip() if "=" in raw else ""
            if key in updates:
                lines.append(f"{key}={updates[key]}")
                seen.add(key)
            else:
                lines.append(raw)
    for key, val in updates.items():
        if key not in seen:
            lines.append(f"{key}={val}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:  # tighten perms where supported (no-op on Windows)
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


def _cmd_set_password(argv: list[str]) -> int:
    if argv:
        pw = argv[0]
    else:
        import getpass
        pw = getpass.getpass("New shared password: ")
        if pw != getpass.getpass("Confirm password: "):
            print("Passwords did not match.", file=sys.stderr)
            return 1
    if len(pw) < 8:
        print("Refusing to set a password shorter than 8 characters.", file=sys.stderr)
        return 1

    updates = {"TBI_AUTH_PASSWORD_HASH": hash_password(pw)}
    if not os.environ.get("TBI_SESSION_SECRET") and "TBI_SESSION_SECRET" not in _existing_env_keys():
        updates["TBI_SESSION_SECRET"] = secrets.token_urlsafe(48)
    _write_env(updates)
    print(f"Password hash written to {ENV_FILE}")
    if "TBI_SESSION_SECRET" in updates:
        print("Generated a persistent TBI_SESSION_SECRET.")
    print("Restart the app to apply:  docker compose up -d --build")
    return 0


def _cmd_hash(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m app.auth hash <password>", file=sys.stderr)
        return 1
    print(hash_password(argv[0]))
    return 0


def _existing_env_keys() -> set[str]:
    if not ENV_FILE.exists():
        return set()
    return {
        line.split("=", 1)[0].strip()
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "set-password":
        return _cmd_set_password(rest)
    if cmd == "hash":
        return _cmd_hash(rest)
    print(f"Unknown command: {cmd}\n", file=sys.stderr)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
