from __future__ import annotations

import time
from collections.abc import Callable

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey


class SignatureVerifier:
    """Verifies Discord's timestamp plus exact raw request-body signature."""

    def __init__(self, hex_public_key: str, *, now: Callable[[], float] | None = None) -> None:
        try:
            if len(hex_public_key) != 64:
                raise ValueError
            self._key = VerifyKey(bytes.fromhex(hex_public_key))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid Ed25519 public key configuration") from exc
        self._now = now or time.time

    def verify(self, signature: str | None, timestamp: str | None, raw_body: bytes | None) -> bool:
        if not signature or not timestamp or raw_body is None:
            return False
        try:
            issued_at = int(timestamp)
            if abs(int(self._now()) - issued_at) > 300:
                return False
            signed = timestamp.encode("utf-8") + raw_body
            self._key.verify(signed, bytes.fromhex(signature))
            return True
        except (BadSignatureError, TypeError, ValueError):
            return False
