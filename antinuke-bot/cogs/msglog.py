import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import time
from collections import deque


# ── Rate-limit config ────────────────────────────────────────────────────────
# Max 8 log embeds per 5 seconds per guild before queuing.
RATE_LIMIT_MAX   = 8
RATE_LIMIT_WINDOW = 5.0   # seconds


class GuildRateLimiter:
    """Token-bucket rate limiter per guild.  Thread-safe for asyncio."""

    def __init__(self, max_tokens: int, window: float):
        self.max_tokens = max_tokens
        self.window = window
        self._tokens: dict[int, list] = {}   # guild_id -> list of timestamps
        self._queues: dict[int, deque] = {}  # guild_id -> deque of (embed, channel_id)

    def _cleanup(self, guild_id: int):
        now = time.monotonic()
        self._tokens.setdefault(guild_id, [])
        self._tokens[guild_id] = [t for t in self._tokens[guild_id] if now - t < self.window]

    def try_consume(self, guild_id: int) -> bool:
        self._cleanup(guild_id)
        if len(self._tokens[guild_id]) < self.max_tokens:
            self._tokens[guild_id].append(time.monotonic())
            return True
        return False

    def enqueue(self, guild_id: int, channel_id: int, embed: discord.Embed):
        self._queues.setdefault(guild_id, deque())
        self._queues[guild_id].append((channel_id, embed))

    def has_queued(self, guild_id: int) -> bool:
        return bool(self._queues.get(guild_id))

    def pop_queued(self, guild_id: int):
        q = self._queues.get(guild_id)
        if q:
            return q.popleft()
        return None


