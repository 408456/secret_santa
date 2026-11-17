from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    bot_username: str
    database_path: Path
    assets_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and add it.")
        return cls(
            bot_token=token,
            bot_username=os.getenv("BOT_USERNAME", "secret_2g_santa_bot").strip().lstrip("@"),
            database_path=Path(os.getenv("DATABASE_PATH", "data/secret_santa.db")),
            assets_dir=Path(os.getenv("ASSETS_DIR", "assets")),
        )

