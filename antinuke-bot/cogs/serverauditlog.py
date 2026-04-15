"""
serverauditlog.py — Mirrors Discord's native audit log to a dedicated audit log channel.
Completely separate from the moderation log. Fully configurable per-event.
"""
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import time

BOT_NAME = "VO AntiNuke"


async def _send_audit_log(bot, guild: discord.Guild, embed: discord.Embed, event_key: str):
    """Send to the dedicated audit log channel if enabled and event is toggled on."""
    cfg = await bot.db.get_audit_log_settings(guild.id)
    if not cfg.get('enabled', 1):
        return
    if not cfg.get(event_key, 1):
        return

    channel_id = cfg.get('channel_id')
    if not channel_id:
        return

    ch = guild.get_channel(channel_id)
    if ch and ch.permissions_for(guild.me).send_messages:
        try:
            await ch.send(embed=embed)
        except Exception:
            pass


class ServerAuditLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._processed: set[int] = set()

    def _is_bot(self, user) -> bool:
        return user is not None and user.id == self.bot.user.id

    async def _already_logged(self, entry_id: int, entry_ts: float = None) -> bool:
        # Reject entries older than 5 seconds (avoids re-logging on restart)
        if entry_ts is not None and (time.time() - entry_ts) > 5:
            return True
        if entry_id in self._processed:
            return True
        self._processed.add(entry_id)
        if len(self._processed) > 2000:
            self._processed = set(list(self._processed)[-1000:])
        return False

    # ── Ban ───────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await asyncio.sleep(0.8)
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target.id != user.id: continue
            if self._is_bot(entry.user): return
            if await self._already_logged(entry.id, entry.created_at.timestamp()): return

            embed = discord.Embed(
                title="🔨 Member Banned (External)",
                description=f"{user.mention} was banned outside the bot.",
                color=0xff4444, timestamp=entry.created_at
            )
            embed.add_field(name="👤 Banned User", value=f"{user} (`{user.id}`)", inline=True)
            embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=entry.reason or "No reason provided", inline=False)
            if hasattr(user, 'display_avatar') and user.display_avatar:
                embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=f"User ID: {user.id} • {BOT_NAME} Audit Log")
            await _send_audit_log(self.bot, guild, embed, 'log_bans')
            break

    # ── Unban ────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        await asyncio.sleep(0.8)
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
            if entry.target.id != user.id: continue
            if self._is_bot(entry.user): return
            if await self._already_logged(entry.id, entry.created_at.timestamp()): return

            embed = discord.Embed(
                title="🔓 Member Unbanned (External)",
                description=f"{user.mention} was unbanned outside the bot.",
                color=0x57f287, timestamp=entry.created_at
            )
            embed.add_field(name="👤 User", value=f"{user} (`{user.id}`)", inline=True)
            embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=entry.reason or "No reason provided", inline=False)
            embed.set_footer(text=f"User ID: {user.id} • {BOT_NAME} Audit Log")
            await _send_audit_log(self.bot, guild, embed, 'log_unbans')
            break

    # ── Kick ─────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await asyncio.sleep(0.8)
        guild = member.guild
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target.id != member.id: continue
            if self._is_bot(entry.user): return
            if (time.time() - entry.created_at.timestamp()) > 5: continue  # timestamp delta check
            if await self._already_logged(entry.id, entry.created_at.timestamp()): return

            embed = discord.Embed(
                title="👢 Member Kicked (External)",
                description=f"{member.mention} was kicked outside the bot.",
                color=0xffa500, timestamp=entry.created_at
            )
            embed.add_field(name="👤 User", value=f"{member} (`{member.id}`)", inline=True)
            embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=entry.reason or "No reason provided", inline=False)
            if member.display_avatar:
                embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id} • {BOT_NAME} Audit Log")
            await _send_audit_log(self.bot, guild, embed, 'log_kicks')
            break

    # ── Timeout ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild

        # ── Timeout applied/removed ──────────────────────────────────────────
        if before.timed_out_until != after.timed_out_until:
            await asyncio.sleep(0.8)
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_update):
                if entry.target.id != after.id: continue
                if self._is_bot(entry.user): return
                if await self._already_logged(entry.id, entry.created_at.timestamp()): return

                if after.timed_out_until is not None:
                    embed = discord.Embed(title="🔇 Member Timed Out (External)", color=0xff8800, timestamp=entry.created_at)
                    embed.add_field(name="👤 User", value=f"{after} (`{after.id}`)", inline=True)
                    embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
                    embed.add_field(name="⏰ Expires", value=f"<t:{int(after.timed_out_until.timestamp())}:R>", inline=True)
                else:
                    embed = discord.Embed(title="🔊 Timeout Removed (External)", color=0x57f287, timestamp=entry.created_at)
                    embed.add_field(name="👤 User", value=f"{after} (`{after.id}`)", inline=True)
                    embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)

                embed.add_field(name="📋 Reason", value=entry.reason or "No reason provided", inline=False)
                if after.display_avatar:
                    embed.set_thumbnail(url=after.display_avatar.url)
                embed.set_footer(text=f"User ID: {after.id} • {BOT_NAME} Audit Log")
                await _send_audit_log(self.bot, guild, embed, 'log_timeouts')
                break

        # ── Role granted/revoked ──────────────────────────────────────────────
        if before.roles != after.roles:
            added = [r for r in after.roles if r not in before.roles]
            removed = [r for r in before.roles if r not in after.roles]
            if not added and not removed:
                return
            await asyncio.sleep(0.5)
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_role_update):
                if entry.target.id != after.id: continue
                if self._is_bot(entry.user): return
                if await self._already_logged(entry.id, entry.created_at.timestamp()): return

                embed = discord.Embed(title="🎭 Member Roles Updated (External)", color=0x5865f2, timestamp=entry.created_at)
                embed.add_field(name="👤 User", value=f"{after} (`{after.id}`)", inline=True)
                embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
                if added:
                    embed.add_field(name="➕ Roles Added", value=", ".join(r.mention for r in added), inline=False)
                if removed:
                    embed.add_field(name="➖ Roles Removed", value=", ".join(r.mention for r in removed), inline=False)
                embed.set_footer(text=f"User ID: {after.id} • {BOT_NAME} Audit Log")
                await _send_audit_log(self.bot, guild, embed, 'log_member_roles')
                break

    # ── Role permission changes ───────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if before.permissions == after.permissions and before.name == after.name:
            return
        await asyncio.sleep(0.8)
        async for entry in after.guild.audit_logs(limit=5, action=discord.AuditLogAction.role_update):
            if entry.target.id != after.id: continue
            if self._is_bot(entry.user): return
            if await self._already_logged(entry.id, entry.created_at.timestamp()): return

            embed = discord.Embed(title="⚙️ Role Updated (External)", color=0x5865f2, timestamp=entry.created_at)
            embed.add_field(name="🎭 Role", value=f"{after.mention} (`{after.id}`)", inline=True)
            embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
            if before.name != after.name:
                embed.add_field(name="📛 Name", value=f"`{before.name}` → `{after.name}`", inline=False)
            if before.permissions != after.permissions:
                embed.add_field(name="🔒 Permissions Changed", value="Yes (permissions were modified)", inline=False)
            embed.add_field(name="📋 Reason", value=entry.reason or "No reason provided", inline=False)
            embed.set_footer(text=f"Role ID: {after.id} • {BOT_NAME} Audit Log")
            await _send_audit_log(self.bot, after.guild, embed, 'log_role_perms')
            break

    # ── Role created/deleted ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await asyncio.sleep(0.8)
        async for entry in role.guild.audit_logs(limit=5, action=discord.AuditLogAction.role_create):
            if entry.target.id != role.id: continue
            if self._is_bot(entry.user): return
            if await self._already_logged(entry.id, entry.created_at.timestamp()): return

            embed = discord.Embed(title="✨ Role Created (External)", color=0x57f287, timestamp=entry.created_at)
            embed.add_field(name="🎭 Role", value=f"{role.mention} (`{role.id}`)", inline=True)
            embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=entry.reason or "No reason provided", inline=False)
            embed.set_footer(text=f"Role ID: {role.id} • {BOT_NAME} Audit Log")
            await _send_audit_log(self.bot, role.guild, embed, 'log_role_create')
            break

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await asyncio.sleep(0.8)
        async for entry in role.guild.audit_logs(limit=5, action=discord.AuditLogAction.role_delete):
            if entry.target.id != role.id: continue
            if self._is_bot(entry.user): return
            if await self._already_logged(entry.id, entry.created_at.timestamp()): return

            embed = discord.Embed(title="🗑️ Role Deleted (External)", color=0xff4444, timestamp=entry.created_at)
            embed.add_field(name="🎭 Role Name", value=f"`{role.name}` (`{role.id}`)", inline=True)
            embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=entry.reason or "No reason provided", inline=False)
            embed.set_footer(text=f"Role ID: {role.id} • {BOT_NAME} Audit Log")
            await _send_audit_log(self.bot, role.guild, embed, 'log_role_delete')
            break

    # ── Channel created/deleted/updated ───────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await asyncio.sleep(0.8)
        async for entry in channel.guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_create):
            if entry.target.id != channel.id: continue
            if self._is_bot(entry.user): return
            if await self._already_logged(entry.id, entry.created_at.timestamp()): return

            embed = discord.Embed(title="📌 Channel Created (External)", color=0x57f287, timestamp=entry.created_at)
            embed.add_field(name="📌 Channel", value=f"{channel.mention} (`{channel.id}`)", inline=True)
            embed.add_field(name="📂 Type", value=str(channel.type).replace('_', ' ').title(), inline=True)
            embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=entry.reason or "No reason provided", inline=False)
            embed.set_footer(text=f"Channel ID: {channel.id} • {BOT_NAME} Audit Log")
            await _send_audit_log(self.bot, channel.guild, embed, 'log_channel_create')
            break

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await asyncio.sleep(0.8)
        async for entry in channel.guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_delete):
            if entry.target.id != channel.id: continue
            if self._is_bot(entry.user): return
            if await self._already_logged(entry.id, entry.created_at.timestamp()): return

            embed = discord.Embed(title="🗑️ Channel Deleted (External)", color=0xff4444, timestamp=entry.created_at)
            embed.add_field(name="🗑️ Channel", value=f"#{channel.name} (`{channel.id}`)", inline=True)
            embed.add_field(name="📂 Type", value=str(channel.type).replace('_', ' ').title(), inline=True)
            embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=entry.reason or "No reason provided", inline=False)
            embed.set_footer(text=f"Channel ID: {channel.id} • {BOT_NAME} Audit Log")
            await _send_audit_log(self.bot, channel.guild, embed, 'log_channel_delete')
            break

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        if before.name == after.name and getattr(before, 'topic', None) == getattr(after, 'topic', None):
            return
        await asyncio.sleep(0.8)
        async for entry in after.guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_update):
            if entry.target.id != after.id: continue
            if self._is_bot(entry.user): return
            if await self._already_logged(entry.id, entry.created_at.timestamp()): return

            embed = discord.Embed(title="✏️ Channel Updated (External)", color=0xffaa00, timestamp=entry.created_at)
            embed.add_field(name="📌 Channel", value=f"{after.mention} (`{after.id}`)", inline=True)
            embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
            if before.name != after.name:
                embed.add_field(name="📛 Name", value=f"`{before.name}` → `{after.name}`", inline=False)
            if hasattr(before, 'topic') and before.topic != after.topic:
                embed.add_field(name="📝 Topic", value=f"**Before:** {before.topic or '*(none)*'}\n**After:** {after.topic or '*(none)*'}", inline=False)
            embed.add_field(name="📋 Reason", value=entry.reason or "No reason provided", inline=False)
            embed.set_footer(text=f"Channel ID: {after.id} • {BOT_NAME} Audit Log")
            await _send_audit_log(self.bot, after.guild, embed, 'log_channel_update')
            break

    # ── Server update ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        if before.name == after.name and before.vanity_url_code == after.vanity_url_code:
            return
        await asyncio.sleep(0.8)
        async for entry in after.audit_logs(limit=5, action=discord.AuditLogAction.guild_update):
            if self._is_bot(entry.user): return
            if await self._already_logged(entry.id, entry.created_at.timestamp()): return

            embed = discord.Embed(title="⚙️ Server Updated (External)", color=0x5865f2, timestamp=entry.created_at)
            if before.name != after.name:
                embed.add_field(name="📛 Name", value=f"`{before.name}` → `{after.name}`", inline=False)
            if before.vanity_url_code != after.vanity_url_code:
                embed.add_field(
                    name="🔗 Vanity URL",
                    value=f"`{before.vanity_url_code or 'None'}` → `{after.vanity_url_code or 'None'}`",
                    inline=False
                )
            embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=entry.reason or "No reason provided", inline=False)
            embed.set_footer(text=f"{BOT_NAME} Audit Log")
            await _send_audit_log(self.bot, after, embed, 'log_server_update')
            break

    # ── Webhook created/deleted ───────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        await asyncio.sleep(0.8)
        guild = channel.guild
        for action, title, color in [
            (discord.AuditLogAction.webhook_create, "🪝 Webhook Created (External)", 0xffaa00),
            (discord.AuditLogAction.webhook_delete, "🗑️ Webhook Deleted (External)", 0xff4444),
        ]:
            async for entry in guild.audit_logs(limit=3, action=action):
                if self._is_bot(entry.user): continue
                if (time.time() - entry.created_at.timestamp()) > 10: continue
                if await self._already_logged(entry.id, entry.created_at.timestamp()): continue

                embed = discord.Embed(title=title, color=color, timestamp=entry.created_at)
                embed.add_field(name="📌 Channel", value=channel.mention, inline=True)
                embed.add_field(name="🛡️ Responsible", value=entry.user.mention if entry.user else "Unknown", inline=True)
                if hasattr(entry.target, 'name') and entry.target:
                    embed.add_field(name="🪝 Webhook Name", value=str(entry.target.name) if hasattr(entry.target, 'name') else "Unknown", inline=True)
                embed.set_footer(text=f"{BOT_NAME} Audit Log — ⚠️ Security Event")
                await _send_audit_log(self.bot, guild, embed, 'log_webhooks')

    # ── Invite created/deleted ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        embed = discord.Embed(title="🔗 Invite Created", color=0x57f287, timestamp=discord.utils.utcnow())
        embed.add_field(name="🔗 Code", value=f"`discord.gg/{invite.code}`", inline=True)
        embed.add_field(name="👤 Created By", value=invite.inviter.mention if invite.inviter else "Unknown", inline=True)
        embed.add_field(name="📌 Channel", value=invite.channel.mention if invite.channel else "Unknown", inline=True)
        max_uses = invite.max_uses or "∞"
        embed.add_field(name="🔢 Max Uses", value=str(max_uses), inline=True)
        if invite.max_age:
            embed.add_field(name="⏰ Expires", value=f"<t:{int(discord.utils.utcnow().timestamp()) + invite.max_age}:R>", inline=True)
        embed.set_footer(text=f"{BOT_NAME} Audit Log")
        await _send_audit_log(self.bot, invite.guild, embed, 'log_invites')

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        embed = discord.Embed(title="🗑️ Invite Deleted", color=0xff4444, timestamp=discord.utils.utcnow())
        embed.add_field(name="🔗 Code", value=f"`discord.gg/{invite.code}`", inline=True)
        embed.add_field(name="📌 Channel", value=invite.channel.mention if invite.channel else "Unknown", inline=True)
        embed.set_footer(text=f"{BOT_NAME} Audit Log")
        await _send_audit_log(self.bot, invite.guild, embed, 'log_invites')

    # ── Emoji/sticker changes ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before, after):
        added = [e for e in after if e not in before]
        removed = [e for e in before if e not in after]
        if not added and not removed: return

        embed = discord.Embed(title="😀 Emoji Updated (External)", color=0x5865f2, timestamp=discord.utils.utcnow())
        if added:
            embed.add_field(name="➕ Added", value=" ".join(str(e) for e in added[:10]), inline=False)
        if removed:
            embed.add_field(name="➖ Removed", value=", ".join(f"`:{e.name}:`" for e in removed[:10]), inline=False)
        embed.set_footer(text=f"{BOT_NAME} Audit Log")
        await _send_audit_log(self.bot, guild, embed, 'log_emoji')

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild: discord.Guild, before, after):
        added = [s for s in after if s not in before]
        removed = [s for s in before if s not in after]
        if not added and not removed: return

        embed = discord.Embed(title="🩹 Sticker Updated (External)", color=0x5865f2, timestamp=discord.utils.utcnow())
        if added:
            embed.add_field(name="➕ Added", value=", ".join(f"`{s.name}`" for s in added[:10]), inline=False)
        if removed:
            embed.add_field(name="➖ Removed", value=", ".join(f"`{s.name}`" for s in removed[:10]), inline=False)
        embed.set_footer(text=f"{BOT_NAME} Audit Log")
        await _send_audit_log(self.bot, guild, embed, 'log_stickers')

    # ── /auditlog commands ────────────────────────────────────────────────────

    auditlog = app_commands.Group(name="auditlog", description="📋 Configure the server audit log system")

    @auditlog.command(name="setchannel", description="Set the dedicated audit log channel (separate from mod log)")
    @app_commands.describe(channel="The channel to send audit logs to")
    async def auditlog_setchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer()
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied", description="You need **Administrator** or be a bot admin.", color=0xff0000
            ), ephemeral=True)
            return

        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Missing Permissions", description=f"I can't send messages in {channel.mention}.", color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_audit_log_channel_id(interaction.guild.id, channel.id)
        await self.bot.db.set_audit_log_enabled(interaction.guild.id, True)

        embed = discord.Embed(
            title="📋 Audit Log Channel Set",
            description=f"External audit events will now be logged in {channel.mention}.\nThis is **separate** from the moderation log.",
            color=0x5865f2, timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="📌 Channel", value=channel.mention, inline=True)
        embed.add_field(name="🔔 Status", value="✅ Enabled", inline=True)
        embed.add_field(name="📋 What Gets Logged", value=(
            "• External bans, unbans, kicks, timeouts\n"
            "• Role create/delete/permission changes\n"
            "• Member role assignments/removals\n"
            "• Channel create/delete/updates\n"
            "• Server name/vanity URL changes\n"
            "• Webhook create/delete\n"
            "• Invite create/delete\n"
            "• Emoji & sticker changes"
        ), inline=False)
        embed.set_footer(text=f"VO AntiNuke • Audit Log")
        await interaction.followup.send(embed=embed)

        test_embed = discord.Embed(
            title="✅ Audit Log Activated",
            description=f"This channel will now receive server audit log events.\nSet by {interaction.user.mention}.",
            color=0x57f287, timestamp=discord.utils.utcnow()
        )
        test_embed.set_footer(text=f"VO AntiNuke • Audit Log")
        await channel.send(embed=test_embed)

    @auditlog.command(name="disable", description="Disable the audit log without wiping config")
    async def auditlog_disable(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied", color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_audit_log_enabled(interaction.guild.id, False)
        await interaction.followup.send(embed=discord.Embed(
            title="❌ Audit Log Disabled",
            description="Audit logging has been disabled. Use `/auditlog setchannel` to re-enable.",
            color=0xff4444, timestamp=discord.utils.utcnow()
        ), ephemeral=True)

    @auditlog.command(name="toggle", description="Toggle a specific audit log event on or off")
    @app_commands.describe(event="Which event type to toggle", enabled="Enable or disable")
    @app_commands.choices(event=[
        app_commands.Choice(name="External Bans", value="log_bans"),
        app_commands.Choice(name="External Unbans", value="log_unbans"),
        app_commands.Choice(name="External Kicks", value="log_kicks"),
        app_commands.Choice(name="External Timeouts", value="log_timeouts"),
        app_commands.Choice(name="Role Permission Changes", value="log_role_perms"),
        app_commands.Choice(name="Role Created", value="log_role_create"),
        app_commands.Choice(name="Role Deleted", value="log_role_delete"),
        app_commands.Choice(name="Member Role Updates", value="log_member_roles"),
        app_commands.Choice(name="Channel Created", value="log_channel_create"),
        app_commands.Choice(name="Channel Deleted", value="log_channel_delete"),
        app_commands.Choice(name="Channel Updated", value="log_channel_update"),
        app_commands.Choice(name="Server Updated", value="log_server_update"),
        app_commands.Choice(name="Webhooks", value="log_webhooks"),
        app_commands.Choice(name="Invites", value="log_invites"),
        app_commands.Choice(name="Emoji Changes", value="log_emoji"),
        app_commands.Choice(name="Sticker Changes", value="log_stickers"),
    ])
    async def auditlog_toggle(self, interaction: discord.Interaction, event: str, enabled: bool):
        await interaction.response.defer()
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied", color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_audit_log_event(interaction.guild.id, event, enabled)
        pretty = event.replace("log_", "").replace("_", " ").title()
        await interaction.followup.send(embed=discord.Embed(
            title=f"✅ Audit Event Updated: {pretty}",
            description=f"**{pretty}** logging is now {'✅ enabled' if enabled else '❌ disabled'}.",
            color=0x57f287 if enabled else 0xff4444, timestamp=discord.utils.utcnow()
        ), ephemeral=True)

    @auditlog.command(name="status", description="View current audit log configuration")
    async def auditlog_status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.id == interaction.guild.owner_id or
                await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied", color=0xff0000
            ), ephemeral=True)
            return

        cfg = await self.bot.db.get_audit_log_settings(interaction.guild.id)
        ch = interaction.guild.get_channel(cfg.get('channel_id', 0)) if cfg.get('channel_id') else None

        def tog(key): return "✅" if cfg.get(key, 1) else "❌"

        embed = discord.Embed(title="📋 Audit Log Configuration", color=0x5865f2, timestamp=discord.utils.utcnow())
        embed.add_field(name="Status", value="✅ Enabled" if cfg.get('enabled', 1) else "❌ Disabled", inline=True)
        embed.add_field(name="Channel", value=ch.mention if ch else "*(not set)*", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="👮 Member Actions", value=(
            f"{tog('log_bans')} Bans\n"
            f"{tog('log_unbans')} Unbans\n"
            f"{tog('log_kicks')} Kicks\n"
            f"{tog('log_timeouts')} Timeouts\n"
            f"{tog('log_member_roles')} Role Updates"
        ), inline=True)
        embed.add_field(name="🎭 Roles", value=(
            f"{tog('log_role_perms')} Permission Changes\n"
            f"{tog('log_role_create')} Role Created\n"
            f"{tog('log_role_delete')} Role Deleted"
        ), inline=True)
        embed.add_field(name="📌 Channels & Server", value=(
            f"{tog('log_channel_create')} Channel Created\n"
            f"{tog('log_channel_delete')} Channel Deleted\n"
            f"{tog('log_channel_update')} Channel Updated\n"
            f"{tog('log_server_update')} Server Updated"
        ), inline=True)
        embed.add_field(name="🔗 Other", value=(
            f"{tog('log_webhooks')} Webhooks ⚠️\n"
            f"{tog('log_invites')} Invites\n"
            f"{tog('log_emoji')} Emoji\n"
            f"{tog('log_stickers')} Stickers"
        ), inline=True)
        embed.set_footer(text=f"VO AntiNuke • Audit Log | ⚠️ = Security-critical")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ServerAuditLog(bot))