class MessageLog(commands.Cog):
    """Full message logging with rate-limiting and per-event customization."""

    def __init__(self, bot):
        self.bot = bot
        self.rl = GuildRateLimiter(RATE_LIMIT_MAX, RATE_LIMIT_WINDOW)
        # Cache message content for edit/delete tracking (memory-only, cleared on restart)
        self._msg_cache: dict[int, dict] = {}   # message_id -> {content, author_id, channel_id, guild_id}
        self._flush_queues.start()

    def cog_unload(self):
        self._flush_queues.cancel()

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _get_settings(self, guild_id: int) -> dict:
        return await self.bot.db.get_msg_log_settings(guild_id)

    def _is_authorized(self, interaction: discord.Interaction) -> bool:
        return (
            interaction.user.guild_permissions.administrator
            or interaction.user.id == interaction.guild.owner_id
            or self.bot.loop.run_until_complete(
                self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
            )
        )

    async def _auth_check(self, interaction: discord.Interaction) -> bool:
        await interaction.response.defer()
        ok = (
            interaction.user.guild_permissions.administrator
            or interaction.user.id == interaction.guild.owner_id
            or await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        )
        if not ok:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description="You need **Administrator** or be a bot admin to configure message logging.",
                    color=0xff0000
                ),
                ephemeral=True
            )
        return ok

    async def _send_log(self, guild_id: int, channel_id: int, embed: discord.Embed):
        """Send to channel respecting rate limit; queue if rate-limited."""
        if self.rl.try_consume(guild_id):
            ch = self.bot.get_channel(channel_id)
            if ch:
                try:
                    await ch.send(embed=embed)
                except discord.Forbidden:
                    pass
        else:
            self.rl.enqueue(guild_id, channel_id, embed)

    @tasks.loop(seconds=2)
    async def _flush_queues(self):
        """Drain queues for guilds whose rate limit has recovered."""
        for guild_id in list(self.rl._queues.keys()):
            while self.rl.has_queued(guild_id) and self.rl.try_consume(guild_id):
                item = self.rl.pop_queued(guild_id)
                if item:
                    channel_id, embed = item
                    ch = self.bot.get_channel(channel_id)
                    if ch:
                        try:
                            await ch.send(embed=embed)
                        except discord.Forbidden:
                            pass
                    await asyncio.sleep(0.1)

    @_flush_queues.before_loop
    async def _before_flush(self):
        await self.bot.wait_until_ready()

    async def _should_log(self, guild_id: int, event_key: str, author: discord.Member | discord.User | None, channel: discord.abc.GuildChannel | None, settings: dict) -> tuple[bool, int | None]:
        """Returns (should_log, channel_id)."""
        if not settings.get('enabled', 1):
            return False, None
        ch_id = settings.get('channel_id')
        if not ch_id:
            return False, None
        if not settings.get(event_key, 1):
            return False, None

        # Ignore bots
        if settings.get('ignore_bots', 1) and author and getattr(author, 'bot', False):
            return False, None

        # Ignored channels
        ignored_channels = settings.get('ignored_channels', [])
        if channel and channel.id in ignored_channels:
            return False, None

        # Ignored roles (only for members)
        if isinstance(author, discord.Member):
            ignored_roles = settings.get('ignored_roles', [])
            if any(r.id in ignored_roles for r in author.roles):
                return False, None

        return True, ch_id

    # ── Cache management ─────────────────────────────────────────────────────

    def _cache_message(self, message: discord.Message):
        if not message.guild:
            return
        self._msg_cache[message.id] = {
            'content': message.content,
            'author_id': message.author.id,
            'channel_id': message.channel.id,
            'guild_id': message.guild.id,
            'author_name': str(message.author),
            'author_avatar': message.author.display_avatar.url,
        }
        # Keep cache from growing unbounded: drop oldest if over 5000 entries
        if len(self._msg_cache) > 5000:
            oldest_key = next(iter(self._msg_cache))
            del self._msg_cache[oldest_key]

    # ── Discord events ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        self._cache_message(message)
        settings = await self._get_settings(message.guild.id)
        ok, ch_id = await self._should_log(message.guild.id, 'log_sent', message.author, message.channel, settings)
        if not ok:
            return

        embed = discord.Embed(
            title="💬 Message Sent",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="Author", value=f"{message.author.mention} `{message.author.id}`", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        if message.content:
            content = message.content[:1000] + ("…" if len(message.content) > 1000 else "")
            embed.add_field(name="Content", value=content, inline=False)
        if message.attachments:
            embed.add_field(name=f"Attachments ({len(message.attachments)})", value="\n".join(a.filename for a in message.attachments), inline=False)
        embed.set_footer(text=f"Message ID: {message.id}")
        await self._send_log(message.guild.id, ch_id, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild:
            return
        if before.content == after.content:
            return
        self._cache_message(after)
        settings = await self._get_settings(after.guild.id)
        ok, ch_id = await self._should_log(after.guild.id, 'log_edited', after.author, after.channel, settings)
        if not ok:
            return

        embed = discord.Embed(
            title="✏️ Message Edited",
            color=0xffaa00,
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=str(after.author), icon_url=after.author.display_avatar.url)
        embed.add_field(name="Author", value=f"{after.author.mention} `{after.author.id}`", inline=True)
        embed.add_field(name="Channel", value=after.channel.mention, inline=True)
        embed.add_field(name="Jump to Message", value=f"[Click here]({after.jump_url})", inline=True)
        before_content = (before.content or "*empty*")[:900] + ("…" if len(before.content or "") > 900 else "")
        after_content  = (after.content  or "*empty*")[:900] + ("…" if len(after.content  or "") > 900 else "")
        embed.add_field(name="Before", value=before_content, inline=False)
        embed.add_field(name="After",  value=after_content,  inline=False)
        embed.set_footer(text=f"Message ID: {after.id}")
        await self._send_log(after.guild.id, ch_id, embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return
        settings = await self._get_settings(message.guild.id)
        # Try cached version first (more reliable)
        cached = self._msg_cache.pop(message.id, None)
        author = message.author
        channel = message.channel

        ok, ch_id = await self._should_log(message.guild.id, 'log_deleted', author, channel, settings)
        if not ok:
            return

        content = (cached or {}).get('content') or message.content or "*Content unavailable*"
        embed = discord.Embed(
            title="🗑️ Message Deleted",
            color=0xff0000,
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=str(author), icon_url=author.display_avatar.url)
        embed.add_field(name="Author", value=f"{author.mention} `{author.id}`", inline=True)
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        display_content = content[:1000] + ("…" if len(content) > 1000 else "")
        embed.add_field(name="Content", value=display_content, inline=False)
        if message.attachments:
            embed.add_field(name=f"Attachments ({len(message.attachments)})", value="\n".join(a.filename for a in message.attachments), inline=False)
        embed.set_footer(text=f"Message ID: {message.id}")
        await self._send_log(message.guild.id, ch_id, embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages:
            return
        guild = messages[0].guild
        if not guild:
            return
        settings = await self._get_settings(guild.id)
        # Use any message's channel for the check
        channel = messages[0].channel
        ok, ch_id = await self._should_log(guild.id, 'log_bulk_delete', None, channel, settings)
        if not ok:
            return

        # Clean cache
        for m in messages:
            self._msg_cache.pop(m.id, None)

        embed = discord.Embed(
            title="🗑️ Bulk Message Delete",
            description=f"**{len(messages)}** messages were deleted in {channel.mention}.",
            color=0xff4444,
            timestamp=discord.utils.utcnow()
        )
        # List up to 10 authors
        authors = {}
        for m in messages:
            authors[m.author.id] = str(m.author)
        author_list = "\n".join(f"• {name} (`{uid}`)" for uid, name in list(authors.items())[:10])
        if len(authors) > 10:
            author_list += f"\n…and {len(authors) - 10} more"
        embed.add_field(name="Authors", value=author_list or "Unknown", inline=False)
        embed.set_footer(text=f"Channel ID: {channel.id}")
        await self._send_log(guild.id, ch_id, embed)

    # ── Slash commands ───────────────────────────────────────────────────────

    msglog_group = app_commands.Group(name="msglog", description="📨 Message logging configuration")

    @msglog_group.command(name="setup", description="📨 Set the channel for message logs")
    @app_commands.describe(channel="Channel to send message logs to")
    async def msglog_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer()
        if not await self._auth_check(interaction):
            return
        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Missing Permissions", description=f"I can't send messages in {channel.mention}.", color=0xff0000),
                ephemeral=True
            )
            return
        await self.bot.db.set_msg_log_channel(interaction.guild.id, channel.id)

        # Log to mod log
        log_ch_id = await self.bot.db.get_log_channel(interaction.guild.id)
        if log_ch_id:
            log_ch = interaction.guild.get_channel(log_ch_id)
            if log_ch:
                le = discord.Embed(title="📨 Message Log Setup", color=0x5865f2, timestamp=discord.utils.utcnow())
                le.add_field(name="Set By", value=f"{interaction.user.mention} `{interaction.user.id}`", inline=True)
                le.add_field(name="Log Channel", value=channel.mention, inline=True)
                await log_ch.send(embed=le)

        embed = discord.Embed(title="✅ Message Log Channel Set", description=f"Message logs will be sent to {channel.mention}.\nAll event types are **enabled** by default.", color=0x57f287, timestamp=discord.utils.utcnow())
        embed.add_field(name="💡 Tip", value="Use `/msglog toggle` to enable/disable logging, or `/msglog event` to control individual event types.", inline=False)
        await interaction.followup.send(embed=embed)

    @msglog_group.command(name="toggle", description="🔛 Enable or disable message logging entirely")
    @app_commands.describe(enabled="True to enable, False to disable")
    async def msglog_toggle(self, interaction: discord.Interaction, enabled: bool):
        await interaction.response.defer()
        if not await self._auth_check(interaction):
            return
        await self.bot.db.set_msg_log_enabled(interaction.guild.id, enabled)

        log_ch_id = await self.bot.db.get_log_channel(interaction.guild.id)
        if log_ch_id:
            log_ch = interaction.guild.get_channel(log_ch_id)
            if log_ch:
                le = discord.Embed(title=f"📨 Message Logging {'Enabled' if enabled else 'Disabled'}", color=0x57f287 if enabled else 0xff0000, timestamp=discord.utils.utcnow())
                le.add_field(name="Changed By", value=f"{interaction.user.mention} `{interaction.user.id}`", inline=True)
                await log_ch.send(embed=le)

        status = "enabled ✅" if enabled else "disabled ❌"
        embed = discord.Embed(title=f"📨 Message Logging {status.title()}", description=f"Message logging has been **{status}**.", color=0x57f287 if enabled else 0xff0000)
        await interaction.followup.send(embed=embed)

    @msglog_group.command(name="event", description="🎛️ Toggle a specific message log event type")
    @app_commands.describe(
        event="Which event type to toggle",
        enabled="True to log this event, False to ignore it"
    )
    @app_commands.choices(event=[
        app_commands.Choice(name="Sent Messages",   value="log_sent"),
        app_commands.Choice(name="Edited Messages", value="log_edited"),
        app_commands.Choice(name="Deleted Messages",value="log_deleted"),
        app_commands.Choice(name="Bulk Deletes",    value="log_bulk_delete"),
        app_commands.Choice(name="Ignore Bots",     value="ignore_bots"),
    ])
    async def msglog_event(self, interaction: discord.Interaction, event: str, enabled: bool):
        await interaction.response.defer()
        if not await self._auth_check(interaction):
            return
        await self.bot.db.set_msg_log_event(interaction.guild.id, event, enabled)

        label_map = {
            'log_sent':        'Sent Messages',
            'log_edited':      'Edited Messages',
            'log_deleted':     'Deleted Messages',
            'log_bulk_delete': 'Bulk Deletes',
            'ignore_bots':     'Ignore Bots',
        }
        label = label_map.get(event, event)

        log_ch_id = await self.bot.db.get_log_channel(interaction.guild.id)
        if log_ch_id:
            log_ch = interaction.guild.get_channel(log_ch_id)
            if log_ch:
                le = discord.Embed(title="📨 Message Log Event Updated", color=0x57f287 if enabled else 0xff0000, timestamp=discord.utils.utcnow())
                le.add_field(name="Event", value=label, inline=True)
                le.add_field(name="Status", value="Enabled ✅" if enabled else "Disabled ❌", inline=True)
                le.add_field(name="Changed By", value=f"{interaction.user.mention} `{interaction.user.id}`", inline=True)
                await log_ch.send(embed=le)

        status = "enabled ✅" if enabled else "disabled ❌"
        embed = discord.Embed(
            title=f"🎛️ Event Updated",
            description=f"**{label}** is now **{status}**.",
            color=0x57f287 if enabled else 0xff0000
        )
        await interaction.followup.send(embed=embed)

    @msglog_group.command(name="ignorechannel", description="🚫 Ignore or unignore a channel from message logs")
    @app_commands.describe(channel="Channel to toggle", ignore="True to ignore, False to unignore")
    async def msglog_ignorechannel(self, interaction: discord.Interaction, channel: discord.TextChannel, ignore: bool):
        await interaction.response.defer()
        if not await self._auth_check(interaction):
            return
        settings = await self._get_settings(interaction.guild.id)
        ignored = settings.get('ignored_channels', [])
        if ignore:
            if channel.id not in ignored:
                ignored.append(channel.id)
        else:
            ignored = [c for c in ignored if c != channel.id]
        await self.bot.db.set_msg_log_ignored_channels(interaction.guild.id, ignored)

        action = "will now be **ignored**" if ignore else "will now be **logged**"
        embed = discord.Embed(title="🚫 Channel Updated", description=f"{channel.mention} {action} in message logs.", color=0xffaa00)
        await interaction.followup.send(embed=embed)

    @msglog_group.command(name="ignorerole", description="🚫 Ignore or unignore a role from message logs")
    @app_commands.describe(role="Role to toggle", ignore="True to ignore, False to unignore")
    async def msglog_ignorerole(self, interaction: discord.Interaction, role: discord.Role, ignore: bool):
        await interaction.response.defer()
        if not await self._auth_check(interaction):
            return
        settings = await self._get_settings(interaction.guild.id)
        ignored = settings.get('ignored_roles', [])
        if ignore:
            if role.id not in ignored:
                ignored.append(role.id)
        else:
            ignored = [r for r in ignored if r != role.id]
        await self.bot.db.set_msg_log_ignored_roles(interaction.guild.id, ignored)

        action = "will now be **ignored**" if ignore else "will now be **logged**"
        embed = discord.Embed(title="🚫 Role Updated", description=f"{role.mention} members {action} in message logs.", color=0xffaa00)
        await interaction.followup.send(embed=embed)

    @msglog_group.command(name="status", description="📋 View current message log configuration")
    async def msglog_status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not await self._auth_check(interaction):
            return
        settings = await self._get_settings(interaction.guild.id)

        ch_id = settings.get('channel_id')
        ch_mention = f"<#{ch_id}>" if ch_id else "❌ Not Set"
        on_off = lambda v: "✅ On" if v else "❌ Off"

        embed = discord.Embed(title="📨 Message Log Configuration", color=0x5865f2, timestamp=discord.utils.utcnow())
        embed.add_field(name="Log Channel",      value=ch_mention,                                  inline=True)
        embed.add_field(name="Enabled",          value=on_off(settings.get('enabled', 1)),          inline=True)
        embed.add_field(name="\u200b",           value="\u200b",                                    inline=True)
        embed.add_field(name="Sent Messages",    value=on_off(settings.get('log_sent', 1)),         inline=True)
        embed.add_field(name="Edited Messages",  value=on_off(settings.get('log_edited', 1)),       inline=True)
        embed.add_field(name="Deleted Messages", value=on_off(settings.get('log_deleted', 1)),      inline=True)
        embed.add_field(name="Bulk Deletes",     value=on_off(settings.get('log_bulk_delete', 1)), inline=True)
        embed.add_field(name="Ignore Bots",      value=on_off(settings.get('ignore_bots', 1)),     inline=True)
        embed.add_field(name="\u200b",           value="\u200b",                                    inline=True)

        ignored_channels = settings.get('ignored_channels', [])
        ic_val = ", ".join(f"<#{c}>" for c in ignored_channels) if ignored_channels else "None"
        embed.add_field(name=f"Ignored Channels ({len(ignored_channels)})", value=ic_val[:400], inline=False)

        ignored_roles = settings.get('ignored_roles', [])
        ir_val = ", ".join(f"<@&{r}>" for r in ignored_roles) if ignored_roles else "None"
        embed.add_field(name=f"Ignored Roles ({len(ignored_roles)})", value=ir_val[:400], inline=False)

        embed.add_field(
            name="⚡ Rate Limit",
            value=f"Max **{RATE_LIMIT_MAX}** log entries per **{RATE_LIMIT_WINDOW:.0f}s** — excess entries are queued and sent automatically.",
            inline=False
        )
        embed.set_footer(text="VO AntiNuke • Message Log")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(MessageLog(bot))