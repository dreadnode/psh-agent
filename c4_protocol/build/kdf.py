"""
Shared KDF for deriving the salt from the operator's RSA public key.

Both the Python build pipeline and the C# runtime engine must produce
identical output for the same public key XML.

    normalized = strip_all_whitespace(public_key_xml)
    salt = HMAC-SHA256(key=normalized, msg="c4-salt").hex()[:64]

The result is a 64-character lowercase hex string (256 bits), used as the
encryption key for the configuration vault.
"""

import base64
import hashlib
import hmac


def derive_salt(public_key_b64: str, length: int = 64) -> str:
    """Derive a deterministic salt from a Base64 X25519 public key.

    Uses HMAC-SHA256 with the raw 32-byte key as HMAC key and "c4-salt"
    as message. Returns the first ``length`` hex characters.
    """
    try:
        key_bytes = base64.b64decode(public_key_b64)
    except Exception:
        # Fallback for old tests or random salts
        key_bytes = public_key_b64.encode("utf-8")

    digest = hmac.new(key_bytes, b"c4-salt", hashlib.sha256).hexdigest()
    return digest[:length]
