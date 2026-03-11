"""
Shared KDF for deriving the salt from the operator's RSA public key.

Both the Python build pipeline and the C# runtime engine must produce
identical output for the same public key XML.

    normalized = strip_all_whitespace(public_key_xml)
    salt = HMAC-SHA256(key=normalized, msg="c4-salt").hex()[:12]

The result is a 12-character lowercase hex string (48 bits), used as the
activation token that differentiates real from decoy model inputs.
"""

import hashlib
import hmac
import re


def derive_salt(public_key_xml: str, length: int = 12) -> str:
    """Derive a deterministic salt from an RSA public key XML string.

    Normalizes the XML by stripping all whitespace, then uses
    HMAC-SHA256 with the normalized key as HMAC key and "c4-salt"
    as message.  Returns the first ``length`` hex characters.
    """
    normalized = re.sub(r"\s", "", public_key_xml)
    digest = hmac.new(
        normalized.encode("utf-8"), b"c4-salt", hashlib.sha256
    ).hexdigest()
    return digest[:length]
