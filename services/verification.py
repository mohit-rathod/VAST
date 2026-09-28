"""Short-lived, one-use verification challenges; transport is injected.

No OTP is returned in a tool result or logged. The existing email must receive
it before a record can be displayed, its contacts changed or bookings listed.
This is a single-process demo implementation, not a distributed identity system.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from hashlib import sha256
import hmac
import secrets
import threading
import time
from typing import Callable, Protocol


class CodeSender(Protocol):
    def send(self, email: str, code: str) -> None: ...


class VerificationUnavailable(RuntimeError):
    pass


@dataclass
class Challenge:
    patient_id: int
    purpose: str
    fingerprint: tuple[str, str | None]
    digest: str = field(repr=False)
    salt: str = field(repr=False)
    expires_at: float = 0
    attempts: int = 0
    consumed: bool = False


class VerificationService:
    def __init__(self, sender: CodeSender, clock: Callable[[], float] = time.monotonic,
                 ttl_seconds: int = 600, max_attempts: int = 5) -> None:
        self.sender, self.clock = sender, clock
        self.ttl_seconds, self.max_attempts = ttl_seconds, max_attempts
        self._sent: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def issue(self, patient: dict, purpose: str) -> Challenge:
        email = patient["email"]
        with self._lock:
            now = self.clock()
            key = sha256(email.encode()).hexdigest()
            times = [t for t in self._sent.get(key, []) if now - t < 3600]
            if times and (now - times[-1] < 60 or len(times) >= 5):
                raise VerificationUnavailable("Please wait before requesting another code; at most five codes are sent per hour.")
            self._sent[key] = [*times, now]
            self._sent.move_to_end(key)
            while len(self._sent) > 4096:
                self._sent.popitem(last=False)
        code, salt = f"{secrets.randbelow(1000000):06d}", secrets.token_hex(16)
        try:
            self.sender.send(email, code)
        except Exception as error:
            raise VerificationUnavailable("Email verification is unavailable. Contact the clinic to recover your account; no details were changed.") from error
        return Challenge(patient["id"], purpose, (patient["email"], patient["phone"]),
                         sha256((salt + code).encode()).hexdigest(), salt, now + self.ttl_seconds)

    def verify(self, challenge: Challenge, code: str) -> bool:
        if challenge.consumed or self.clock() >= challenge.expires_at or challenge.attempts >= self.max_attempts:
            return False
        challenge.attempts += 1
        valid = len(code) == 6 and code.isascii() and code.isdigit()
        digest = sha256((challenge.salt + code).encode()).hexdigest()
        if not valid or not hmac.compare_digest(digest, challenge.digest):
            return False
        challenge.consumed = True
        return True