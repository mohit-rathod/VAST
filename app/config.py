# Settings, read from the environment or from a .env file in the project root.
# Copy .env.example to .env and fill in your key. .env is gitignored.

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("VAST_MODEL", "gpt-4o-mini")

# The release this working tree is. Bump it when the behaviour changes.
VERSION = "0.2.3"


def email_verification_required() -> bool:
    """Compatibility hook: email-code verification is removed.

    The old VAST_REQUIRE_EMAIL_VERIFICATION variable is intentionally ignored,
    including when an existing .env still sets it to true. This application
    uses explicit in-chat confirmation, not proof of email ownership.
    """
    return False


# Keep VAST_MODEL unchanged: it remains the model used by the NextDim agent.
REALTIME_MODEL = os.getenv("VAST_REALTIME_MODEL", "gpt-realtime")
REALTIME_VOICE = os.getenv("VAST_REALTIME_VOICE", "marin")
