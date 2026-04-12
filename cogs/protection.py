import discord
from discord.ext import commands, tasks
import time
import asyncio
from datetime import timedelta
from typing import Dict, List, Optional, Set
from collections import defaultdict
from cogs.dmalerts import send_dm_alert as _send_dm_alert

DANGEROUS_PERMISSION_FLAGS = (
    discord.Permissions(administrator=True).value,
    discord.Permissions(kick_members=True).value,
    discord.Permissions(ban_members=True).value,
    discord.Permissions(manage_guild=True).value,
    discord.Permissions(manage_roles=True).value,
    discord.Permissions(manage_channels=True).value,
    discord.Permissions(manage_webhooks=True).value,
    discord.Permissions(mention_everyone=True).value,
    discord.Permissions(manage_expressions=True).value,
    discord.Permissions(manage_threads=True).value,
)

DEFAULT_SETTINGS = {
    'banning_members':              {'limit': 3,  'timeframe': 10,  'punishment': 'ban'},
    'kicking_members':              {'limit': 3,  'timeframe': 10,  'punishment': 'ban'},
    'creating_channels':            {'limit': 3,  'timeframe': 10,  'punishment': 'ban'},
    'deleting_channels':            {'limit': 2,  'timeframe': 10,  'punishment': 'ban'},
    'creating_roles':               {'limit': 3,  'timeframe': 10,  'punishment': 'ban'},
    'deleting_roles':               {'limit': 2,  'timeframe': 10,  'punishment': 'ban'},
    'editing_channels':             {'limit': 5,  'timeframe': 10,  'punishment': 'ban'},
    'editing_roles':                {'limit': 5,  'timeframe': 10,  'punishment': 'ban'},
    'giving_dangerous_permissions': {'limit': 1,  'timeframe': 10,  'punishment': 'ban'},
    'giving_administrative_roles':  {'limit': 1,  'timeframe': 10,  'punishment': 'ban'},
    'adding_bots':                  {'limit': 1,  'timeframe': 60,  'punishment': 'ban'},
    'updating_server':              {'limit': 2,  'timeframe': 10,  'punishment': 'ban'},
    'creating_webhooks':            {'limit': 2,  'timeframe': 10,  'punishment': 'ban'},
    'deleting_webhooks':            {'limit': 3,  'timeframe': 10,  'punishment': 'ban'},
    'authorizing_applications':     {'limit': 1,  'timeframe': 60,  'punishment': 'ban'},
    'timing_out_members':           {'limit': 3,  'timeframe': 10,  'punishment': 'ban'},
    'changing_nicknames':           {'limit': 5,  'timeframe': 10,  'punishment': 'kick'},
    'pruning_members':              {'limit': 1,  'timeframe': 60,  'punishment': 'ban'},
}


def has_dangerous_permissions(permissions: discord.Permissions) -> bool:
    for flag in DANGEROUS_PERMISSION_FLAGS:
        if permissions.value & flag:
            return True
    return False


