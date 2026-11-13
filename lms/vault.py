"""Encrypted JSON files, so a PUBLIC repo can hold private data.

Format (text, JSON): {"v":1,"salt":b64,"iv":b64,"ct":b64}
AES-256-GCM, key = PBKDF2-HMAC-SHA256(passphrase, salt, 200k iterations). `ct` is ciphertext||tag,
which is exactly what the browser's WebCrypto AES-GCM expects, so the panel can decrypt it.
"""
import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 200_000


class VaultError(Exception):
    pass


def _key(passphrase, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(
        passphrase.encode("utf-8"))


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def encrypt(obj, passphrase):
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(passphrase, salt)).encrypt(iv, canonical(obj).encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return json.dumps({"v": 1, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)})


def decrypt(text, passphrase):
    try:
        d = json.loads(text)
        salt, iv, ct = (base64.b64decode(d[k]) for k in ("salt", "iv", "ct"))
        return json.loads(AESGCM(_key(passphrase, salt)).decrypt(iv, ct, None).decode("utf-8"))
    except (InvalidTag, ValueError, KeyError):
        raise VaultError("cannot decrypt (wrong DATA_KEY or corrupted file)")


def load(path, passphrase, default=None):
    """Return (object, canonical_text_or_None). Missing file -> (default, None)."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return default, None
    obj = decrypt(text, passphrase)
    return obj, canonical(obj)


def save_if_changed(path, obj, passphrase, previous_canonical):
    """Write only when the content changed (fresh random IV would otherwise dirty git every run)."""
    if canonical(obj) == previous_canonical:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(encrypt(obj, passphrase) + "\n")
    return True
