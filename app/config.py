# Settings, read from the environment or from a .env file in the project root.
# Copy .env.example to .env and fill in your key. .env is gitignored.

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("VAST_MODEL", "gpt-4o-mini")

# The release this working tree is. Bump it when the behaviour changes.
VERSION = "0.1.0"