class PendingTracker:
    """In-memory pending tracker backed by the DB for restart recovery."""

    def __init__(self, db):
        self._db = db
        self._data: Dict[int, Dict[int, Dict[str, List]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )

    def add(self, guild_id: int, user_id: int, action: str, target_data):
        if target_data is not None:
            self._data[guild_id][user_id][action].append(target_data)
            # Persist serialisable target data for recovery.
            # discord objects (Member, Role, etc.) can't be serialised, so we
            # only persist the plain-dict parts (IDs and simple values).
            try:
                serialisable = {k: v for k, v in target_data.items()
                                if isinstance(v, (int, str, float, bool, type(None)))}
                if serialisable:
                    asyncio.ensure_future(
                        self._db.save_pending_action(guild_id, user_id, action, serialisable)
                    )
            except Exception:
                pass

    def pop_all(self, guild_id: int, user_id: int, action: str) -> List:
        result = self._data[guild_id][user_id].pop(action, [])
        asyncio.ensure_future(
            self._db.clear_pending_actions(guild_id, user_id, action)
        )
        return result


class Protection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_cache: Dict[int, Dict[int, dict]] = {}
        self.role_cache: Dict[int, Dict[int, dict]] = {}
        self.server_cache: Dict[int, dict] = {}
        self.nickname_cache: Dict[int, Dict[int, Optional[str]]] = {}
        self.pending = PendingTracker(bot.db)

        self._nuker_created_channels: Dict[int, Set[int]] = defaultdict(set)

        self.cache_updater.start()
        self.cleanup_task.start()

    def cog_unload(self):
        self.cache_updater.cancel()
        self.cleanup_task.cancel()

    # ------------------------------------------------------------------ cache

    @tasks.loop(minutes=5)
    async def cache_updater(self):
        for guild in self.bot.guilds:
            await self.cache_guild_state(guild)

    @tasks.loop(hours=1)
    async def cleanup_task(self):
        """Periodically clean up old action logs and expired temp whitelists."""
        try:
            await self.bot.db.cleanup_old_logs(older_than_seconds=86400)
            await self.bot.db.cleanup_expired_temp_whitelist()
            await self.bot.db.cleanup_old_pending_actions(older_than_seconds=3600)
        except Exception as e:
            print(f'[AntiNuke] Cleanup error: {e}')

    @cache_updater.before_loop
    async def before_cache_updater(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self.apply_default_settings(guild)
            await self.cache_guild_state(guild)

    @cleanup_task.before_loop
    async def before_cleanup_task(self):
        await self.bot.wait_until_ready()

    async def apply_default_settings(self, guild: discord.Guild):
        for action, defaults in DEFAULT_SETTINGS.items():
            existing_limit = await self.bot.db.get_limit(guild.id, action)
            if existing_limit is None:
                await self.bot.db.set_limit(guild.id, action, defaults['limit'])
                await self.bot.db.set_timeframe(guild.id, action, defaults['timeframe'])
                await self.bot.db.set_punishment(guild.id, action, defaults['punishment'])

    async def cache_guild_state(self, guild: discord.Guild):
        self.channel_cache.setdefault(guild.id, {})
        self.role_cache.setdefault(guild.id, {})
        self.server_cache.setdefault(guild.id, {})
        self.nickname_cache.setdefault(guild.id, {})

        for channel in guild.channels:
            self.channel_cache[guild.id][channel.id] = self._serialize_channel(channel)

        for role in guild.roles:
            if role != guild.default_role:
                self.role_cache[guild.id][role.id] = self._serialize_role(role)

        for member in guild.members:
            self.nickname_cache[guild.id][member.id] = member.nick

        self.server_cache[guild.id] = {
            'name': guild.name,
            'vanity_url': guild.vanity_url_code,
            'icon': str(guild.icon.url) if guild.icon else None,
            'banner': str(guild.banner.url) if guild.banner else None,
            'description': guild.description,
        }

    # ---------------------------------------------------------------- helpers

    def _serialize_channel(self, channel: discord.abc.GuildChannel) -> dict:
        data = {
            'id': channel.id,
            'name': channel.name,
            'type': str(channel.type),
            'position': channel.position,
            'category_id': channel.category.id if channel.category else None,
            'overwrites': {},
        }
        if isinstance(channel, discord.TextChannel):
            data['topic'] = channel.topic
            data['slowmode_delay'] = channel.slowmode_delay
            data['nsfw'] = channel.nsfw
        elif isinstance(channel, discord.VoiceChannel):
            data['bitrate'] = channel.bitrate
            data['user_limit'] = channel.user_limit
        elif isinstance(channel, discord.StageChannel):
            data['bitrate'] = getattr(channel, 'bitrate', 64000)
            data['user_limit'] = getattr(channel, 'user_limit', 0)
        elif isinstance(channel, discord.ForumChannel):
            data['topic'] = getattr(channel, 'topic', None)
            data['slowmode_delay'] = getattr(channel, 'slowmode_delay', 0)
            data['nsfw'] = getattr(channel, 'nsfw', False)

        for target, overwrite in channel.overwrites.items():
            key = (f"role_{target.id}" if isinstance(target, discord.Role)
                   else f"member_{target.id}")
            allow, deny = overwrite.pair()
            data['overwrites'][key] = {'allow': allow.value, 'deny': deny.value}
        return data

    def _serialize_role(self, role: discord.Role) -> dict:
        return {
            'id': role.id,
            'name': role.name,
            'color': role.color.value,
            'permissions': role.permissions.value,
            'position': role.position,
            'hoist': role.hoist,
            'mentionable': role.mentionable,
        }

    def _bot_member(self, guild: discord.Guild) -> Optional[discord.Member]:
        return guild.get_member(self.bot.user.id)

    def _build_overwrites(self, guild: discord.Guild, raw: dict) -> dict:
        overwrites = {}
        for key, perms in raw.items():
            if key.startswith('role_'):
                obj = guild.get_role(int(key[5:]))
            elif key.startswith('member_'):
                obj = guild.get_member(int(key[7:]))
            else:
                continue
            if obj:
                overwrites[obj] = discord.PermissionOverwrite.from_pair(
                    discord.Permissions(perms['allow']),
                    discord.Permissions(perms['deny']),
                )
        return overwrites

    def _member_role_ids(self, member: discord.Member) -> list:
        return [r.id for r in member.roles]

    # --------------------------------------------------------- channel restore

    async def recreate_channel(
        self,
        guild: discord.Guild,
        data: dict,
        category_map: Optional[Dict[int, discord.CategoryChannel]] = None,
    ) -> Optional[discord.abc.GuildChannel]:
        try:
            old_cat_id = data.get('category_id')
            if category_map and old_cat_id and old_cat_id in category_map:
                category = category_map[old_cat_id]
            elif old_cat_id:
                category = guild.get_channel(old_cat_id)
            else:
                category = None

            overwrites = self._build_overwrites(guild, data.get('overwrites', {}))
            ch_type = data['type']
            reason = "Anti-Nuke: Restoring deleted channel"

            if 'text' in ch_type:
                return await guild.create_text_channel(
                    name=data['name'], category=category, position=data['position'],
                    topic=data.get('topic'), slowmode_delay=data.get('slowmode_delay', 0),
                    nsfw=data.get('nsfw', False), overwrites=overwrites, reason=reason)
            elif 'voice' in ch_type:
                return await guild.create_voice_channel(
                    name=data['name'], category=category, position=data['position'],
                    bitrate=data.get('bitrate', 64000), user_limit=data.get('user_limit', 0),
                    overwrites=overwrites, reason=reason)
            elif 'stage' in ch_type:
                return await guild.create_stage_channel(
                    name=data['name'], category=category, position=data['position'],
                    overwrites=overwrites, reason=reason)
            elif 'forum' in ch_type:
                return await guild.create_forum(
                    name=data['name'], category=category, position=data['position'],
                    topic=data.get('topic'), slowmode_delay=data.get('slowmode_delay', 0),
                    nsfw=data.get('nsfw', False), overwrites=overwrites, reason=reason)
            elif 'category' in ch_type:
                return await guild.create_category(
                    name=data['name'], position=data['position'],
                    overwrites=overwrites, reason=reason)
        except Exception as e:
            print(f"[AntiNuke] Failed to recreate channel '{data.get('name')}': {e}")
        return None

    async def recreate_role(self, guild: discord.Guild, data: dict) -> Optional[discord.Role]:
        try:
            role = await guild.create_role(
                name=data['name'],
                permissions=discord.Permissions(data['permissions']),
                color=discord.Color(data['color']),
                hoist=data['hoist'],
                mentionable=data['mentionable'],
                reason="Anti-Nuke: Restoring deleted role",
            )
            try:
                await role.edit(position=data['position'])
            except Exception:
                pass
            return role
        except Exception as e:
            print(f"[AntiNuke] Failed to recreate role '{data.get('name')}': {e}")
        return None

    # ---------------------------------------------------------------- logging

    async def send_log_embed(self, guild: discord.Guild, embed: discord.Embed):
        log_channel_id = await self.bot.db.get_log_channel(guild.id)
        if log_channel_id:
            ch = guild.get_channel(log_channel_id)
            if ch and ch.permissions_for(guild.me).send_messages:
                try:
                    await ch.send(embed=embed)
                    return
                except Exception:
                    pass
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                try:
                    await ch.send(embed=embed)
                    return
                except Exception:
                    continue

    async def send_dm_alert(self, guild: discord.Guild, embed: discord.Embed, event_type: str = "antinuke"):
        """Send DM alert to all configured targets via the dmalerts routing system."""
        try:
            dm_embed = embed.copy()
            dm_embed.title = f"🚨 [DM Alert] {embed.title or 'Anti-Nuke Alert'}"
            dm_embed.set_footer(text=f"Server: {guild.name} | VO AntiNuke")
            await _send_dm_alert(self.bot, guild, dm_embed, event_type=event_type)
        except Exception:
            pass

    # ------------------------------------------------------------ punishment

    async def _punish_member(self, guild: discord.Guild, member: discord.Member,
                              punishment: str, action: str, info: str):
        bot_me = self._bot_member(guild)
        if not bot_me:
            return

        action_name = action.replace('_', ' ').title()
        reason = f"Anti-Nuke: {action_name}" + (f" | {info}" if info else "")

        if guild.owner_id == member.id:
            embed = discord.Embed(
                title="🚨 Anti-Nuke: Owner Triggered Protection",
                description=(
                    f"{member.mention} is the **server owner** and triggered "
                    f"**{action_name}**. Cannot punish — actions will still be reverted."
                ),
                color=0xff0000,
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Trigger", value=action_name, inline=True)
            embed.add_field(name="Details", value=info or "N/A", inline=True)
            embed.set_footer(text="VO AntiNuke • Protection System")
            await self.send_log_embed(guild, embed)
            await self.send_dm_alert(guild, embed, event_type="antinuke")
            return

        if member.top_role >= bot_me.top_role:
            embed = discord.Embed(
                title="⚠️ Anti-Nuke: Cannot Punish — Role Too High",
                description=(
                    f"{member.mention} triggered **{action_name}** but their "
                    f"top role is equal to or above mine. Actions will still be reverted."
                ),
                color=0xffcc00,
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="User", value=f"{member.mention}\n`{member.id}`", inline=True)
            embed.add_field(name="Trigger", value=action_name, inline=True)
            embed.add_field(name="Details", value=info or "N/A", inline=False)
            embed.set_footer(text="VO AntiNuke • Protection System")
            await self.send_log_embed(guild, embed)
            await self.send_dm_alert(guild, embed, event_type="antinuke")
            return

        color = 0xff4444
        log_msg = ""
        try:
            if punishment == 'ban':
                await member.ban(reason=reason, delete_message_days=0)
                log_msg = f"🔨 Banned {member.mention}"
                color = 0xff4444
            elif punishment == 'kick':
                await member.kick(reason=reason)
                log_msg = f"👢 Kicked {member.mention}"
                color = 0xffa500
            elif punishment == 'clear_roles':
                removable = [r for r in member.roles
                             if r != guild.default_role and r < bot_me.top_role]
                if removable:
                    await member.remove_roles(*removable, reason=reason)
                log_msg = f"🔓 Cleared roles for {member.mention}"
                color = 0xffcc00
            elif punishment == 'timeout':
                await member.timeout(timedelta(days=28), reason=reason)
                log_msg = f"⏰ Timed out {member.mention} (28 days)"
                color = 0xff8800
            elif punishment == 'warn':
                log_msg = f"⚠️ Warning issued to {member.mention}"
                color = 0xffcc00
            else:
                return

            embed = discord.Embed(
                title="🛡️ Anti-Nuke: Threat Neutralised",
                description=log_msg + f" for **{action_name}**",
                color=color,
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="👤 User", value=f"{member.mention}\n`{member.id}`", inline=True)
            embed.add_field(name="⚡ Trigger", value=action_name, inline=True)
            embed.add_field(name="🔨 Punishment", value=punishment.replace('_', ' ').title(), inline=True)
            embed.add_field(name="📋 Reason", value=reason, inline=False)
            if member.display_avatar:
                embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text="VO AntiNuke • Protection System",
                             icon_url=guild.me.display_avatar.url)
            await self.send_log_embed(guild, embed)
            await self.send_dm_alert(guild, embed, event_type="antinuke")

        except discord.Forbidden:
            print(f"[AntiNuke] Forbidden when punishing {member} in {guild}")
        except Exception as e:
            print(f"[AntiNuke] Punishment error: {e}")

    async def _force_ban(self, guild: discord.Guild, target, reason: str):
        try:
            await guild.ban(target, reason=reason, delete_message_days=0)
            embed = discord.Embed(
                title="🔨 Anti-Nuke: Force Banned",
                description=f"{target.mention} was force-banned.",
                color=0xff0000,
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Reason", value=reason)
            embed.set_footer(text="VO AntiNuke • Protection System")
            await self.send_log_embed(guild, embed)
            await self.send_dm_alert(guild, embed, event_type="antinuke")
        except discord.Forbidden:
            print(f"[AntiNuke] Forbidden force-banning {target} in {guild}")
        except Exception as e:
            print(f"[AntiNuke] Force ban error: {e}")

    # ----------------------------------------------------------- revert logic

    async def revert_all(self, guild: discord.Guild, user_id: int, action: str):
        items = self.pending.pop_all(guild.id, user_id, action)
        if not items:
            return

        if action == 'deleting_channels':
            guild_cache = self.channel_cache.get(guild.id, {})
            nuker_created = self._nuker_created_channels.get(guild.id, set())

            category_items = []
            other_items = []
            for item in items:
                ch_id = item.get('channel_id')
                if ch_id in nuker_created:
                    continue
                cached = guild_cache.get(ch_id)
                if cached and 'category' in cached.get('type', ''):
                    category_items.append(item)
                else:
                    other_items.append(item)

            category_map: Dict[int, discord.CategoryChannel] = {}

            for td in sorted(category_items,
                             key=lambda i: guild_cache.get(i.get('channel_id', 0), {}).get('position', 0)):
                ch_id = td.get('channel_id')
                cached = guild_cache.get(ch_id)
                if cached:
                    new_ch = await self.recreate_channel(guild, cached)
                    if new_ch and isinstance(new_ch, discord.CategoryChannel):
                        category_map[ch_id] = new_ch
                        await self._revert_log(guild, "Recreated deleted category", cached['name'])

            async def _restore(td: dict):
                ch_id = td.get('channel_id')
                cached = guild_cache.get(ch_id)
                if cached:
                    new_ch = await self.recreate_channel(guild, cached, category_map)
                    if new_ch:
                        await self._revert_log(guild, "Recreated deleted channel", cached['name'])
                    else:
                        await self._revert_log(guild, "⚠️ Failed to recreate channel",
                                               cached.get('name', str(ch_id)))

            results = await asyncio.gather(*[_restore(td) for td in other_items], return_exceptions=True)

        elif action == 'creating_channels':
            async def _delete_created(td: dict):
                channel = td.get('channel')
                if not channel:
                    return
                self._nuker_created_channels[guild.id].add(channel.id)
                self.channel_cache.get(guild.id, {}).pop(channel.id, None)
                live = guild.get_channel(channel.id)
                if live:
                    try:
                        await live.delete(reason="Anti-Nuke: Unauthorized channel creation")
                        await self._revert_log(guild, "Deleted unauthorized channel", channel.name)
                    except Exception as e:
                        await self._revert_log(guild, "⚠️ Failed to delete spam channel", channel.name)
                        print(f"[AntiNuke] Could not delete spam channel '{channel.name}': {e}")

            results = await asyncio.gather(*[_delete_created(td) for td in items], return_exceptions=True)

        else:
            results = await asyncio.gather(
                *[self._revert_one(guild, action, td) for td in items],
                return_exceptions=True,
            )

        for r in results:
            if isinstance(r, Exception):
                await self._revert_log(guild, f"⚠️ Revert error ({action})", str(r))
                print(f"[AntiNuke] Revert error: {r}")

    async def _revert_one(self, guild: discord.Guild, action: str, td: dict):
        try:
            if action == 'deleting_roles':
                role_id = td.get('role_id')
                cached = self.role_cache.get(guild.id, {}).get(role_id)
                if cached:
                    new_role = await self.recreate_role(guild, cached)
                    if new_role:
                        await self._revert_log(guild, "Recreated deleted role", cached['name'])
                    else:
                        await self._revert_log(guild, "⚠️ Failed to recreate role",
                                               cached.get('name', str(role_id)))

            elif action == 'creating_roles':
                role = td.get('role')
                if role:
                    live = guild.get_role(role.id)
                    if live:
                        await live.delete(reason="Anti-Nuke: Unauthorized role creation")
                        await self._revert_log(guild, "Deleted unauthorized role", role.name)

            elif action == 'banning_members':
                banned_user = td.get('banned_user')
                if banned_user:
                    await guild.unban(banned_user, reason="Anti-Nuke: Reverting unauthorized ban")
                    await self._revert_log(guild, "Unbanned user", str(banned_user))

            elif action == 'kicking_members':
                uid = td.get('kicked_user_id')
                if uid:
                    await self._revert_log(guild, "Member was kicked (cannot reinvite automatically)",
                                           f"User ID: {uid}")

            elif action == 'timing_out_members':
                member = td.get('member')
                if member:
                    live = guild.get_member(member.id)
                    if live and live.timed_out_until:
                        await live.timeout(None, reason="Anti-Nuke: Reverting unauthorized timeout")
                        await self._revert_log(guild, "Removed timeout from member", str(member))

            elif action == 'changing_nicknames':
                member_id = td.get('member_id')
                old_nick = td.get('old_nick')
                if member_id:
                    live = guild.get_member(member_id)
                    if live:
                        await live.edit(nick=old_nick,
                                        reason="Anti-Nuke: Reverting unauthorized nickname change")
                        await self._revert_log(guild, "Reverted nickname",
                                               f"{live} -> {old_nick or '(none)'}")

            elif action == 'updating_server':
                old_name = td.get('old_name')
                old_vanity = td.get('old_vanity')
                if old_name and old_name != guild.name:
                    await guild.edit(name=old_name,
                                     reason="Anti-Nuke: Reverting server name change")
                    await self._revert_log(guild, "Reverted server name", old_name)
                if old_vanity is not None and old_vanity != guild.vanity_url_code:
                    await guild.edit(vanity_code=old_vanity or None,
                                     reason="Anti-Nuke: Reverting vanity URL change")
                    await self._revert_log(guild, "Reverted vanity URL", old_vanity or "None")

            elif action == 'creating_webhooks':
                webhook = td.get('webhook')
                if webhook:
                    try:
                        await webhook.delete(reason="Anti-Nuke: Unauthorized webhook")
                        await self._revert_log(guild, "Deleted unauthorized webhook",
                                               str(getattr(webhook, 'name', webhook.id)))
                    except Exception:
                        pass

            elif action == 'adding_bots':
                bot_member = td.get('bot')
                if bot_member:
                    live = guild.get_member(bot_member.id)
                    target = live or bot_member
                    try:
                        await guild.ban(target,
                                        reason="Anti-Nuke: Unauthorized bot — removed",
                                        delete_message_days=0)
                        await self._revert_log(guild, "Banned unauthorized bot", str(bot_member))
                    except Exception as e:
                        print(f"[AntiNuke] Could not ban unauthorized bot: {e}")

            elif action in ('giving_dangerous_permissions', 'giving_administrative_roles'):
                member = td.get('member')
                role = td.get('role')
                if member and role:
                    live_member = guild.get_member(member.id)
                    live_role = guild.get_role(role.id)
                    bot_me = self._bot_member(guild)
                    if live_member and live_role and bot_me and live_role < bot_me.top_role:
                        await live_member.remove_roles(
                            live_role,
                            reason="Anti-Nuke: Removing unauthorized dangerous role assignment"
                        )
                        await self._revert_log(guild, "Removed dangerous role from member",
                                               f"@{live_role.name} from {live_member}")

        except discord.Forbidden:
            print(f"[AntiNuke] Forbidden reverting {action}")
        except Exception as e:
            print(f"[AntiNuke] Revert error for {action}: {e}")

    async def _revert_log(self, guild: discord.Guild, action: str, target: str):
        embed = discord.Embed(
            title="🔄 Anti-Nuke — Action Reverted",
            description=f"**{action}**: `{target}`",
            color=0x00ffff,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="VO AntiNuke • Protection System")
        await self.send_log_embed(guild, embed)

    # ---------------------------------------------------- check + punish core

    async def check_and_punish(
        self,
        guild: discord.Guild,
        user: discord.User | discord.Member,
        action: str,
        info: str = "",
        target_data: dict = None,
        responsible_user: discord.Member | discord.User | None = None,
    ) -> bool:
        """
        Core detection + punishment method.

        responsible_user: when this bot's own commands are the audit-log actor,
        pass the human who ran the command here so we punish them instead of the bot.
        """
        # Check if this protection is enabled
        if not await self.bot.db.is_protection_enabled(guild.id, action):
            return False

        # --- Resolve who is actually responsible ---

        # If a responsible_user was explicitly passed (our own commands do this),
        # use that directly — no need for any audit log guessing.
        if responsible_user is not None:
            user = responsible_user
        else:
            # Never punish ourselves under any circumstances
            if user.id == self.bot.user.id:
                return False

            actor_member = guild.get_member(user.id)
            is_bot_actor = actor_member is not None and actor_member.bot

            if is_bot_actor:
                # Another bot performed the action. We need the human who told it to.
                # We look up who originally added this bot (recorded in on_member_join).
                #
                # IMPORTANT: if the adder is the server owner, whitelisted, or a bot
                # admin, we do NOT blame them — they added the bot legitimately and
                # are trusted. In that case we still track the action against the bot
                # itself so it can be caught if it goes rogue.
                real_owner_id = await self.bot.db.get_bot_owner(guild.id, user.id)

                if real_owner_id:
                    real_owner = guild.get_member(real_owner_id)

                    if real_owner and real_owner.id != guild.owner_id:
                        adder_role_ids = self._member_role_ids(real_owner)
                        adder_whitelisted = await self.bot.db.is_whitelisted(guild.id, real_owner.id, action=action, member_role_ids=adder_role_ids)
                        adder_is_admin = await self.bot.db.is_admin(guild.id, real_owner.id)

                        if not adder_whitelisted and not adder_is_admin:
                            # Untrusted user added this bot — hold them responsible
                            proxy_embed = discord.Embed(
                                title="🤖 Anti-Nuke: Bot Used as Proxy",
                                description=(
                                    f"**{action.replace('_', ' ').title()}** was performed by bot "
                                    f"{actor_member.mention}. The user who added this bot, "
                                    f"{real_owner.mention}, is being held responsible."
                                ),
                                color=0xff8800,
                                timestamp=discord.utils.utcnow(),
                            )
                            proxy_embed.add_field(name="Bot", value=f"{actor_member.mention}\n`{actor_member.id}`", inline=True)
                            proxy_embed.add_field(name="Held Responsible", value=f"{real_owner.mention}\n`{real_owner.id}`", inline=True)
                            proxy_embed.add_field(name="Action", value=action.replace('_', ' ').title(), inline=True)
                            proxy_embed.set_footer(text="VO AntiNuke • Bot Proxy Detection")
                            await self.send_log_embed(guild, proxy_embed)
                            await self.send_dm_alert(guild, proxy_embed, event_type="antinuke")
                            user = real_owner
                        else:
                            # Trusted user added this bot — track the action against
                            # the bot itself in case it goes rogue
                            pass  # user stays as the bot, falls through to normal tracking
                    else:
                        # Adder left or is the owner — track against the bot itself
                        pass  # user stays as the bot
                else:
                    # No record of who added this bot (was added before VO AntiNuke joined,
                    # or record was lost). Still track and punish the bot itself if it hits
                    # the limit — don't let unknown bots get a free pass.
                    proxy_embed = discord.Embed(
                        title="🤖 Anti-Nuke: Unknown Bot Activity",
                        description=(
                            f"Bot {actor_member.mention} performed **{action.replace('_', ' ').title()}** "
                            f"and has no recorded adder. Tracking actions against the bot directly."
                        ),
                        color=0xff8800,
                        timestamp=discord.utils.utcnow(),
                    )
                    proxy_embed.add_field(name="Bot", value=f"{actor_member.mention}\n`{actor_member.id}`", inline=True)
                    proxy_embed.add_field(name="Action", value=action.replace('_', ' ').title(), inline=True)
                    proxy_embed.set_footer(text="VO AntiNuke • Bot Proxy Detection")
                    await self.send_log_embed(guild, proxy_embed)
                    # user stays as the bot — it will be tracked and punished if it hits the limit

        if target_data is not None:
            self.pending.add(guild.id, user.id, action, target_data)

        # Get role IDs for role-based whitelist check
        member = guild.get_member(user.id)
        role_ids = self._member_role_ids(member) if member else []

        if await self.bot.db.is_whitelisted(guild.id, user.id, action=action, member_role_ids=role_ids):
            return False

        limit = await self.bot.db.get_limit(guild.id, action)
        if limit is None:
            await self.apply_default_settings(guild)
            limit = await self.bot.db.get_limit(guild.id, action)
        if limit is None:
            return False

        timeframe = await self.bot.db.get_timeframe(guild.id, action)
        current_time = int(time.time())
        since_time = current_time - timeframe

        await self.bot.db.log_action(guild.id, user.id, action, current_time)
        action_count = await self.bot.db.get_recent_actions(guild.id, user.id, action, since_time)

        triggered = (limit == 0) or (action_count > limit)
        if not triggered:
            return False

        if member:
            punishment = await self.bot.db.get_punishment(guild.id, action)
            await self._punish_member(guild, member, punishment, action, info)

        await self.revert_all(guild, user.id, action)
        return True

    # ---------------------------------------------------------- guild join

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.apply_default_settings(guild)
        await self.cache_guild_state(guild)

        embed = discord.Embed(
            title="🛡️ Anti-Nuke Protection Active",
            description=(
                "Protection has been automatically enabled with default settings.\n"
                "Use `/setlimit`, `/settime`, and `/setpunishment` to customise any action."
            ),
            color=0x57f287,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Default Limits",
            value=(
                "• Banning/Kicking Members — **3 in 10s → Ban**\n"
                "• Creating/Deleting Channels — **3/2 in 10s → Ban**\n"
                "• Creating/Deleting Roles — **3/2 in 10s → Ban**\n"
                "• Dangerous Permissions / Admin Roles — **1 in 10s → Ban**\n"
                "• Adding Bots / Authorizing Apps — **1 in 60s → Ban**\n"
                "• Creating Webhooks — **2 in 10s → Ban**\n"
                "• Updating Server — **2 in 10s → Ban**\n"
                "• Timing Out Members — **3 in 10s → Ban**\n"
                "• Changing Nicknames — **5 in 10s → Kick**"
            ),
            inline=False,
        )
        embed.set_footer(text="VO AntiNuke • Auto-configured")

        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                try:
                    await ch.send(embed=embed)
                    break
                except Exception:
                    continue

    # ------------------------------------------------------- channel events

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        self.channel_cache.setdefault(guild.id, {})[channel.id] = self._serialize_channel(channel)

        await asyncio.sleep(0.5)
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_create):
            if entry.target.id == channel.id:
                was_punished = await self.check_and_punish(
                    guild, entry.user,
                    'creating_channels',
                    f"Created #{channel.name}",
                    {'channel': channel},
                )
                if was_punished:
                    self._nuker_created_channels[guild.id].add(channel.id)
                    self.channel_cache.get(guild.id, {}).pop(channel.id, None)
                break

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        guild_id = guild.id
        ch_id = channel.id
        self.channel_cache.setdefault(guild_id, {})

        nuker_created = self._nuker_created_channels.get(guild_id, set())
        if ch_id not in self.channel_cache[guild_id] and ch_id not in nuker_created:
            self.channel_cache[guild_id][ch_id] = self._serialize_channel(channel)

        await asyncio.sleep(0.5)
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_delete):
            if entry.target.id == ch_id:
                await self.check_and_punish(
                    guild, entry.user,
                    'deleting_channels',
                    f"Deleted #{channel.name}",
                    {'channel_id': ch_id},
                )
                break

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        self.channel_cache.setdefault(after.guild.id, {})
        if after.id not in self.channel_cache[after.guild.id]:
            self.channel_cache[after.guild.id][after.id] = self._serialize_channel(before)

        await asyncio.sleep(0.5)
        async for entry in after.guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_update):
            if entry.target.id == after.id:
                punished = await self.check_and_punish(
                    after.guild, entry.user,
                    'editing_channels',
                    f"Edited #{after.name}",
                )
                if not punished:
                    self.channel_cache[after.guild.id][after.id] = self._serialize_channel(after)
                break

    # --------------------------------------------------------- role events

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await asyncio.sleep(0.5)
        async for entry in role.guild.audit_logs(limit=5, action=discord.AuditLogAction.role_create):
            if entry.target.id == role.id:
                await self.check_and_punish(
                    role.guild, entry.user,
                    'creating_roles',
                    f"Created @{role.name}",
                    {'role': role},
                )
                break

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        guild_id = role.guild.id
        role_id = role.id
        self.role_cache.setdefault(guild_id, {})
        if role_id not in self.role_cache[guild_id]:
            self.role_cache[guild_id][role_id] = self._serialize_role(role)

        await asyncio.sleep(0.5)
        async for entry in role.guild.audit_logs(limit=5, action=discord.AuditLogAction.role_delete):
            if entry.target.id == role_id:
                await self.check_and_punish(
                    role.guild, entry.user,
                    'deleting_roles',
                    f"Deleted @{role.name}",
                    {'role_id': role_id},
                )
                break

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        self.role_cache.setdefault(after.guild.id, {})
        if after.id not in self.role_cache[after.guild.id]:
            self.role_cache[after.guild.id][after.id] = self._serialize_role(before)

        await asyncio.sleep(0.5)
        async for entry in after.guild.audit_logs(limit=5, action=discord.AuditLogAction.role_update):
            if entry.target.id != after.id:
                continue

            before_p = before.permissions
            after_p = after.permissions

            if not before_p.administrator and after_p.administrator:
                await self.check_and_punish(
                    after.guild, entry.user,
                    'giving_administrative_roles',
                    f"Gave administrator to @{after.name}",
                )
                break

            newly_dangerous = any(
                not (before_p.value & flag) and (after_p.value & flag)
                for flag in DANGEROUS_PERMISSION_FLAGS
            )

            if newly_dangerous:
                punished = await self.check_and_punish(
                    after.guild, entry.user,
                    'giving_dangerous_permissions',
                    f"Gave dangerous permissions to @{after.name}",
                )
            else:
                punished = await self.check_and_punish(
                    after.guild, entry.user,
                    'editing_roles',
                    f"Edited @{after.name}",
                )

            if not punished:
                self.role_cache[after.guild.id][after.id] = self._serialize_role(after)
            break

    # --------------------------------------------------------- member events

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await asyncio.sleep(0.5)
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                await self.check_and_punish(
                    guild, entry.user,
                    'banning_members',
                    f"Banned {user}",
                    {'banned_user': user},
                )
                break

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await asyncio.sleep(0.5)
        async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                await self.check_and_punish(
                    member.guild, entry.user,
                    'kicking_members',
                    f"Kicked {member}",
                    {'kicked_user_id': member.id},
                )
                break

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild

        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until is not None:
                await asyncio.sleep(0.5)
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_update):
                    if entry.target.id == after.id:
                        await self.check_and_punish(
                            guild, entry.user,
                            'timing_out_members',
                            f"Timed out {after}",
                            {'member': after},
                        )
                        break

        if before.nick != after.nick:
            old_nick = self.nickname_cache.get(guild.id, {}).get(after.id)
            self.nickname_cache.setdefault(guild.id, {})[after.id] = after.nick
            await asyncio.sleep(0.5)
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_update):
                if entry.target.id == after.id:
                    await self.check_and_punish(
                        guild, entry.user,
                        'changing_nicknames',
                        f"Changed nickname of {after}",
                        {'member_id': after.id, 'old_nick': old_nick},
                    )
                    break

        if before.roles == after.roles:
            return

        added_roles = set(after.roles) - set(before.roles)
        if not added_roles:
            return

        await asyncio.sleep(0.5)
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_role_update):
            if entry.target.id != after.id:
                continue

            for role in added_roles:
                if role.permissions.administrator:
                    await self.check_and_punish(
                        guild, entry.user,
                        'giving_administrative_roles',
                        f"Gave @{role.name} (admin) to {after}",
                        {'member': after, 'role': role},
                    )
                    return
                if has_dangerous_permissions(role.permissions):
                    await self.check_and_punish(
                        guild, entry.user,
                        'giving_dangerous_permissions',
                        f"Gave @{role.name} (dangerous perms) to {after}",
                        {'member': after, 'role': role},
                    )
                    return
            break

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.bot:
            return

        await asyncio.sleep(1)
        async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
            if entry.target.id != member.id:
                continue

            await self.bot.db.set_bot_owner(member.guild.id, member.id, entry.user.id)

            was_punished = await self.check_and_punish(
                member.guild, entry.user,
                'adding_bots',
                f"Added bot {member} ({member.id})",
                {'bot': member},
            )

            if was_punished:
                live_bot = member.guild.get_member(member.id)
                if live_bot:
                    await self._force_ban(
                        member.guild, live_bot,
                        "Anti-Nuke: Unauthorized bot addition — bot removed"
                    )

                adder = member.guild.get_member(entry.user.id)
                if adder and adder.id != member.guild.owner_id:
                    bot_me = self._bot_member(member.guild)
                    if bot_me and adder.top_role < bot_me.top_role:
                        await self._force_ban(
                            member.guild, adder,
                            "Anti-Nuke: Added unauthorized bot"
                        )
            break

    # --------------------------------------------------------- guild events

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        if before.name != after.name or before.vanity_url_code != after.vanity_url_code:
            await asyncio.sleep(0.5)
            async for entry in after.audit_logs(limit=5, action=discord.AuditLogAction.guild_update):
                await self.check_and_punish(
                    after, entry.user,
                    'updating_server',
                    "Updated server settings",
                    {'old_name': before.name, 'old_vanity': before.vanity_url_code},
                )
                break

        await self.cache_guild_state(after)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.TextChannel):
        await asyncio.sleep(0.5)

        async for entry in channel.guild.audit_logs(limit=3, action=discord.AuditLogAction.webhook_create):
            was_punished = await self.check_and_punish(
                channel.guild, entry.user,
                'creating_webhooks',
                f"Created webhook in #{channel.name}",
                {'webhook': entry.target},
            )
            if was_punished:
                try:
                    webhooks = await channel.webhooks()
                    for wh in webhooks:
                        if wh.id == entry.target.id:
                            await wh.delete(reason="Anti-Nuke: Unauthorized webhook")
                except Exception:
                    pass
            break

        async for entry in channel.guild.audit_logs(limit=3, action=discord.AuditLogAction.webhook_delete):
            await self.check_and_punish(
                channel.guild, entry.user,
                'deleting_webhooks',
                "Deleted webhook",
            )
            break

    @commands.Cog.listener()
    async def on_guild_integrations_update(self, guild: discord.Guild):
        await asyncio.sleep(0.5)
        async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.integration_create):
            await self.check_and_punish(
                guild, entry.user,
                'authorizing_applications',
                "Authorized application",
            )
            break


async def setup(bot):
    await bot.add_cog(Protection(bot))