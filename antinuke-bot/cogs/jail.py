import discord
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks
import json
import time
import asyncio
from utils.helpers import parse_time, format_time


JAIL_ROLE_NAME = "Jailed"
JAIL_ROLE_COLOR = discord.Color.from_rgb(128, 0, 0)


class Jail(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.expiry_checker.start()

    def cog_unload(self):
        self.expiry_checker.cancel()

    # ─── Background task: auto-unjail when time expires ──────────

    @tasks.loop(seconds=30)
    async def expiry_checker(self):
        try:
            expired = await self.bot.jail_db.get_expired_jails(int(time.time()))
            for guild_id, user_id in expired:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    await self.bot.jail_db.unjail_user(guild_id, user_id)
                    continue

                member = guild.get_member(user_id)
                jail_data = await self.bot.jail_db.get_jailed_user(guild_id, user_id)

                if jail_data:
                    _, reason, prev_roles_json, _, _ = jail_data
                    await self._do_unjail(guild, member, user_id, prev_roles_json, auto=True)

                await self.bot.jail_db.unjail_user(guild_id, user_id)
                await self.bot.db.remove_role_persistence(guild_id, user_id, 'jail')
        except Exception as e:
            print(f"[Jail expiry checker error]: {e}")

    @expiry_checker.before_loop
    async def before_expiry_checker(self):
        await self.bot.wait_until_ready()

    # ─── Helpers ──────────────────────────────────────────────────

    async def get_or_create_jail_role(self, guild: discord.Guild) -> discord.Role:
        """Returns the jail role, creating it if it doesn't exist."""
        config = await self.bot.jail_db.get_jail_config(guild.id)

        if config and config[0]:
            role = guild.get_role(config[0])
            if role:
                return role

        # Check by name fallback
        existing = discord.utils.get(guild.roles, name=JAIL_ROLE_NAME)
        if existing:
            await self.bot.jail_db.update_jail_role(guild.id, existing.id)
            return existing

        # Create the role
        role = await guild.create_role(
            name=JAIL_ROLE_NAME,
            color=JAIL_ROLE_COLOR,
            reason="VO AntiNuke: Jail role auto-created",
            permissions=discord.Permissions.none()
        )
        await self.bot.jail_db.update_jail_role(guild.id, role.id)

        # Deny send/view in all channels except the jail channel
        await self._apply_jail_role_to_all_channels(guild, role)

        return role

    async def _apply_jail_role_to_all_channels(self, guild: discord.Guild, jail_role: discord.Role):
        """Deny the jail role from viewing/sending in all non-jail channels."""
        config = await self.bot.jail_db.get_jail_config(guild.id)
        jail_channel_id = config[1] if config else None

        for channel in guild.channels:
            if channel.id == jail_channel_id:
                continue
            try:
                await channel.set_permissions(
                    jail_role,
                    view_channel=False,
                    send_messages=False,
                    reason="VO AntiNuke: Jail role lockout"
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
            await asyncio.sleep(0.3)  # rate limit safety

    async def _do_unjail(
        self,
        guild: discord.Guild,
        member: discord.Member | None,
        user_id: int,
        prev_roles_json: str,
        auto: bool = False
    ):
        """Core unjail logic — restores roles, removes jail role."""
        config = await self.bot.jail_db.get_jail_config(guild.id)
        jail_role = None
        if config and config[0]:
            jail_role = guild.get_role(config[0])

        if not member:
            return  # User left — roles can't be restored

        bot_member = guild.get_member(self.bot.user.id)

        # Restore previous roles
        prev_role_ids = json.loads(prev_roles_json)
        roles_to_add = []
        for role_id in prev_role_ids:
            role = guild.get_role(role_id)
            if role and role != guild.default_role and role < bot_member.top_role:
                roles_to_add.append(role)

        # Remove jail role first
        if jail_role and jail_role in member.roles:
            try:
                await member.remove_roles(jail_role, reason="VO AntiNuke: Unjailed")
            except Exception:
                pass

        # Restore roles
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="VO AntiNuke: Restoring roles after unjail")
            except Exception as e:
                print(f"Failed to restore roles for {member}: {e}")

        # Log auto-unjail
        if auto:
            log_channel_id = await self.bot.db.get_log_channel(guild.id)
            if log_channel_id:
                log_ch = guild.get_channel(log_channel_id)
                if log_ch:
                    embed = discord.Embed(
                        title="🔓 Member Auto-Unjailed",
                        description=f"{member.mention} has been automatically unjailed (jail time expired).",
                        color=0x57f287,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="User", value=f"{member} (`{member.id}`)", inline=True)
                    embed.add_field(name="Roles Restored", value=str(len(roles_to_add)), inline=True)
                    embed.set_footer(text="VO AntiNuke • Jail System")
                    await log_ch.send(embed=embed)

    # ─── Commands ─────────────────────────────────────────────────

    @app_commands.command(name="setjailchannel", description="⚙️ Set up the jail channel (auto-creates role + locks all channels)")
    @app_commands.describe(channel="The channel jailed users will be restricted to")
    async def setjailchannel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await interaction.response.defer()
        is_bot_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not (interaction.user.guild_permissions.administrator or interaction.user.id == interaction.guild.owner_id or is_bot_admin):
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Access Denied", description="You need **Administrator** permission, be the server owner, or be an authorized bot admin.", color=0xff0000),
                ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        guild = interaction.guild

        # Create or find the channel
        if channel is None:
            # Auto-create the jail channel
            jail_category = None
            # Try to find or create a "Moderation" category
            for cat in guild.categories:
                if "mod" in cat.name.lower() or "admin" in cat.name.lower():
                    jail_category = cat
                    break

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
            }
            channel = await guild.create_text_channel(
                name="🔒・jail",
                category=jail_category,
                overwrites=overwrites,
                topic="You have been jailed. A moderator will attend to you shortly.",
                reason="VO AntiNuke: Jail channel setup"
            )

        # Ensure jail role exists
        jail_role = await self.get_or_create_jail_role(guild)

        # Save jail channel
        await self.bot.jail_db.update_jail_channel(guild.id, channel.id)

        # Allow jail role to see the jail channel
        try:
            await channel.set_permissions(
                jail_role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                reason="VO AntiNuke: Jail channel access for Jailed role"
            )
        except Exception:
            pass

        # Lock jail role out of all other channels
        locked = 0
        for ch in guild.channels:
            if ch.id == channel.id:
                continue
            try:
                await ch.set_permissions(
                    jail_role,
                    view_channel=False,
                    send_messages=False,
                    reason="VO AntiNuke: Jail role lockout"
                )
                locked += 1
            except (discord.Forbidden, discord.HTTPException):
                pass
            await asyncio.sleep(0.3)

        embed = discord.Embed(
            title="⚙️ Jail System Configured",
            description="The jail system has been fully set up and is ready to use.",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="🔒 Jail Channel", value=channel.mention, inline=True)
        embed.add_field(name="🏷️ Jail Role", value=jail_role.mention, inline=True)
        embed.add_field(name="🔐 Channels Locked", value=f"{locked} channel(s)", inline=True)
        embed.add_field(
            name="ℹ️ How It Works",
            value=(
                f"When a user is jailed with `/jail`, they will:\n"
                f"• Have all roles removed and replaced with {jail_role.mention}\n"
                f"• Only be able to see {channel.mention}\n"
                f"• Have their old roles restored when unjailed"
            ),
            inline=False
        )
        embed.set_footer(text="VO AntiNuke • Jail System", icon_url=guild.me.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="jail", description="🔒 Jail a member (removes all roles, restricts to jail channel)")
    @app_commands.describe(
        user="The member to jail",
        reason="Reason for jailing",
        duration="Duration (e.g. 1h, 30m, 1d) — leave empty for permanent"
    )
    async def jail(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "No reason provided",
        duration: str = None
    ):
        await interaction.response.defer()
        is_bot_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not (interaction.user.guild_permissions.manage_roles or interaction.user.id == interaction.guild.owner_id or is_bot_admin):
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Access Denied", description="You need **Manage Roles** permission, be the server owner, or be an authorized bot admin.", color=0xff0000),
                ephemeral=True
            )
            return

        if user.id == interaction.user.id:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ You cannot jail yourself.", color=0xff0000), ephemeral=True
            )
            return

        if user.id == interaction.guild.owner_id:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ You cannot jail the server owner.", color=0xff0000), ephemeral=True
            )
            return

        if user.bot:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ You cannot jail bots.", color=0xff0000), ephemeral=True
            )
            return

        bot_member = interaction.guild.get_member(self.bot.user.id)
        if user.top_role >= bot_member.top_role:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ I cannot jail this user — their role is higher than mine.", color=0xff0000),
                ephemeral=True
            )
            return

        if await self.bot.jail_db.is_jailed(interaction.guild.id, user.id):
            await interaction.followup.send(
                embed=discord.Embed(description=f"⚠️ {user.mention} is already jailed.", color=0xffcc00),
                ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        # Parse duration
        expires_at = None
        duration_str = "Permanent"
        if duration:
            seconds = parse_time(duration)
            if seconds is None:
                await interaction.followup.send(
                    embed=discord.Embed(description="❌ Invalid duration format. Use `1h`, `30m`, `1d`, etc.", color=0xff0000),
                    ephemeral=True
                )
                return
            expires_at = int(time.time()) + seconds
            duration_str = format_time(seconds)

        # Get or create jail role
        jail_role = await self.get_or_create_jail_role(interaction.guild)

        # Save current roles (excluding @everyone and the jail role itself)
        prev_roles = [
            r.id for r in user.roles
            if r != interaction.guild.default_role and r != jail_role and r < bot_member.top_role
        ]

        # Remove all roles and add jail role
        roles_to_remove = [r for r in user.roles if r != interaction.guild.default_role and r < bot_member.top_role]
        try:
            if roles_to_remove:
                await user.remove_roles(*roles_to_remove, reason=f"VO AntiNuke: Jailing — {reason}")
            await user.add_roles(jail_role, reason=f"VO AntiNuke: Jailing — {reason}")
        except discord.Forbidden:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ I don't have permission to manage this user's roles.", color=0xff0000),
                ephemeral=True
            )
            return

        # Save to DB
        await self.bot.jail_db.jail_user(
            interaction.guild.id, user.id, interaction.user.id,
            reason, prev_roles, expires_at
        )

        # Register role persistence so the jail survives a rejoin
        jail_role = await self.get_or_create_jail_role(interaction.guild)
        await self.bot.db.set_role_persistence(
            interaction.guild.id, user.id,
            'jail', jail_role.id,
            {'expires_at': expires_at} if expires_at else {}
        )

        # DM the jailed user
        config = await self.bot.jail_db.get_jail_config(interaction.guild.id)
        jail_channel = interaction.guild.get_channel(config[1]) if config and config[1] else None

        try:
            dm_embed = discord.Embed(
                title=f"🔒 You Have Been Jailed",
                description=f"You have been jailed in **{interaction.guild.name}**.",
                color=0xff6600,
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="📋 Reason", value=reason, inline=False)
            dm_embed.add_field(name="🛡️ Jailed By", value=str(interaction.user), inline=True)
            dm_embed.add_field(name="⏰ Duration", value=duration_str, inline=True)
            if expires_at:
                dm_embed.add_field(name="🔓 Expires", value=f"<t:{expires_at}:F>", inline=True)
            dm_embed.set_footer(text=f"{interaction.guild.name} • VO AntiNuke")
            await user.send(embed=dm_embed)
        except Exception:
            pass

        # Response embed
        embed = discord.Embed(
            title="🔒 Member Jailed",
            color=0xff6600,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 Jailed User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.add_field(name="⏰ Duration", value=duration_str, inline=True)
        if expires_at:
            embed.add_field(name="🔓 Expires", value=f"<t:{expires_at}:R>", inline=True)
        embed.add_field(name="💾 Roles Saved", value=f"{len(prev_roles)} role(s) stored", inline=True)
        if jail_channel:
            embed.add_field(name="🔒 Jail Channel", value=jail_channel.mention, inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="VO AntiNuke • Jail System", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.followup.send(embed=embed)

        # Log
        log_channel_id = await self.bot.db.get_log_channel(interaction.guild.id)
        if log_channel_id:
            log_ch = interaction.guild.get_channel(log_channel_id)
            if log_ch:
                log_embed = discord.Embed(title="🔒 Moderation Action — Jail", color=0xff6600, timestamp=discord.utils.utcnow())
                log_embed.add_field(name="Jailed User", value=f"{user} (`{user.id}`)", inline=True)
                log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
                log_embed.add_field(name="Reason", value=reason, inline=False)
                log_embed.add_field(name="Duration", value=duration_str, inline=True)
                if expires_at:
                    log_embed.add_field(name="Expires", value=f"<t:{expires_at}:F>", inline=True)
                log_embed.set_footer(text=f"User ID: {user.id}")
                await log_ch.send(embed=log_embed)

    @app_commands.command(name="unjail", description="🔓 Unjail a member and restore their previous roles")
    @app_commands.describe(user="The member to unjail", reason="Reason for unjailing")
    async def unjail(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        await interaction.response.defer()
        is_bot_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not (interaction.user.guild_permissions.manage_roles or interaction.user.id == interaction.guild.owner_id or is_bot_admin):
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Access Denied", description="You need **Manage Roles** permission, be the server owner, or be an authorized bot admin.", color=0xff0000),
                ephemeral=True
            )
            return

        jail_data = await self.bot.jail_db.get_jailed_user(interaction.guild.id, user.id)
        if not jail_data:
            await interaction.followup.send(
                embed=discord.Embed(description=f"⚠️ {user.mention} is not currently jailed.", color=0xffcc00),
                ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        mod_id, original_reason, prev_roles_json, jailed_at, expires_at = jail_data

        await self._do_unjail(interaction.guild, user, user.id, prev_roles_json)
        await self.bot.jail_db.unjail_user(interaction.guild.id, user.id)
        # Clear role persistence record
        await self.bot.db.remove_role_persistence(interaction.guild.id, user.id, 'jail')

        prev_role_ids = json.loads(prev_roles_json)
        restored_count = len(prev_role_ids)

        # DM the unjailed user
        try:
            dm_embed = discord.Embed(
                title="🔓 You Have Been Unjailed",
                description=f"Your jail in **{interaction.guild.name}** has been lifted.",
                color=0x57f287,
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="🛡️ Unjailed By", value=str(interaction.user), inline=True)
            dm_embed.add_field(name="📋 Reason", value=reason, inline=True)
            dm_embed.add_field(name="💼 Roles Restored", value=f"{restored_count} role(s)", inline=True)
            await user.send(embed=dm_embed)
        except Exception:
            pass

        embed = discord.Embed(
            title="🔓 Member Unjailed",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 Unjailed User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.add_field(name="💼 Roles Restored", value=f"{restored_count} role(s) returned", inline=True)
        embed.add_field(name="📅 Was Jailed Since", value=f"<t:{jailed_at}:R>", inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="VO AntiNuke • Jail System", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.followup.send(embed=embed)

        # Log
        log_channel_id = await self.bot.db.get_log_channel(interaction.guild.id)
        if log_channel_id:
            log_ch = interaction.guild.get_channel(log_channel_id)
            if log_ch:
                log_embed = discord.Embed(title="🔓 Moderation Action — Unjail", color=0x57f287, timestamp=discord.utils.utcnow())
                log_embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
                log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
                log_embed.add_field(name="Reason", value=reason, inline=False)
                log_embed.add_field(name="Roles Restored", value=str(restored_count), inline=True)
                log_embed.set_footer(text=f"User ID: {user.id}")
                await log_ch.send(embed=log_embed)

    @app_commands.command(name="jaillist", description="📋 View all currently jailed members")
    async def jaillist(self, interaction: discord.Interaction):
        await interaction.response.defer()
        is_bot_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not (interaction.user.guild_permissions.manage_roles or interaction.user.id == interaction.guild.owner_id or is_bot_admin):
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Access Denied", description="You need **Manage Roles** permission, be the server owner, or be an authorized bot admin.", color=0xff0000),
                ephemeral=True
            )
            return

        jailed = await self.bot.jail_db.get_all_jailed(interaction.guild.id)

        if not jailed:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="📋 Jailed Members",
                    description="✅ No members are currently jailed.",
                    color=0x57f287
                )
            )
            return

        embed = discord.Embed(
            title="📋 Currently Jailed Members",
            description=f"**{len(jailed)}** member(s) are currently jailed.",
            color=0xff6600,
            timestamp=discord.utils.utcnow()
        )

        for user_id, mod_id, reason, jailed_at, expires_at in jailed[:10]:
            member = interaction.guild.get_member(user_id)
            member_str = f"{member.mention}" if member else f"Unknown (`{user_id}`)"
            mod = interaction.guild.get_member(mod_id)
            mod_str = str(mod) if mod else f"Unknown (`{mod_id}`)"
            expires_str = f"<t:{expires_at}:R>" if expires_at else "Permanent"

            embed.add_field(
                name=f"{member_str}",
                value=(
                    f"**Reason:** {reason}\n"
                    f"**By:** {mod_str}\n"
                    f"**Since:** <t:{jailed_at}:R>\n"
                    f"**Expires:** {expires_str}"
                ),
                inline=False
            )

        embed.set_footer(text="VO AntiNuke • Jail System", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Jail(bot))