"""
joinlog.py — Full-featured join/leave logging with invite tracking,
suspicious account detection, welcome messages, and deep customizability.
"""
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import time
from datetime import datetime, timezone

BOT_NAME = "VO AntiNuke"

# Default welcome message template (supports {user}, {server}, {membercount}, {mention})
DEFAULT_WELCOME = "Welcome to **{server}**, {mention}! You are member **#{membercount}**. 🎉"


def _fmt_age(created_at: datetime) -> str:
    now = datetime.now(timezone.utc)
    delta = now - created_at
    days = delta.days
    if days < 1:
        hours = delta.seconds // 3600
        return f"{hours} hour(s)"
    elif days < 30:
        return f"{days} day(s)"
    elif days < 365:
        return f"{days // 30} month(s)"
    else:
        return f"{days // 365} year(s), {(days % 365) // 30} month(s)"


def _is_suspicious(member: discord.Member, cfg: dict) -> tuple[bool, list[str]]:
    flags = []
    threshold = cfg.get('new_account_threshold', 7)
    age_days = (datetime.now(timezone.utc) - member.created_at).days

    if cfg.get('warn_new_accounts', 1) and age_days < threshold:
        flags.append(f"⚠️ Account is only **{age_days}** day(s) old (threshold: {threshold}d)")
    if cfg.get('warn_no_avatar', 1) and member.display_avatar == member.default_avatar:
        flags.append("⚠️ No custom profile picture")
    if member.bot and cfg.get('show_is_bot', 1):
        flags.append("🤖 This is a **bot account**")

    return bool(flags), flags


class JoinLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # invite cache: guild_id -> {code: uses}
        self._invite_cache: dict[int, dict[str, int]] = {}

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        cfg = await self.bot.db.get_join_log_settings(guild.id)
        if not cfg.get('enabled', 1) or not cfg.get('channel_id'):
            return None
        ch = guild.get_channel(cfg['channel_id'])
        if ch and ch.permissions_for(guild.me).send_messages:
            return ch
        return None

    async def _cache_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self._invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except Exception:
            pass

    async def _detect_invite(self, guild: discord.Guild) -> discord.Invite | None:
        try:
            new_invites = await guild.invites()
            old_cache = self._invite_cache.get(guild.id, {})
            for inv in new_invites:
                old_uses = old_cache.get(inv.code, 0)
                if inv.uses > old_uses:
                    self._invite_cache[guild.id] = {i.code: i.uses for i in new_invites}
                    return inv
            self._invite_cache[guild.id] = {i.code: i.uses for i in new_invites}
        except Exception:
            pass
        return None

    # ── Events ────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        await self._cache_invites(invite.guild)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        await self._cache_invites(invite.guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        cfg = await self.bot.db.get_join_log_settings(guild.id)
        if not cfg.get('enabled', 1) or not cfg.get('log_joins', 1):
            return
        channel = await self._get_channel(guild)
        if not channel:
            return

        join_pos = guild.member_count
        age_days = (datetime.now(timezone.utc) - member.created_at).days
        is_suspicious, flags = _is_suspicious(member, cfg)
        color = cfg.get('embed_color_suspicious', 16744272) if is_suspicious else cfg.get('embed_color_join', 5763719)

        embed = discord.Embed(
            title=f"{'⚠️ Suspicious ' if is_suspicious else ''}📥 Member Joined",
            color=color,
            timestamp=discord.utils.utcnow()
        )

        if cfg.get('show_avatar', 1):
            embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="👤 User", value=f"{member.mention}\n`{member}`\n`{member.id}`", inline=True)

        if cfg.get('show_account_age', 1):
            embed.add_field(
                name="🎂 Account Age",
                value=f"{_fmt_age(member.created_at)}\n<t:{int(member.created_at.timestamp())}:D>",
                inline=True
            )

        if cfg.get('show_join_position', 1):
            embed.add_field(name="📊 Join Position", value=f"Member **#{join_pos:,}**", inline=True)

        if cfg.get('show_is_bot', 1) and member.bot:
            embed.add_field(name="🤖 Bot Account", value="Yes", inline=True)

        # Roles on rejoin
        if cfg.get('show_roles_on_rejoin', 1) and len(member.roles) > 1:
            role_list = ", ".join(r.mention for r in member.roles[1:][:10])
            embed.add_field(name="🎭 Existing Roles", value=role_list or "None", inline=False)

        # Invite used
        if cfg.get('show_invite_used', 1) and guild.me.guild_permissions.manage_guild:
            used_invite = await self._detect_invite(guild)
            if used_invite:
                creator_str = f"\nCreated by: {used_invite.inviter.mention}" if used_invite.inviter else ""
                embed.add_field(
                    name="🔗 Invite Used",
                    value=f"`discord.gg/{used_invite.code}` (uses: {used_invite.uses}){creator_str}",
                    inline=False
                )

        # Suspicious flags
        if is_suspicious and flags:
            embed.add_field(name="🚨 Suspicious Flags", value="\n".join(flags), inline=False)

        embed.set_footer(text=f"User ID: {member.id} • {BOT_NAME} Join Log")
        await channel.send(embed=embed)

        # Ping a role if suspicious
        if is_suspicious and cfg.get('suspicious_ping_role_id'):
            role = guild.get_role(cfg['suspicious_ping_role_id'])
            if role:
                try:
                    await channel.send(f"{role.mention} ⚠️ Suspicious join detected: {member.mention}", delete_after=30)
                except Exception:
                    pass

        # Welcome message
        if cfg.get('welcome_enabled', 0) and cfg.get('welcome_channel_id'):
            wch = guild.get_channel(cfg['welcome_channel_id'])
            if wch and wch.permissions_for(guild.me).send_messages:
                template = cfg.get('welcome_message') or DEFAULT_WELCOME
                msg = template.replace("{user}", str(member)) \
                              .replace("{mention}", member.mention) \
                              .replace("{server}", guild.name) \
                              .replace("{membercount}", str(guild.member_count))
                try:
                    await wch.send(msg)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        cfg = await self.bot.db.get_join_log_settings(guild.id)
        if not cfg.get('enabled', 1):
            return
        channel = await self._get_channel(guild)
        if not channel:
            return

        # Check if it was a kick or ban (check audit log)
        await asyncio.sleep(0.8)
        action_type = "leave"
        responsible = None
        reason_str = "No reason provided"

        if cfg.get('log_kicks', 1) or cfg.get('log_bans', 1):
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                    if entry.target.id == member.id and (time.time() - entry.created_at.timestamp()) < 5:
                        action_type = "kick"
                        responsible = entry.user
                        reason_str = entry.reason or "No reason provided"
                        break
            except Exception:
                pass

            if action_type == "leave":
                try:
                    async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                        if entry.target.id == member.id and (time.time() - entry.created_at.timestamp()) < 5:
                            action_type = "ban"
                            responsible = entry.user
                            reason_str = entry.reason or "No reason provided"
                            break
                except Exception:
                    pass

        if action_type == "kick" and not cfg.get('log_kicks', 1):
            return
        if action_type == "ban" and not cfg.get('log_bans', 1):
            return
        if action_type == "leave" and not cfg.get('log_leaves', 1):
            return

        if action_type == "kick":
            title = "👢 Member Kicked"
            color = 0xff8800
            emoji = "👢"
        elif action_type == "ban":
            title = "🔨 Member Banned"
            color = 0xff4444
            emoji = "🔨"
        else:
            title = "📤 Member Left"
            color = cfg.get('embed_color_leave', 16729344)
            emoji = "📤"

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        if cfg.get('show_avatar', 1):
            embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="👤 User", value=f"{member.mention}\n`{member}`\n`{member.id}`", inline=True)

        if cfg.get('show_account_age', 1):
            embed.add_field(
                name="🎂 Account Age",
                value=f"{_fmt_age(member.created_at)}\n<t:{int(member.created_at.timestamp())}:D>",
                inline=True
            )

        if responsible:
            embed.add_field(name=f"🛡️ {action_type.title()} By", value=f"{responsible.mention}\n`{responsible}`", inline=True)
            embed.add_field(name="📋 Reason", value=reason_str, inline=False)

        if len(member.roles) > 1:
            role_list = ", ".join(r.mention for r in member.roles[1:][:10])
            embed.add_field(name="🎭 Roles at Leave", value=role_list, inline=False)

        embed.set_footer(text=f"User ID: {member.id} • {BOT_NAME} Join Log")
        await channel.send(embed=embed)

    # ── Commands ──────────────────────────────────────────────────────────────

    joinlog = app_commands.Group(name="joinlog", description="📥 Configure the join/leave log system")

    @joinlog.command(name="setchannel", description="Set the channel for join/leave logs")
    @app_commands.describe(channel="The channel to send join/leave logs to")
    async def joinlog_setchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied", description="You need **Administrator** or be a bot admin.", color=0xff0000
            ), ephemeral=True)
            return

        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Missing Permissions", description=f"I can't send messages in {channel.mention}.", color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_join_log_channel(interaction.guild.id, channel.id)
        await self.bot.db.set_join_log_enabled(interaction.guild.id, True)
        await self._cache_invites(interaction.guild)

        embed = discord.Embed(
            title="📥 Join Log Channel Set",
            description=f"Join/leave events will now be logged in {channel.mention}.",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="📌 Channel", value=channel.mention, inline=True)
        embed.add_field(name="🔔 Status", value="✅ Enabled", inline=True)
        embed.set_footer(text=f"VO AntiNuke • {interaction.guild.name}")
        await interaction.response.send_message(embed=embed)

        test_embed = discord.Embed(
            title="✅ Join Log Activated",
            description=f"This channel will now receive join/leave logs.\nSet by {interaction.user.mention}.",
            color=0x57f287, timestamp=discord.utils.utcnow()
        )
        test_embed.set_footer(text=f"VO AntiNuke • Join Log")
        await channel.send(embed=test_embed)

    @joinlog.command(name="disable", description="Disable join/leave logging without wiping config")
    async def joinlog_disable(self, interaction: discord.Interaction):
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied", color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_join_log_enabled(interaction.guild.id, False)
        await interaction.response.send_message(embed=discord.Embed(
            title="❌ Join Log Disabled",
            description="Join/leave logging has been disabled. Use `/joinlog setchannel` to re-enable.",
            color=0xff4444, timestamp=discord.utils.utcnow()
        ), ephemeral=True)

    @joinlog.command(name="toggle", description="Toggle specific join log events on or off")
    @app_commands.describe(
        setting="Which setting to toggle",
        enabled="True to enable, False to disable"
    )
    @app_commands.choices(setting=[
        app_commands.Choice(name="Log joins", value="log_joins"),
        app_commands.Choice(name="Log leaves", value="log_leaves"),
        app_commands.Choice(name="Log kicks", value="log_kicks"),
        app_commands.Choice(name="Log bans (as leave reason)", value="log_bans"),
        app_commands.Choice(name="Show avatar", value="show_avatar"),
        app_commands.Choice(name="Show account age", value="show_account_age"),
        app_commands.Choice(name="Show join position", value="show_join_position"),
        app_commands.Choice(name="Show roles on rejoin", value="show_roles_on_rejoin"),
        app_commands.Choice(name="Show invite used", value="show_invite_used"),
        app_commands.Choice(name="Show if bot", value="show_is_bot"),
        app_commands.Choice(name="Warn new accounts", value="warn_new_accounts"),
        app_commands.Choice(name="Warn no avatar", value="warn_no_avatar"),
        app_commands.Choice(name="Welcome message", value="welcome_enabled"),
    ])
    async def joinlog_toggle(self, interaction: discord.Interaction, setting: str, enabled: bool):
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied", color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_join_log_setting(interaction.guild.id, setting, 1 if enabled else 0)
        pretty = setting.replace("_", " ").title()
        await interaction.response.send_message(embed=discord.Embed(
            title=f"✅ Setting Updated: {pretty}",
            description=f"**{pretty}** is now {'✅ enabled' if enabled else '❌ disabled'}.",
            color=0x57f287 if enabled else 0xff4444, timestamp=discord.utils.utcnow()
        ), ephemeral=True)

    @joinlog.command(name="threshold", description="Set how many days old an account must be to not be flagged suspicious")
    @app_commands.describe(days="Number of days (default: 7)")
    async def joinlog_threshold(self, interaction: discord.Interaction, days: int):
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied", color=0xff0000
            ), ephemeral=True)
            return

        if days < 0 or days > 365:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Invalid Value", description="Days must be between 0 and 365.", color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_join_log_setting(interaction.guild.id, 'new_account_threshold', days)
        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Account Age Threshold Set",
            description=f"Accounts younger than **{days} day(s)** will be flagged as suspicious.",
            color=0x57f287, timestamp=discord.utils.utcnow()
        ), ephemeral=True)

    @joinlog.command(name="susrole", description="Set a role to ping when a suspicious join is detected")
    @app_commands.describe(role="Role to ping (leave empty to clear)")
    async def joinlog_susrole(self, interaction: discord.Interaction, role: discord.Role = None):
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied", color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_join_log_setting(
            interaction.guild.id, 'suspicious_ping_role_id', role.id if role else None
        )
        desc = f"Suspicious joins will now ping {role.mention}." if role else "Suspicious join pings cleared."
        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Suspicious Join Role Updated",
            description=desc,
            color=0x57f287, timestamp=discord.utils.utcnow()
        ), ephemeral=True)

    @joinlog.command(name="welcome", description="Configure the welcome message")
    @app_commands.describe(
        channel="Channel to send welcome messages in",
        message="Welcome message template. Use {user}, {mention}, {server}, {membercount}"
    )
    async def joinlog_welcome(self, interaction: discord.Interaction, channel: discord.TextChannel = None, message: str = None):
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied", color=0xff0000
            ), ephemeral=True)
            return

        if channel:
            await self.bot.db.set_join_log_setting(interaction.guild.id, 'welcome_channel_id', channel.id)
        if message:
            await self.bot.db.set_join_log_setting(interaction.guild.id, 'welcome_message', message[:500])

        cfg = await self.bot.db.get_join_log_settings(interaction.guild.id)
        wch_id = cfg.get('welcome_channel_id')
        wch = interaction.guild.get_channel(wch_id) if wch_id else None
        preview = (cfg.get('welcome_message') or DEFAULT_WELCOME)

        embed = discord.Embed(
            title="🎉 Welcome Message Configured",
            color=0x57f287, timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="📌 Channel", value=wch.mention if wch else "*(not set)*", inline=True)
        embed.add_field(name="📝 Message Preview", value=preview[:300], inline=False)
        embed.add_field(
            name="💡 Placeholders",
            value="`{user}` = username\n`{mention}` = @mention\n`{server}` = server name\n`{membercount}` = member count",
            inline=False
        )
        embed.set_footer(text=f"Use `/joinlog toggle welcome_enabled True` to activate")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @joinlog.command(name="color", description="Set embed colors for join/leave/suspicious events")
    @app_commands.describe(
        event="Which event's color to change",
        hex_color="Hex color code without # (e.g. 57f287)"
    )
    @app_commands.choices(event=[
        app_commands.Choice(name="Join", value="embed_color_join"),
        app_commands.Choice(name="Leave", value="embed_color_leave"),
        app_commands.Choice(name="Suspicious", value="embed_color_suspicious"),
    ])
    async def joinlog_color(self, interaction: discord.Interaction, event: str, hex_color: str):
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied", color=0xff0000
            ), ephemeral=True)
            return

        try:
            color_int = int(hex_color.lstrip('#'), 16)
        except ValueError:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Invalid Color", description="Please provide a valid hex code like `ff4444` or `#57f287`.", color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_join_log_setting(interaction.guild.id, event, color_int)
        await interaction.response.send_message(embed=discord.Embed(
            title=f"✅ Color Updated: {event.replace('embed_color_', '').title()}",
            description=f"Color set to `#{hex_color.upper()}`",
            color=color_int, timestamp=discord.utils.utcnow()
        ), ephemeral=True)

    @joinlog.command(name="status", description="View the current join log configuration")
    async def joinlog_status(self, interaction: discord.Interaction):
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied", color=0xff0000
            ), ephemeral=True)
            return

        cfg = await self.bot.db.get_join_log_settings(interaction.guild.id)
        ch = interaction.guild.get_channel(cfg.get('channel_id', 0)) if cfg.get('channel_id') else None
        wch = interaction.guild.get_channel(cfg.get('welcome_channel_id', 0)) if cfg.get('welcome_channel_id') else None
        sus_role = interaction.guild.get_role(cfg.get('suspicious_ping_role_id', 0)) if cfg.get('suspicious_ping_role_id') else None

        def tog(key): return "✅" if cfg.get(key, 1) else "❌"

        embed = discord.Embed(
            title="📥 Join Log Configuration",
            color=0x5865f2, timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Status", value="✅ Enabled" if cfg.get('enabled', 1) else "❌ Disabled", inline=True)
        embed.add_field(name="Channel", value=ch.mention if ch else "*(not set)*", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="📡 Events", value=(
            f"{tog('log_joins')} Log Joins\n"
            f"{tog('log_leaves')} Log Leaves\n"
            f"{tog('log_kicks')} Log Kicks\n"
            f"{tog('log_bans')} Log Bans (in leave)"
        ), inline=True)
        embed.add_field(name="🔍 Display Options", value=(
            f"{tog('show_avatar')} Show Avatar\n"
            f"{tog('show_account_age')} Account Age\n"
            f"{tog('show_join_position')} Join Position\n"
            f"{tog('show_roles_on_rejoin')} Roles on Rejoin\n"
            f"{tog('show_invite_used')} Invite Used\n"
            f"{tog('show_is_bot')} Show Bot Flag"
        ), inline=True)
        embed.add_field(name="⚠️ Suspicious Detection", value=(
            f"{tog('warn_new_accounts')} New Account Warning\n"
            f"{tog('warn_no_avatar')} No Avatar Warning\n"
            f"📅 Threshold: **{cfg.get('new_account_threshold', 7)}** days\n"
            f"🔔 Ping Role: {sus_role.mention if sus_role else '*(none)*'}"
        ), inline=False)
        embed.add_field(name="🎉 Welcome Message", value=(
            f"Status: {'✅ Enabled' if cfg.get('welcome_enabled') else '❌ Disabled'}\n"
            f"Channel: {wch.mention if wch else '*(not set)*'}\n"
            f"Message: {(cfg.get('welcome_message') or DEFAULT_WELCOME)[:80]}..."
        ), inline=False)
        embed.set_footer(text=f"VO AntiNuke • Join Log")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(JoinLog(bot))
