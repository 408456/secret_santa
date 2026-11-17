from __future__ import annotations

import re
import secrets
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from collections.abc import AsyncIterator

import aiosqlite

from .algorithm import make_draw


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().lower().replace("ё", "е")
    return re.sub(r"\s+", " ", value)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
        finally:
            await conn.close()

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as conn:
            await conn.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    creator_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    budget TEXT,
                    exchange_date TEXT,
                    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'drawn')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    wish TEXT,
                    photo_file_id TEXT,
                    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(game_id, user_id),
                    UNIQUE(game_id, normalized_name)
                );
                CREATE TABLE IF NOT EXISTS exclusions (
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    participant_a INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
                    participant_b INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
                    CHECK(participant_a < participant_b),
                    PRIMARY KEY(game_id, participant_a, participant_b)
                );
                CREATE TABLE IF NOT EXISTS assignments (
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    giver_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
                    receiver_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
                    PRIMARY KEY(game_id, giver_id),
                    UNIQUE(game_id, receiver_id),
                    CHECK(giver_id <> receiver_id)
                );
                """
            )
            await conn.commit()

    async def _one(self, query: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        async with self.connect() as conn:
            async with conn.execute(query, params) as cursor:
                return await cursor.fetchone()

    async def _all(self, query: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        async with self.connect() as conn:
            async with conn.execute(query, params) as cursor:
                return await cursor.fetchall()

    async def create_game(self, creator_id: int, title: str, budget: str | None, exchange_date: str | None) -> aiosqlite.Row:
        async with self.connect() as conn:
            for _ in range(20):
                code = secrets.token_hex(3).upper()
                try:
                    cursor = await conn.execute(
                        "INSERT INTO games(code, creator_id, title, budget, exchange_date) VALUES(?,?,?,?,?)",
                        (code, creator_id, title, budget, exchange_date),
                    )
                    await conn.commit()
                    return await self.get_game(cursor.lastrowid)
                except aiosqlite.IntegrityError:
                    continue
        raise RuntimeError("Не удалось создать уникальный код игры")

    async def get_game(self, game_id: int) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM games WHERE id=?", (game_id,))

    async def get_game_by_code(self, code: str) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM games WHERE code=?", (code.strip().upper(),))

    async def user_games(self, user_id: int) -> list[aiosqlite.Row]:
        return await self._all(
            """SELECT DISTINCT g.* FROM games g LEFT JOIN participants p ON p.game_id=g.id
               WHERE g.creator_id=? OR p.user_id=? ORDER BY g.created_at DESC""",
            (user_id, user_id),
        )

    async def participants(self, game_id: int) -> list[aiosqlite.Row]:
        return await self._all("SELECT * FROM participants WHERE game_id=? ORDER BY joined_at, id", (game_id,))

    async def participant(self, game_id: int, user_id: int) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM participants WHERE game_id=? AND user_id=?", (game_id, user_id))

    async def add_participant(self, game_id: int, user_id: int, name: str, wish: str | None, photo_file_id: str | None) -> None:
        async with self.connect() as conn:
            await conn.execute(
                "INSERT INTO participants(game_id,user_id,name,normalized_name,wish,photo_file_id) VALUES(?,?,?,?,?,?)",
                (game_id, user_id, name.strip(), normalize_name(name), wish, photo_file_id),
            )
            await conn.commit()

    async def leave(self, game_id: int, user_id: int) -> bool:
        async with self.connect() as conn:
            cursor = await conn.execute(
                "DELETE FROM participants WHERE game_id=? AND user_id=? AND EXISTS(SELECT 1 FROM games WHERE id=? AND status='open')",
                (game_id, user_id, game_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def add_exclusion(self, game_id: int, first: int, second: int) -> None:
        left, right = sorted((first, second))
        async with self.connect() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO exclusions(game_id,participant_a,participant_b) VALUES(?,?,?)",
                (game_id, left, right),
            )
            await conn.commit()

    async def exclusions(self, game_id: int) -> list[aiosqlite.Row]:
        return await self._all(
            """SELECT e.*, a.name AS name_a, b.name AS name_b FROM exclusions e
               JOIN participants a ON a.id=e.participant_a JOIN participants b ON b.id=e.participant_b
               WHERE e.game_id=? ORDER BY a.name,b.name""",
            (game_id,),
        )

    async def draw(self, game_id: int) -> list[aiosqlite.Row]:
        async with self.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            game = await (await conn.execute("SELECT * FROM games WHERE id=?", (game_id,))).fetchone()
            if not game or game[6] != "open":
                await conn.rollback()
                raise ValueError("Игра уже запущена или не существует")
            participants = await (await conn.execute("SELECT * FROM participants WHERE game_id=?", (game_id,))).fetchall()
            if len(participants) < 3:
                await conn.rollback()
                raise ValueError("Для жеребьёвки нужно минимум 3 участника")
            exclusions = await (await conn.execute(
                "SELECT participant_a,participant_b FROM exclusions WHERE game_id=?", (game_id,)
            )).fetchall()
            assignment = make_draw([row[0] for row in participants], [(r[0], r[1]) for r in exclusions])
            await conn.executemany(
                "INSERT INTO assignments(game_id,giver_id,receiver_id) VALUES(?,?,?)",
                [(game_id, giver, receiver) for giver, receiver in assignment.items()],
            )
            await conn.execute("UPDATE games SET status='drawn' WHERE id=?", (game_id,))
            await conn.commit()
        return await self.assignment_rows(game_id)

    async def assignment_rows(self, game_id: int) -> list[aiosqlite.Row]:
        return await self._all(
            """SELECT giver.user_id AS giver_user_id, receiver.name, receiver.wish, receiver.photo_file_id
               FROM assignments x JOIN participants giver ON giver.id=x.giver_id
               JOIN participants receiver ON receiver.id=x.receiver_id WHERE x.game_id=?""",
            (game_id,),
        )

    async def result(self, game_id: int, user_id: int) -> aiosqlite.Row | None:
        return await self._one(
            """SELECT receiver.name,receiver.wish,receiver.photo_file_id FROM assignments x
               JOIN participants giver ON giver.id=x.giver_id JOIN participants receiver ON receiver.id=x.receiver_id
               WHERE x.game_id=? AND giver.user_id=?""",
            (game_id, user_id),
        )

    async def delete_game(self, game_id: int, creator_id: int) -> bool:
        async with self.connect() as conn:
            cursor = await conn.execute("DELETE FROM games WHERE id=? AND creator_id=?", (game_id, creator_id))
            await conn.commit()
            return cursor.rowcount > 0

