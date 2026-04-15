import aiosqlite
import os
import time
import json


class JailDatabase:
    def __init__(self):
        self.db_path = 'data/jail.db'

    async def initialize(self):
        os.makedirs('data', exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            # Guild-level jail config (jail role + jail channel)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS jail_config (
                    guild_id INTEGER PRIMARY KEY,
                    jail_role_id INTEGER,
                    jail_channel_id INTEGER
                )
            ''')

            # Jailed users — stores their previous roles and jail expiry
            await db.execute('''
                CREATE TABLE IF NOT EXISTS jailed_users (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    previous_roles TEXT NOT NULL,
                    jailed_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')
            await db.commit()

    # ─── Config ────────────────────────────────────────────────────

    async def set_jail_config(self, guild_id: int, jail_role_id: int, jail_channel_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT OR REPLACE INTO jail_config (guild_id, jail_role_id, jail_channel_id) VALUES (?, ?, ?)',
                (guild_id, jail_role_id, jail_channel_id)
            )
            await db.commit()

    async def get_jail_config(self, guild_id: int):
        """Returns (jail_role_id, jail_channel_id) or None"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT jail_role_id, jail_channel_id FROM jail_config WHERE guild_id = ?',
                (guild_id,)
            ) as cursor:
                return await cursor.fetchone()

    async def update_jail_role(self, guild_id: int, jail_role_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT INTO jail_config (guild_id, jail_role_id) VALUES (?, ?) '
                'ON CONFLICT(guild_id) DO UPDATE SET jail_role_id = excluded.jail_role_id',
                (guild_id, jail_role_id)
            )
            await db.commit()

    async def update_jail_channel(self, guild_id: int, jail_channel_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT INTO jail_config (guild_id, jail_channel_id) VALUES (?, ?) '
                'ON CONFLICT(guild_id) DO UPDATE SET jail_channel_id = excluded.jail_channel_id',
                (guild_id, jail_channel_id)
            )
            await db.commit()

    # ─── Jailed users ──────────────────────────────────────────────

    async def jail_user(
        self,
        guild_id: int,
        user_id: int,
        moderator_id: int,
        reason: str,
        previous_role_ids: list[int],
        expires_at: int | None = None
    ):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                '''INSERT OR REPLACE INTO jailed_users
                   (guild_id, user_id, moderator_id, reason, previous_roles, jailed_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (
                    guild_id,
                    user_id,
                    moderator_id,
                    reason,
                    json.dumps(previous_role_ids),
                    int(time.time()),
                    expires_at
                )
            )
            await db.commit()

    async def get_jailed_user(self, guild_id: int, user_id: int):
        """Returns (moderator_id, reason, previous_roles_json, jailed_at, expires_at) or None"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT moderator_id, reason, previous_roles, jailed_at, expires_at FROM jailed_users WHERE guild_id = ? AND user_id = ?',
                (guild_id, user_id)
            ) as cursor:
                return await cursor.fetchone()

    async def is_jailed(self, guild_id: int, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT 1 FROM jailed_users WHERE guild_id = ? AND user_id = ?',
                (guild_id, user_id)
            ) as cursor:
                return await cursor.fetchone() is not None

    async def unjail_user(self, guild_id: int, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'DELETE FROM jailed_users WHERE guild_id = ? AND user_id = ?',
                (guild_id, user_id)
            )
            await db.commit()

    async def get_all_jailed(self, guild_id: int):
        """Returns list of (user_id, moderator_id, reason, jailed_at, expires_at)"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT user_id, moderator_id, reason, jailed_at, expires_at FROM jailed_users WHERE guild_id = ? ORDER BY jailed_at DESC',
                (guild_id,)
            ) as cursor:
                return await cursor.fetchall()

    async def get_expired_jails(self, current_time: int):
        """Returns list of (guild_id, user_id) where jail has expired"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT guild_id, user_id FROM jailed_users WHERE expires_at IS NOT NULL AND expires_at <= ?',
                (current_time,)
            ) as cursor:
                return await cursor.fetchall()