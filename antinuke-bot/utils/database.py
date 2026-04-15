import aiosqlite
import asyncio
import os
import time
import json


MAX_BACKUPS = 10


class Database:
    def __init__(self):
        self.db_path = 'data/antinuke.db'
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
        return self._conn

    async def _execute(self, sql: str, params: tuple = ()):
        async with self._lock:
            conn = await self._get_conn()
            await conn.execute(sql, params)
            await conn.commit()

    async def _fetchone(self, sql: str, params: tuple = ()):
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute(sql, params) as cur:
                return await cur.fetchone()

    async def _fetchall(self, sql: str, params: tuple = ()):
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute(sql, params) as cur:
                return await cur.fetchall()

    async def initialize(self):
        os.makedirs('data', exist_ok=True)
        conn = await self._get_conn()
        async with self._lock:
            await conn.executescript('''
                CREATE TABLE IF NOT EXISTS limits (
                    guild_id INTEGER, action TEXT, action_limit INTEGER,
                    PRIMARY KEY (guild_id, action)
                );
                CREATE TABLE IF NOT EXISTS timeframes (
                    guild_id INTEGER, action TEXT, seconds INTEGER,
                    PRIMARY KEY (guild_id, action)
                );
                CREATE TABLE IF NOT EXISTS punishments (
                    guild_id INTEGER, action TEXT, punishment TEXT,
                    PRIMARY KEY (guild_id, action)
                );
                CREATE TABLE IF NOT EXISTS protection_toggles (
                    guild_id INTEGER, action TEXT, enabled INTEGER DEFAULT 1,
                    PRIMARY KEY (guild_id, action)
                );
                CREATE TABLE IF NOT EXISTS whitelist (
                    guild_id INTEGER, user_id INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS whitelist_per_action (
                    guild_id INTEGER, user_id INTEGER, action TEXT,
                    PRIMARY KEY (guild_id, user_id, action)
                );
                CREATE TABLE IF NOT EXISTS whitelist_temp (
                    guild_id INTEGER, user_id INTEGER, expires_at INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS whitelist_roles (
                    guild_id INTEGER, role_id INTEGER,
                    PRIMARY KEY (guild_id, role_id)
                );
                CREATE TABLE IF NOT EXISTS whitelist_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER, target_id INTEGER, target_type TEXT,
                    action_taken TEXT, details TEXT, performed_by INTEGER, timestamp INTEGER
                );
                CREATE TABLE IF NOT EXISTS admins (
                    guild_id INTEGER, user_id INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS admins_temp (
                    guild_id INTEGER, user_id INTEGER, expires_at INTEGER, added_by INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS admin_action_perms (
                    guild_id INTEGER, user_id INTEGER, action TEXT,
                    PRIMARY KEY (guild_id, user_id, action)
                );
                CREATE TABLE IF NOT EXISTS action_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER, user_id INTEGER, action TEXT, timestamp INTEGER
                );
                CREATE TABLE IF NOT EXISTS bot_owners (
                    guild_id INTEGER, bot_id INTEGER, owner_id INTEGER,
                    PRIMARY KEY (guild_id, bot_id)
                );
                CREATE TABLE IF NOT EXISTS server_backups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER, label TEXT, backup_data TEXT, timestamp INTEGER
                );
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    prefix TEXT DEFAULT "!",
                    log_channel_id INTEGER,
                    audit_log_channel_id INTEGER DEFAULT NULL,
                    dm_alerts_enabled INTEGER DEFAULT 0,
                    dm_alert_targets TEXT DEFAULT NULL,
                    dm_alert_admin_can_manage INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS pending_actions (
                    guild_id INTEGER, user_id INTEGER, action TEXT,
                    target_json TEXT, created_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER, user_id INTEGER, moderator_id INTEGER,
                    note TEXT, timestamp INTEGER
                );
                CREATE TABLE IF NOT EXISTS temp_bans (
                    guild_id INTEGER, user_id INTEGER, expires_at INTEGER,
                    reason TEXT, banned_by INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS msg_log_settings (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER DEFAULT NULL,
                    enabled INTEGER DEFAULT 1,
                    log_sent INTEGER DEFAULT 1,
                    log_edited INTEGER DEFAULT 1,
                    log_deleted INTEGER DEFAULT 1,
                    log_bulk_delete INTEGER DEFAULT 1,
                    ignore_bots INTEGER DEFAULT 1,
                    ignored_channels TEXT DEFAULT NULL,
                    ignored_roles TEXT DEFAULT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log_settings (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER DEFAULT NULL,
                    enabled INTEGER DEFAULT 1,
                    log_bans INTEGER DEFAULT 1,
                    log_unbans INTEGER DEFAULT 1,
                    log_kicks INTEGER DEFAULT 1,
                    log_timeouts INTEGER DEFAULT 1,
                    log_role_perms INTEGER DEFAULT 1,
                    log_role_create INTEGER DEFAULT 1,
                    log_role_delete INTEGER DEFAULT 1,
                    log_member_roles INTEGER DEFAULT 1,
                    log_channel_create INTEGER DEFAULT 1,
                    log_channel_delete INTEGER DEFAULT 1,
                    log_channel_update INTEGER DEFAULT 1,
                    log_server_update INTEGER DEFAULT 1,
                    log_webhooks INTEGER DEFAULT 1,
                    log_invites INTEGER DEFAULT 1,
                    log_emoji INTEGER DEFAULT 1,
                    log_stickers INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS join_log_settings (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER DEFAULT NULL,
                    enabled INTEGER DEFAULT 1,
                    log_joins INTEGER DEFAULT 1,
                    log_leaves INTEGER DEFAULT 1,
                    log_kicks INTEGER DEFAULT 1,
                    log_bans INTEGER DEFAULT 1,
                    show_avatar INTEGER DEFAULT 1,
                    show_account_age INTEGER DEFAULT 1,
                    show_join_position INTEGER DEFAULT 1,
                    show_roles_on_rejoin INTEGER DEFAULT 1,
                    show_invite_used INTEGER DEFAULT 1,
                    show_is_bot INTEGER DEFAULT 1,
                    new_account_threshold INTEGER DEFAULT 7,
                    warn_new_accounts INTEGER DEFAULT 1,
                    warn_no_avatar INTEGER DEFAULT 1,
                    suspicious_ping_role_id INTEGER DEFAULT NULL,
                    welcome_channel_id INTEGER DEFAULT NULL,
                    welcome_enabled INTEGER DEFAULT 0,
                    welcome_message TEXT DEFAULT NULL,
                    embed_color_join INTEGER DEFAULT 5763719,
                    embed_color_leave INTEGER DEFAULT 16729344,
                    embed_color_suspicious INTEGER DEFAULT 16744272
                );
                CREATE TABLE IF NOT EXISTS dm_alert_rules (
                    guild_id INTEGER, event_type TEXT,
                    target_user_ids TEXT DEFAULT NULL,
                    enabled INTEGER DEFAULT 1,
                    PRIMARY KEY (guild_id, event_type)
                );
                CREATE INDEX IF NOT EXISTS idx_action_log_lookup
                    ON action_log (guild_id, user_id, action, timestamp);
                CREATE INDEX IF NOT EXISTS idx_whitelist_temp_expires
                    ON whitelist_temp (expires_at);
                CREATE INDEX IF NOT EXISTS idx_pending_actions
                    ON pending_actions (guild_id, user_id, action);
                CREATE INDEX IF NOT EXISTS idx_notes_user
                    ON notes (guild_id, user_id);
                CREATE INDEX IF NOT EXISTS idx_temp_bans_expires
                    ON temp_bans (expires_at);
                CREATE INDEX IF NOT EXISTS idx_msg_log_settings
                    ON msg_log_settings (guild_id);
                CREATE TABLE IF NOT EXISTS trusted_roles (
                    guild_id INTEGER, role_id INTEGER,
                    PRIMARY KEY (guild_id, role_id)
                );
                CREATE TABLE IF NOT EXISTS mod_log_filters (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 1,
                    ignore_bots INTEGER DEFAULT 0,
                    ignored_users TEXT DEFAULT NULL,
                    ignored_roles TEXT DEFAULT NULL,
                    ignored_actions TEXT DEFAULT NULL,
                    log_warns INTEGER DEFAULT 1,
                    log_mutes INTEGER DEFAULT 1,
                    log_kicks INTEGER DEFAULT 1,
                    log_bans INTEGER DEFAULT 1,
                    log_unbans INTEGER DEFAULT 1,
                    log_jails INTEGER DEFAULT 1,
                    log_lockdowns INTEGER DEFAULT 1,
                    log_massbans INTEGER DEFAULT 1,
                    log_antinuke INTEGER DEFAULT 1,
                    log_notes INTEGER DEFAULT 1,
                    log_slowmode INTEGER DEFAULT 1,
                    log_purge INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS invite_tracker (
                    guild_id INTEGER, user_id INTEGER, inviter_id INTEGER,
                    invite_code TEXT, joined_at INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS mod_action_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER, target_id INTEGER, moderator_id INTEGER,
                    action TEXT, reason TEXT, timestamp INTEGER,
                    extra TEXT DEFAULT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mod_action_history
                    ON mod_action_history (guild_id, target_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_invite_tracker
                    ON invite_tracker (guild_id, inviter_id);
            ''')
            await conn.commit()
        await self._migrate()

    async def _migrate(self):
        migrations = [
            "ALTER TABLE guild_settings ADD COLUMN audit_log_channel_id INTEGER DEFAULT NULL",
            "ALTER TABLE guild_settings ADD COLUMN dm_alert_admin_can_manage INTEGER DEFAULT 0",
            "ALTER TABLE guild_settings ADD COLUMN lockdown_member_role_id INTEGER DEFAULT NULL",
            # New tables via executescript won't work here — handled in initialize via IF NOT EXISTS
        ]
        conn = await self._get_conn()
        async with self._lock:
            for sql in migrations:
                try:
                    await conn.execute(sql)
                    await conn.commit()
                except Exception:
                    pass

    # ─── Limits ───────────────────────────────────────────────────────────────
    async def set_limit(self, guild_id, action, limit):
        await self._execute('INSERT OR REPLACE INTO limits VALUES (?,?,?)', (guild_id, action, limit))
    async def get_limit(self, guild_id, action):
        r = await self._fetchone('SELECT action_limit FROM limits WHERE guild_id=? AND action=?', (guild_id, action))
        return r[0] if r else None

    # ─── Timeframes ──────────────────────────────────────────────────────────
    async def set_timeframe(self, guild_id, action, seconds):
        await self._execute('INSERT OR REPLACE INTO timeframes VALUES (?,?,?)', (guild_id, action, seconds))
    async def get_timeframe(self, guild_id, action):
        r = await self._fetchone('SELECT seconds FROM timeframes WHERE guild_id=? AND action=?', (guild_id, action))
        return r[0] if r else 60

    # ─── Punishments ─────────────────────────────────────────────────────────
    async def set_punishment(self, guild_id, action, punishment):
        await self._execute('INSERT OR REPLACE INTO punishments VALUES (?,?,?)', (guild_id, action, punishment))
    async def get_punishment(self, guild_id, action):
        r = await self._fetchone('SELECT punishment FROM punishments WHERE guild_id=? AND action=?', (guild_id, action))
        return r[0] if r else 'ban'

    # ─── Protection toggles ──────────────────────────────────────────────────
    async def set_protection_enabled(self, guild_id, action, enabled):
        await self._execute('INSERT OR REPLACE INTO protection_toggles VALUES (?,?,?)', (guild_id, action, 1 if enabled else 0))
    async def is_protection_enabled(self, guild_id, action):
        r = await self._fetchone('SELECT enabled FROM protection_toggles WHERE guild_id=? AND action=?', (guild_id, action))
        return r[0] == 1 if r else True
    async def get_all_toggles(self, guild_id):
        rows = await self._fetchall('SELECT action, enabled FROM protection_toggles WHERE guild_id=?', (guild_id,))
        return {r[0]: bool(r[1]) for r in rows}

    # ─── Global whitelist ────────────────────────────────────────────────────
    async def add_whitelist(self, guild_id, user_id):
        await self._execute('INSERT OR IGNORE INTO whitelist VALUES (?,?)', (guild_id, user_id))
    async def remove_whitelist(self, guild_id, user_id):
        await self._execute('DELETE FROM whitelist WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    async def is_globally_whitelisted(self, guild_id, user_id):
        return await self._fetchone('SELECT 1 FROM whitelist WHERE guild_id=? AND user_id=?', (guild_id, user_id)) is not None
    async def get_whitelist(self, guild_id):
        rows = await self._fetchall('SELECT user_id FROM whitelist WHERE guild_id=?', (guild_id,))
        return [r[0] for r in rows]

    # ─── Per-action whitelist ────────────────────────────────────────────────
    async def add_whitelist_action(self, guild_id, user_id, action):
        await self._execute('INSERT OR IGNORE INTO whitelist_per_action VALUES (?,?,?)', (guild_id, user_id, action))
    async def remove_whitelist_action(self, guild_id, user_id, action):
        await self._execute('DELETE FROM whitelist_per_action WHERE guild_id=? AND user_id=? AND action=?', (guild_id, user_id, action))
    async def remove_all_whitelist_actions(self, guild_id, user_id):
        await self._execute('DELETE FROM whitelist_per_action WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    async def get_whitelisted_actions(self, guild_id, user_id):
        rows = await self._fetchall('SELECT action FROM whitelist_per_action WHERE guild_id=? AND user_id=?', (guild_id, user_id))
        return [r[0] for r in rows]
    async def is_action_whitelisted(self, guild_id, user_id, action):
        return await self._fetchone('SELECT 1 FROM whitelist_per_action WHERE guild_id=? AND user_id=? AND action=?', (guild_id, user_id, action)) is not None

    # ─── Temporary whitelist ─────────────────────────────────────────────────
    async def add_temp_whitelist(self, guild_id, user_id, expires_at):
        await self._execute('INSERT OR REPLACE INTO whitelist_temp VALUES (?,?,?)', (guild_id, user_id, expires_at))
    async def remove_temp_whitelist(self, guild_id, user_id):
        await self._execute('DELETE FROM whitelist_temp WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    async def is_temp_whitelisted(self, guild_id, user_id):
        return await self._fetchone('SELECT expires_at FROM whitelist_temp WHERE guild_id=? AND user_id=? AND expires_at>?', (guild_id, user_id, int(time.time()))) is not None
    async def get_temp_whitelist_expiry(self, guild_id, user_id):
        r = await self._fetchone('SELECT expires_at FROM whitelist_temp WHERE guild_id=? AND user_id=? AND expires_at>?', (guild_id, user_id, int(time.time())))
        return r[0] if r else None
    async def cleanup_expired_temp_whitelist(self):
        await self._execute('DELETE FROM whitelist_temp WHERE expires_at<=?', (int(time.time()),))

    # ─── Role-based whitelist ─────────────────────────────────────────────────
    async def add_whitelist_role(self, guild_id, role_id):
        await self._execute('INSERT OR IGNORE INTO whitelist_roles VALUES (?,?)', (guild_id, role_id))
    async def remove_whitelist_role(self, guild_id, role_id):
        await self._execute('DELETE FROM whitelist_roles WHERE guild_id=? AND role_id=?', (guild_id, role_id))
    async def get_whitelist_roles(self, guild_id):
        rows = await self._fetchall('SELECT role_id FROM whitelist_roles WHERE guild_id=?', (guild_id,))
        return [r[0] for r in rows]

    # ─── Combined whitelist check ────────────────────────────────────────────
    async def is_whitelisted(self, guild_id, user_id, action=None, member_role_ids=None):
        if await self.is_globally_whitelisted(guild_id, user_id): return True
        if await self.is_temp_whitelisted(guild_id, user_id): return True
        if action and await self.is_action_whitelisted(guild_id, user_id, action): return True
        if member_role_ids:
            wl_roles = await self.get_whitelist_roles(guild_id)
            if any(r in wl_roles for r in member_role_ids): return True
        return False

    # ─── Whitelist audit ─────────────────────────────────────────────────────
    async def log_whitelist_audit(self, guild_id, target_id, target_type, action_taken, details, performed_by):
        await self._execute(
            'INSERT INTO whitelist_audit (guild_id,target_id,target_type,action_taken,details,performed_by,timestamp) VALUES (?,?,?,?,?,?,?)',
            (guild_id, target_id, target_type, action_taken, details, performed_by, int(time.time()))
        )
    async def get_whitelist_audit(self, guild_id, limit=20):
        rows = await self._fetchall(
            'SELECT target_id,target_type,action_taken,details,performed_by,timestamp FROM whitelist_audit WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?',
            (guild_id, limit)
        )
        return [dict(r) for r in rows]

    # ─── Admins ──────────────────────────────────────────────────────────────
    async def add_admin(self, guild_id, user_id):
        await self._execute('INSERT OR IGNORE INTO admins VALUES (?,?)', (guild_id, user_id))
    async def remove_admin(self, guild_id, user_id):
        await self._execute('DELETE FROM admins WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    async def is_admin(self, guild_id, user_id):
        r = await self._fetchone('SELECT 1 FROM admins WHERE guild_id=? AND user_id=?', (guild_id, user_id))
        return r is not None or await self.is_temp_admin(guild_id, user_id)
    async def get_all_admins(self, guild_id):
        rows = await self._fetchall('SELECT user_id FROM admins WHERE guild_id=?', (guild_id,))
        return [r[0] for r in rows]

    # ─── Temporary Admins ────────────────────────────────────────────────────
    async def add_temp_admin(self, guild_id, user_id, expires_at, added_by):
        await self._execute('INSERT OR REPLACE INTO admins_temp VALUES (?,?,?,?)', (guild_id, user_id, expires_at, added_by))
    async def remove_temp_admin(self, guild_id, user_id):
        await self._execute('DELETE FROM admins_temp WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    async def is_temp_admin(self, guild_id, user_id):
        return await self._fetchone('SELECT expires_at FROM admins_temp WHERE guild_id=? AND user_id=? AND expires_at>?', (guild_id, user_id, int(time.time()))) is not None
    async def get_temp_admin_expiry(self, guild_id, user_id):
        r = await self._fetchone('SELECT expires_at FROM admins_temp WHERE guild_id=? AND user_id=? AND expires_at>?', (guild_id, user_id, int(time.time())))
        return r[0] if r else None
    async def get_all_temp_admins(self, guild_id):
        rows = await self._fetchall('SELECT user_id,expires_at,added_by FROM admins_temp WHERE guild_id=? AND expires_at>?', (guild_id, int(time.time())))
        return [dict(r) for r in rows]
    async def cleanup_expired_temp_admins(self):
        await self._execute('DELETE FROM admins_temp WHERE expires_at<=?', (int(time.time()),))

    # ─── Admin Action Permissions ─────────────────────────────────────────────
    async def add_admin_action_perm(self, guild_id, user_id, action):
        await self._execute('INSERT OR IGNORE INTO admin_action_perms VALUES (?,?,?)', (guild_id, user_id, action))
    async def remove_admin_action_perm(self, guild_id, user_id, action):
        await self._execute('DELETE FROM admin_action_perms WHERE guild_id=? AND user_id=? AND action=?', (guild_id, user_id, action))
    async def remove_all_admin_action_perms(self, guild_id, user_id):
        await self._execute('DELETE FROM admin_action_perms WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    async def get_admin_action_perms(self, guild_id, user_id):
        rows = await self._fetchall('SELECT action FROM admin_action_perms WHERE guild_id=? AND user_id=?', (guild_id, user_id))
        return [r[0] for r in rows]
    async def has_admin_action_perm(self, guild_id, user_id, action):
        return await self._fetchone('SELECT 1 FROM admin_action_perms WHERE guild_id=? AND user_id=? AND action=?', (guild_id, user_id, action)) is not None

    # ─── Action log ──────────────────────────────────────────────────────────
    async def log_action(self, guild_id, user_id, action, timestamp):
        await self._execute('INSERT INTO action_log (guild_id,user_id,action,timestamp) VALUES (?,?,?,?)', (guild_id, user_id, action, timestamp))
    async def get_recent_actions(self, guild_id, user_id, action, since_timestamp):
        r = await self._fetchone('SELECT COUNT(*) FROM action_log WHERE guild_id=? AND user_id=? AND action=? AND timestamp>=?', (guild_id, user_id, action, since_timestamp))
        return r[0] if r else 0
    async def cleanup_old_logs(self, older_than_seconds=86400):
        await self._execute('DELETE FROM action_log WHERE timestamp<?', (int(time.time()) - older_than_seconds,))

    # ─── Bot owners ──────────────────────────────────────────────────────────
    async def set_bot_owner(self, guild_id, bot_id, owner_id):
        await self._execute('INSERT OR REPLACE INTO bot_owners VALUES (?,?,?)', (guild_id, bot_id, owner_id))
    async def get_bot_owner(self, guild_id, bot_id):
        r = await self._fetchone('SELECT owner_id FROM bot_owners WHERE guild_id=? AND bot_id=?', (guild_id, bot_id))
        return r[0] if r else None

    # ─── Server backups ──────────────────────────────────────────────────────
    async def count_server_backups(self, guild_id):
        r = await self._fetchone('SELECT COUNT(*) FROM server_backups WHERE guild_id=?', (guild_id,))
        return r[0] if r else 0
    async def save_server_backup(self, guild_id, backup_data, timestamp, label=''):
        count = await self.count_server_backups(guild_id)
        if count >= MAX_BACKUPS:
            r = await self._fetchone('SELECT id FROM server_backups WHERE guild_id=? ORDER BY timestamp ASC LIMIT 1', (guild_id,))
            if r: await self._execute('DELETE FROM server_backups WHERE id=?', (r[0],))
        await self._execute('INSERT INTO server_backups (guild_id,label,backup_data,timestamp) VALUES (?,?,?,?)', (guild_id, label or '', backup_data, timestamp))
    async def get_server_backup(self, guild_id, backup_id=None):
        if backup_id is not None:
            return await self._fetchone('SELECT id,backup_data,timestamp,label FROM server_backups WHERE guild_id=? AND id=?', (guild_id, backup_id))
        return await self._fetchone('SELECT id,backup_data,timestamp,label FROM server_backups WHERE guild_id=? ORDER BY timestamp DESC LIMIT 1', (guild_id,))
    async def list_server_backups(self, guild_id):
        rows = await self._fetchall('SELECT id,label,timestamp FROM server_backups WHERE guild_id=? ORDER BY timestamp DESC', (guild_id,))
        return [dict(r) for r in rows]
    async def delete_server_backup(self, guild_id, backup_id):
        if not await self._fetchone('SELECT 1 FROM server_backups WHERE guild_id=? AND id=?', (guild_id, backup_id)): return False
        await self._execute('DELETE FROM server_backups WHERE guild_id=? AND id=?', (guild_id, backup_id))
        return True
    async def has_server_backup(self, guild_id):
        return await self._fetchone('SELECT 1 FROM server_backups WHERE guild_id=?', (guild_id,)) is not None

    # ─── Guild settings ──────────────────────────────────────────────────────
    async def _ensure_guild_settings(self, guild_id):
        await self._execute('INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)', (guild_id,))

    async def set_prefix(self, guild_id, prefix):
        await self._ensure_guild_settings(guild_id)
        await self._execute('UPDATE guild_settings SET prefix=? WHERE guild_id=?', (prefix, guild_id))
    async def get_prefix(self, guild_id):
        r = await self._fetchone('SELECT prefix FROM guild_settings WHERE guild_id=?', (guild_id,))
        return r[0] if r else '!'

    async def set_log_channel(self, guild_id, channel_id):
        await self._ensure_guild_settings(guild_id)
        await self._execute('UPDATE guild_settings SET log_channel_id=? WHERE guild_id=?', (channel_id, guild_id))
    async def get_log_channel(self, guild_id):
        r = await self._fetchone('SELECT log_channel_id FROM guild_settings WHERE guild_id=?', (guild_id,))
        return r[0] if r else None

    async def set_audit_log_channel(self, guild_id, channel_id):
        await self._ensure_guild_settings(guild_id)
        await self._execute('UPDATE guild_settings SET audit_log_channel_id=? WHERE guild_id=?', (channel_id, guild_id))
    async def get_audit_log_channel(self, guild_id):
        r = await self._fetchone('SELECT audit_log_channel_id FROM guild_settings WHERE guild_id=?', (guild_id,))
        return r[0] if r else None

    async def set_dm_alerts(self, guild_id, enabled):
        await self._ensure_guild_settings(guild_id)
        await self._execute('UPDATE guild_settings SET dm_alerts_enabled=? WHERE guild_id=?', (1 if enabled else 0, guild_id))
    async def get_dm_alerts(self, guild_id):
        r = await self._fetchone('SELECT dm_alerts_enabled FROM guild_settings WHERE guild_id=?', (guild_id,))
        return bool(r[0]) if r else False

    async def set_dm_alert_admin_can_manage(self, guild_id, allowed):
        await self._ensure_guild_settings(guild_id)
        await self._execute('UPDATE guild_settings SET dm_alert_admin_can_manage=? WHERE guild_id=?', (1 if allowed else 0, guild_id))
    async def get_dm_alert_admin_can_manage(self, guild_id):
        r = await self._fetchone('SELECT dm_alert_admin_can_manage FROM guild_settings WHERE guild_id=?', (guild_id,))
        return bool(r[0]) if r else False

    # ─── DM Alert Targets ────────────────────────────────────────────────────
    async def set_dm_alert_targets(self, guild_id, user_ids):
        await self._ensure_guild_settings(guild_id)
        await self._execute('UPDATE guild_settings SET dm_alert_targets=? WHERE guild_id=?', (json.dumps(user_ids) if user_ids else None, guild_id))
    async def get_dm_alert_targets(self, guild_id):
        r = await self._fetchone('SELECT dm_alert_targets FROM guild_settings WHERE guild_id=?', (guild_id,))
        if r and r[0]:
            try: return json.loads(r[0])
            except: pass
        return []
    async def add_dm_alert_target(self, guild_id, user_id):
        targets = await self.get_dm_alert_targets(guild_id)
        if user_id not in targets:
            targets.append(user_id)
            await self.set_dm_alert_targets(guild_id, targets)
    async def remove_dm_alert_target(self, guild_id, user_id):
        targets = await self.get_dm_alert_targets(guild_id)
        if user_id in targets:
            targets.remove(user_id)
            await self.set_dm_alert_targets(guild_id, targets)

    # ─── DM Alert Rules (per-event routing) ─────────────────────────────────
    async def set_dm_alert_rule(self, guild_id, event_type, enabled, target_user_ids=None):
        data = json.dumps(target_user_ids) if target_user_ids else None
        await self._execute(
            'INSERT OR REPLACE INTO dm_alert_rules (guild_id,event_type,target_user_ids,enabled) VALUES (?,?,?,?)',
            (guild_id, event_type, data, 1 if enabled else 0)
        )
    async def get_dm_alert_rule(self, guild_id, event_type):
        r = await self._fetchone('SELECT enabled,target_user_ids FROM dm_alert_rules WHERE guild_id=? AND event_type=?', (guild_id, event_type))
        if r:
            targets = None
            if r[1]:
                try: targets = json.loads(r[1])
                except: pass
            return {'enabled': bool(r[0]), 'targets': targets}
        return {'enabled': True, 'targets': None}
    async def get_all_dm_alert_rules(self, guild_id):
        rows = await self._fetchall('SELECT event_type,enabled,target_user_ids FROM dm_alert_rules WHERE guild_id=?', (guild_id,))
        result = []
        for r in rows:
            targets = None
            if r[2]:
                try: targets = json.loads(r[2])
                except: pass
            result.append({'event_type': r[0], 'enabled': bool(r[1]), 'targets': targets})
        return result

    # ─── Pending actions ─────────────────────────────────────────────────────
    async def save_pending_action(self, guild_id, user_id, action, target_data):
        await self._execute(
            'INSERT INTO pending_actions (guild_id,user_id,action,target_json,created_at) VALUES (?,?,?,?,?)',
            (guild_id, user_id, action, json.dumps(target_data), int(time.time()))
        )
    async def load_pending_actions(self, guild_id, user_id, action):
        rows = await self._fetchall('SELECT target_json FROM pending_actions WHERE guild_id=? AND user_id=? AND action=?', (guild_id, user_id, action))
        result = []
        for r in rows:
            try: result.append(json.loads(r[0]))
            except: pass
        return result
    async def clear_pending_actions(self, guild_id, user_id, action):
        await self._execute('DELETE FROM pending_actions WHERE guild_id=? AND user_id=? AND action=?', (guild_id, user_id, action))
    async def cleanup_old_pending_actions(self, older_than_seconds=3600):
        await self._execute('DELETE FROM pending_actions WHERE created_at<?', (int(time.time()) - older_than_seconds,))

    # ─── Notes ───────────────────────────────────────────────────────────────
    async def add_note(self, guild_id, user_id, moderator_id, note):
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute(
                'INSERT INTO notes (guild_id,user_id,moderator_id,note,timestamp) VALUES (?,?,?,?,?)',
                (guild_id, user_id, moderator_id, note, int(time.time()))
            ) as cur:
                note_id = cur.lastrowid
            await conn.commit()
        return note_id
    async def get_notes(self, guild_id, user_id):
        rows = await self._fetchall('SELECT id,moderator_id,note,timestamp FROM notes WHERE guild_id=? AND user_id=? ORDER BY timestamp DESC', (guild_id, user_id))
        return [dict(r) for r in rows]
    async def remove_note(self, guild_id, note_id):
        if not await self._fetchone('SELECT 1 FROM notes WHERE guild_id=? AND id=?', (guild_id, note_id)): return False
        await self._execute('DELETE FROM notes WHERE id=? AND guild_id=?', (note_id, guild_id))
        return True
    async def clear_notes(self, guild_id, user_id):
        r = await self._fetchone('SELECT COUNT(*) FROM notes WHERE guild_id=? AND user_id=?', (guild_id, user_id))
        count = r[0] if r else 0
        await self._execute('DELETE FROM notes WHERE guild_id=? AND user_id=?', (guild_id, user_id))
        return count

    # ─── Temp Bans ───────────────────────────────────────────────────────────
    async def add_temp_ban(self, guild_id, user_id, expires_at, reason, banned_by):
        await self._execute('INSERT OR REPLACE INTO temp_bans VALUES (?,?,?,?,?)', (guild_id, user_id, expires_at, reason, banned_by))
    async def remove_temp_ban(self, guild_id, user_id):
        await self._execute('DELETE FROM temp_bans WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    async def get_expired_temp_bans(self):
        rows = await self._fetchall('SELECT guild_id,user_id,reason FROM temp_bans WHERE expires_at<=?', (int(time.time()),))
        return [dict(r) for r in rows]
    async def get_all_temp_bans(self, guild_id):
        rows = await self._fetchall('SELECT user_id,expires_at,reason,banned_by FROM temp_bans WHERE guild_id=? AND expires_at>?', (guild_id, int(time.time())))
        return [dict(r) for r in rows]

    # ─── Message Log Settings ────────────────────────────────────────────────
    async def _ensure_msg_log(self, guild_id):
        await self._execute('INSERT OR IGNORE INTO msg_log_settings (guild_id) VALUES (?)', (guild_id,))
    async def get_msg_log_settings(self, guild_id):
        await self._ensure_msg_log(guild_id)
        r = await self._fetchone('SELECT * FROM msg_log_settings WHERE guild_id=?', (guild_id,))
        if not r: return {}
        d = dict(r)
        for k in ('ignored_channels', 'ignored_roles'):
            try: d[k] = json.loads(d[k]) if d[k] else []
            except: d[k] = []
        return d
    async def set_msg_log_channel(self, guild_id, channel_id):
        await self._ensure_msg_log(guild_id)
        await self._execute('UPDATE msg_log_settings SET channel_id=? WHERE guild_id=?', (channel_id, guild_id))
    async def set_msg_log_enabled(self, guild_id, enabled):
        await self._ensure_msg_log(guild_id)
        await self._execute('UPDATE msg_log_settings SET enabled=? WHERE guild_id=?', (1 if enabled else 0, guild_id))
    async def set_msg_log_event(self, guild_id, event, enabled):
        allowed = {'log_sent','log_edited','log_deleted','log_bulk_delete','ignore_bots'}
        if event not in allowed: raise ValueError(f"Invalid event: {event}")
        await self._ensure_msg_log(guild_id)
        await self._execute(f'UPDATE msg_log_settings SET {event}=? WHERE guild_id=?', (1 if enabled else 0, guild_id))
    async def set_msg_log_ignored_channels(self, guild_id, channel_ids):
        await self._ensure_msg_log(guild_id)
        await self._execute('UPDATE msg_log_settings SET ignored_channels=? WHERE guild_id=?', (json.dumps(channel_ids), guild_id))
    async def set_msg_log_ignored_roles(self, guild_id, role_ids):
        await self._ensure_msg_log(guild_id)
        await self._execute('UPDATE msg_log_settings SET ignored_roles=? WHERE guild_id=?', (json.dumps(role_ids), guild_id))

    # ─── Audit Log Settings ───────────────────────────────────────────────────
    async def _ensure_audit_log(self, guild_id):
        await self._execute('INSERT OR IGNORE INTO audit_log_settings (guild_id) VALUES (?)', (guild_id,))
    async def get_audit_log_settings(self, guild_id):
        await self._ensure_audit_log(guild_id)
        r = await self._fetchone('SELECT * FROM audit_log_settings WHERE guild_id=?', (guild_id,))
        return dict(r) if r else {}
    async def set_audit_log_channel_id(self, guild_id, channel_id):
        await self._ensure_audit_log(guild_id)
        await self._execute('UPDATE audit_log_settings SET channel_id=? WHERE guild_id=?', (channel_id, guild_id))
    async def set_audit_log_enabled(self, guild_id, enabled):
        await self._ensure_audit_log(guild_id)
        await self._execute('UPDATE audit_log_settings SET enabled=? WHERE guild_id=?', (1 if enabled else 0, guild_id))
    async def set_audit_log_event(self, guild_id, event, enabled):
        allowed = {
            'log_bans','log_unbans','log_kicks','log_timeouts','log_role_perms',
            'log_role_create','log_role_delete','log_member_roles','log_channel_create',
            'log_channel_delete','log_channel_update','log_server_update',
            'log_webhooks','log_invites','log_emoji','log_stickers'
        }
        if event not in allowed: raise ValueError(f"Invalid audit event: {event}")
        await self._ensure_audit_log(guild_id)
        await self._execute(f'UPDATE audit_log_settings SET {event}=? WHERE guild_id=?', (1 if enabled else 0, guild_id))

    # ─── Join Log Settings ────────────────────────────────────────────────────
    async def _ensure_join_log(self, guild_id):
        await self._execute('INSERT OR IGNORE INTO join_log_settings (guild_id) VALUES (?)', (guild_id,))
    async def get_join_log_settings(self, guild_id):
        await self._ensure_join_log(guild_id)
        r = await self._fetchone('SELECT * FROM join_log_settings WHERE guild_id=?', (guild_id,))
        return dict(r) if r else {}
    async def set_join_log_channel(self, guild_id, channel_id):
        await self._ensure_join_log(guild_id)
        await self._execute('UPDATE join_log_settings SET channel_id=? WHERE guild_id=?', (channel_id, guild_id))
    async def set_join_log_enabled(self, guild_id, enabled):
        await self._ensure_join_log(guild_id)
        await self._execute('UPDATE join_log_settings SET enabled=? WHERE guild_id=?', (1 if enabled else 0, guild_id))
    async def set_join_log_setting(self, guild_id, key, value):
        allowed = {
            'log_joins','log_leaves','log_kicks','log_bans','show_avatar',
            'show_account_age','show_join_position','show_roles_on_rejoin',
            'show_invite_used','show_is_bot','new_account_threshold',
            'warn_new_accounts','warn_no_avatar','suspicious_ping_role_id',
            'welcome_channel_id','welcome_enabled','welcome_message',
            'embed_color_join','embed_color_leave','embed_color_suspicious'
        }
        if key not in allowed: raise ValueError(f"Invalid join log setting: {key}")
        await self._ensure_join_log(guild_id)
        await self._execute(f'UPDATE join_log_settings SET {key}=? WHERE guild_id=?', (value, guild_id))

    # ─── Trusted Roles (anti-nuke exemption) ─────────────────────────────────
    async def add_trusted_role(self, guild_id, role_id):
        await self._execute('INSERT OR IGNORE INTO trusted_roles VALUES (?,?)', (guild_id, role_id))
    async def remove_trusted_role(self, guild_id, role_id):
        await self._execute('DELETE FROM trusted_roles WHERE guild_id=? AND role_id=?', (guild_id, role_id))
    async def get_trusted_roles(self, guild_id):
        rows = await self._fetchall('SELECT role_id FROM trusted_roles WHERE guild_id=?', (guild_id,))
        return [r[0] for r in rows]
    async def is_trusted_role(self, guild_id, role_id):
        return await self._fetchone('SELECT 1 FROM trusted_roles WHERE guild_id=? AND role_id=?', (guild_id, role_id)) is not None
    async def is_trusted_by_role(self, guild_id, member_role_ids):
        trusted = await self.get_trusted_roles(guild_id)
        return any(r in trusted for r in member_role_ids)

    # ─── Lockdown member role ─────────────────────────────────────────────────
    async def set_lockdown_member_role(self, guild_id, role_id):
        await self._ensure_guild_settings(guild_id)
        await self._execute('UPDATE guild_settings SET lockdown_member_role_id=? WHERE guild_id=?', (role_id, guild_id))
    async def get_lockdown_member_role(self, guild_id):
        r = await self._fetchone('SELECT lockdown_member_role_id FROM guild_settings WHERE guild_id=?', (guild_id,))
        return r[0] if r else None

    # ─── Mod Log Filters ──────────────────────────────────────────────────────
    async def _ensure_mod_log_filters(self, guild_id):
        await self._execute('INSERT OR IGNORE INTO mod_log_filters (guild_id) VALUES (?)', (guild_id,))
    async def get_mod_log_filters(self, guild_id):
        await self._ensure_mod_log_filters(guild_id)
        r = await self._fetchone('SELECT * FROM mod_log_filters WHERE guild_id=?', (guild_id,))
        if not r: return {}
        d = dict(r)
        for k in ('ignored_users', 'ignored_roles', 'ignored_actions'):
            try: d[k] = json.loads(d[k]) if d[k] else []
            except: d[k] = []
        return d
    async def set_mod_log_filter(self, guild_id, key, value):
        bool_keys = {
            'enabled','ignore_bots','log_warns','log_mutes','log_kicks',
            'log_bans','log_unbans','log_jails','log_lockdowns','log_massbans',
            'log_antinuke','log_notes','log_slowmode','log_purge'
        }
        list_keys = {'ignored_users','ignored_roles','ignored_actions'}
        await self._ensure_mod_log_filters(guild_id)
        if key in bool_keys:
            await self._execute(f'UPDATE mod_log_filters SET {key}=? WHERE guild_id=?', (1 if value else 0, guild_id))
        elif key in list_keys:
            await self._execute(f'UPDATE mod_log_filters SET {key}=? WHERE guild_id=?', (json.dumps(value), guild_id))
        else:
            raise ValueError(f"Invalid filter key: {key}")
    async def should_log_mod_action(self, guild_id, action, moderator_id=None, target_id=None, moderator_roles=None):
        """Returns True if this action should be logged given current filters."""
        f = await self.get_mod_log_filters(guild_id)
        if not f.get('enabled', 1): return False
        action_map = {
            'warn': 'log_warns', 'mute': 'log_mutes', 'kick': 'log_kicks',
            'ban': 'log_bans', 'unban': 'log_unbans', 'jail': 'log_jails',
            'lockdown': 'log_lockdowns', 'massban': 'log_massbans',
            'antinuke': 'log_antinuke', 'note': 'log_notes',
            'slowmode': 'log_slowmode', 'purge': 'log_purge'
        }
        flag = action_map.get(action)
        if flag and not f.get(flag, 1): return False
        ignored_actions = f.get('ignored_actions', [])
        if action in ignored_actions: return False
        if moderator_id:
            ignored_users = f.get('ignored_users', [])
            if moderator_id in ignored_users: return False
        if moderator_roles:
            ignored_roles = f.get('ignored_roles', [])
            if any(r in ignored_roles for r in moderator_roles): return False
        return True

    # ─── Invite Tracker ───────────────────────────────────────────────────────
    async def record_invite(self, guild_id, user_id, inviter_id, invite_code):
        await self._execute(
            'INSERT OR REPLACE INTO invite_tracker (guild_id,user_id,inviter_id,invite_code,joined_at) VALUES (?,?,?,?,?)',
            (guild_id, user_id, inviter_id, invite_code, int(time.time()))
        )
    async def get_inviter(self, guild_id, user_id):
        r = await self._fetchone('SELECT inviter_id,invite_code,joined_at FROM invite_tracker WHERE guild_id=? AND user_id=?', (guild_id, user_id))
        return dict(r) if r else None
    async def get_invited_by(self, guild_id, inviter_id):
        rows = await self._fetchall('SELECT user_id,invite_code,joined_at FROM invite_tracker WHERE guild_id=? AND inviter_id=?', (guild_id, inviter_id))
        return [dict(r) for r in rows]
    async def get_invite_leaderboard(self, guild_id, limit=20):
        rows = await self._fetchall(
            'SELECT inviter_id, COUNT(*) as cnt FROM invite_tracker WHERE guild_id=? GROUP BY inviter_id ORDER BY cnt DESC LIMIT ?',
            (guild_id, limit)
        )
        return [{'inviter_id': r[0], 'count': r[1]} for r in rows]

    # ─── Mod Action History ───────────────────────────────────────────────────
    async def log_mod_action(self, guild_id, target_id, moderator_id, action, reason='', extra=None):
        await self._execute(
            'INSERT INTO mod_action_history (guild_id,target_id,moderator_id,action,reason,timestamp,extra) VALUES (?,?,?,?,?,?,?)',
            (guild_id, target_id, moderator_id, action, reason or '', int(time.time()), json.dumps(extra) if extra else None)
        )
    async def search_mod_actions(self, guild_id, target_id=None, moderator_id=None, action=None, limit=50, offset=0):
        conditions = ['guild_id=?']
        params = [guild_id]
        if target_id: conditions.append('target_id=?'); params.append(target_id)
        if moderator_id: conditions.append('moderator_id=?'); params.append(moderator_id)
        if action: conditions.append('action=?'); params.append(action)
        where = ' AND '.join(conditions)
        params.extend([limit, offset])
        rows = await self._fetchall(
            f'SELECT id,target_id,moderator_id,action,reason,timestamp,extra FROM mod_action_history WHERE {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?',
            tuple(params)
        )
        result = []
        for r in rows:
            d = dict(r)
            try: d['extra'] = json.loads(d['extra']) if d['extra'] else None
            except: d['extra'] = None
            result.append(d)
        return result
    async def count_mod_actions(self, guild_id, target_id=None, moderator_id=None, action=None):
        conditions = ['guild_id=?']
        params = [guild_id]
        if target_id: conditions.append('target_id=?'); params.append(target_id)
        if moderator_id: conditions.append('moderator_id=?'); params.append(moderator_id)
        if action: conditions.append('action=?'); params.append(action)
        where = ' AND '.join(conditions)
        r = await self._fetchone(f'SELECT COUNT(*) FROM mod_action_history WHERE {where}', tuple(params))
        return r[0] if r else 0