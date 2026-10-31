"""Lock the API keys into an encrypted file that is safe to keep in the repo, and unlock them on setup.

    python keys_vault.py lock      (owner) encrypt .env + Google key into keys.vault
    python keys_vault.py unlock    (team)  ask for the passphrase and restore .env + Google key
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import secrets
import sys

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from lead_agent.common import ROOT

VAULT = ROOT / "keys.vault"
ENV = ROOT / ".env"
GOOGLE = ROOT / "secrets" / "google_service_account.json"


def _fernet(passphrase: str, salt: bytes) -> Fernet:
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def lock(passphrase: str) -> None:
    payload = json.dumps({"env": ENV.read_text(encoding="utf-8"), "google": GOOGLE.read_text(encoding="utf-8")})
    salt = secrets.token_bytes(16)
    token = _fernet(passphrase, salt).encrypt(payload.encode())
    VAULT.write_text(json.dumps({"salt": base64.b64encode(salt).decode(), "data": token.decode()}), encoding="utf-8")
    print(f"Locked keys into {VAULT.name}")


def unlock(passphrase: str) -> None:
    vault = json.loads(VAULT.read_text(encoding="utf-8"))
    try:
        payload = json.loads(_fernet(passphrase, base64.b64decode(vault["salt"])).decrypt(vault["data"].encode()))
    except InvalidToken:
        sys.exit("Wrong passphrase. Run the setup again and type it exactly.")
    GOOGLE.parent.mkdir(exist_ok=True)
    for path, text in ((ENV, payload["env"]), (GOOGLE, payload["google"])):
        path.write_text(text, encoding="utf-8")
        os.chmod(path, 0o600)
    print("Keys unlocked: .env and secrets/google_service_account.json are in place.")


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "lock":
        passphrase = os.environ.get("VAULT_PASSPHRASE") or getpass.getpass("Choose a passphrase: ")
        lock(passphrase)
    elif action == "unlock":
        has_key = ENV.exists() and any(l.startswith("INSTANTLY_API_KEY=") and len(l.strip()) > 18
                                       for l in ENV.read_text().splitlines())
        if has_key and GOOGLE.exists():
            if os.environ.get("VAULT_FORCE") != "1":
                print("Keys already set up on this computer; skipping unlock.")
                return
        if not VAULT.exists():
            print("No keys.vault in this folder yet. Ask Mahaveer for the keys; everything else is installed.")
            return
        unlock(os.environ.get("VAULT_PASSPHRASE") or getpass.getpass("Passphrase (ask Mahaveer): "))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
