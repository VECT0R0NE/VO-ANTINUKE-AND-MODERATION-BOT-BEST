import aiosqlite
import os
import time


class WarnsDatabase:
    def __init__(self):
        self.db_path = 'data/warns.db'

    async def initialize(self):
        os.makedirs('data', exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            ''')
            # Index for fast lookup by guild + user
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_guild_user
                ON warnings (guild_id, user_id)
            ''')
            await db.commit()

    async def add_warn(self, guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'INSERT INTO warnings (guild_id, user_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?, ?)',
                (guild_id, user_id, moderator_id, reason, int(time.time()))
            )
            await db.commit()
            return cursor.lastrowid

    async def get_warns(self, guild_id: int, user_id: int):
        """Returns list of (id, moderator_id, reason, timestamp)"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT id, moderator_id, reason, timestamp FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC',
                (guild_id, user_id)
            ) as cursor:
                return await cursor.fetchall()

    async def get_warn_count(self, guild_id: int, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?',
                (guild_id, user_id)
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0

    async def get_warn_by_id(self, guild_id: int, warn_id: int):
        """Returns (user_id, reason) or None"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT user_id, reason FROM warnings WHERE id = ? AND guild_id = ?',
                (warn_id, guild_id)
            ) as cursor:
                return await cursor.fetchone()

    async def remove_warn(self, guild_id: int, warn_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'DELETE FROM warnings WHERE id = ? AND guild_id = ?',
                (warn_id, guild_id)
            )
            await db.commit()

    async def clear_warns(self, guild_id: int, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'DELETE FROM warnings WHERE guild_id = ? AND user_id = ?',
                (guild_id, user_id)
            )
            await db.commit()