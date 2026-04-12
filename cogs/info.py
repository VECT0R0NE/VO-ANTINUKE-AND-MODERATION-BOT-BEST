import discord
from discord import app_commands
from discord.ext import commands
import time

BOT_NAME = "VO AntiNuke"


async def _is_admin(bot, guild_id, user_id):
    return await bot.db.is_admin(guild_id, user_id)


def _perm_flags(permissions: discord.Permissions) -> list[str]:
    """Return a human-readable list of notable permissions."""
    notable = {
        "administrator": "Administrator",
        "manage_guild": "Manage Server",
        "manage_channels": "Manage Channels",
        "manage_roles": "Manage Roles",
        "manage_messages": "Manage Messages",
        "manage_webhooks": "Manage Webhooks",
        "manage_nicknames": "Manage Nicknames",
        "kick_members": "Kick Members",
        "ban_members": "Ban Members",
        "moderate_members": "Timeout Members",
        "mention_everyone": "Mention @everyone",
        "view_audit_log": "View Audit Log",
        "manage_expressions": "Manage Expressions",
        "move_members": "Move Members",
    }
    active = []
    for attr, label in notable.items():
        if getattr(permissions, attr, False):
            active.append(label)
    return active


class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ────────────────────────── /userinfo ────────────────────────

    @app_commands.command(name="userinfo", description="👤 View detailed info about a member")
    @app_commands.describe(user="The member to inspect (defaults to yourself)")
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user

        warn_count = await self.bot.warns_db.get_warn_count(interaction.guild.id, target.id)
        is_jailed = await self.bot.jail_db.get_jailed_user(interaction.guild.id, target.id) is not None
        is_admin = await self.bot.db.is_admin(interaction.guild.id, target.id)
        is_whitelisted = await self.bot.db.is_globally_whitelisted(interaction.guild.id, target.id)
        is_muted = target.is_timed_out()

        # Determine color
        if target.id == interaction.guild.owner_id:
            color = 0xffd700
        elif target.guild_permissions.administrator:
            color = 0xff4444
        elif warn_count >= 3 or is_jailed:
            color = 0xff8800
        else:
            color = target.color if target.color != discord.Color.default() else 0x5865f2

        embed = discord.Embed(
            title=f"👤 {target.display_name}",
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        # Identity
        embed.add_field(name="🏷️ Username", value=f"`{target}`", inline=True)
        embed.add_field(name="🆔 User ID", value=f"`{target.id}`", inline=True)
        embed.add_field(name="🤖 Bot Account", value="✅ Yes" if target.bot else "❌ No", inline=True)

        # Dates
        created_ts = int(target.created_at.timestamp())
        joined_ts = int(target.joined_at.timestamp()) if target.joined_at else None
        embed.add_field(name="📅 Account Created", value=f"<t:{created_ts}:F>\n(<t:{created_ts}:R>)", inline=True)
        embed.add_field(
            name="📥 Joined Server",
            value=f"<t:{joined_ts}:F>\n(<t:{joined_ts}:R>)" if joined_ts else "Unknown",
            inline=True
        )

        # Boost status
        if target.premium_since:
            boost_ts = int(target.premium_since.timestamp())
            embed.add_field(name="💎 Boosting Since", value=f"<t:{boost_ts}:R>", inline=True)

        # Roles (up to 15)
        roles = [r for r in reversed(target.roles) if r != interaction.guild.default_role]
        if roles:
            role_mentions = " ".join(r.mention for r in roles[:15])
            if len(roles) > 15:
                role_mentions += f" *+{len(roles) - 15} more*"
            embed.add_field(name=f"🎭 Roles ({len(roles)})", value=role_mentions, inline=False)

        # Moderation status
        status_lines = []
        if target.id == interaction.guild.owner_id:
            status_lines.append("👑 **Server Owner**")
        if is_admin:
            status_lines.append("🛡️ **Bot Admin**")
        if is_whitelisted:
            status_lines.append("✅ **Anti-Nuke Whitelisted**")
        if is_muted:
            muted_until_ts = int(target.timed_out_until.timestamp())
            status_lines.append(f"🔇 **Muted** until <t:{muted_until_ts}:R>")
        if is_jailed:
            status_lines.append("🔒 **Currently Jailed**")
        if warn_count > 0:
            status_lines.append(f"⚠️ **{warn_count} Warning(s)** on record")

        if not status_lines:
            status_lines.append("✅ No active punishments or flags")

        embed.add_field(name="⚡ Moderation Status", value="\n".join(status_lines), inline=False)

        # Top role
        if roles:
            embed.add_field(name="🏅 Top Role", value=roles[0].mention, inline=True)

        embed.set_footer(text=f"{BOT_NAME} • User Information", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ────────────────────────── /serverinfo ──────────────────────

    @app_commands.command(name="serverinfo", description="🏠 View detailed information about this server")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        await interaction.response.defer()

        # Counts
        total_members = guild.member_count
        bots = sum(1 for m in guild.members if m.bot)
        humans = total_members - bots
        online = sum(1 for m in guild.members if m.status != discord.Status.offline and not m.bot)

        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        threads = len(guild.threads)

        total_roles = len(guild.roles) - 1  # exclude @everyone
        boosters = guild.premium_subscription_count
        boost_level = guild.premium_tier

        created_ts = int(guild.created_at.timestamp())

        # Verification level map
        verify_map = {
            discord.VerificationLevel.none: "None",
            discord.VerificationLevel.low: "Low",
            discord.VerificationLevel.medium: "Medium",
            discord.VerificationLevel.high: "High",
            discord.VerificationLevel.highest: "Highest",
        }

        embed = discord.Embed(
            title=f"🏠 {guild.name}",
            description=guild.description or "",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        # Banner (if any)
        if guild.banner:
            embed.set_image(url=guild.banner.with_format("png").with_size(1024).url)

        embed.add_field(name="🆔 Server ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="👑 Owner", value=f"<@{guild.owner_id}>", inline=True)
        embed.add_field(name="📅 Created", value=f"<t:{created_ts}:F>\n(<t:{created_ts}:R>)", inline=True)

        # Member counts
        embed.add_field(
            name="👥 Members",
            value=f"**Total:** {total_members:,}\n**Humans:** {humans:,}\n**Bots:** {bots:,}\n**Online:** {online:,}",
            inline=True
        )

        # Channel counts
        embed.add_field(
            name="📌 Channels",
            value=f"**Text:** {text_channels}\n**Voice:** {voice_channels}\n**Categories:** {categories}\n**Threads:** {threads}",
            inline=True
        )

        # Boost info
        boost_bar = "⬜" * 14
        if boost_level == 1:
            boost_bar = "🟣" * 2 + "⬜" * 12
        elif boost_level == 2:
            boost_bar = "🟣" * 7 + "⬜" * 7
        elif boost_level >= 3:
            boost_bar = "🟣" * 14

        embed.add_field(
            name="💎 Server Boost",
            value=f"**Level {boost_level}** — {boosters} booster(s)\n{boost_bar}",
            inline=True
        )

        embed.add_field(name="🎭 Roles", value=f"{total_roles}", inline=True)
        embed.add_field(name="🔒 Verification", value=verify_map.get(guild.verification_level, "Unknown"), inline=True)

        features = guild.features
        if features:
            nice_features = [f.replace("_", " ").title() for f in features[:8]]
            embed.add_field(name="✨ Features", value="\n".join(nice_features), inline=False)

        embed.set_footer(text=f"{BOT_NAME} • Server Information", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.followup.send(embed=embed)

    # ────────────────────────── /roleinfo ────────────────────────

    @app_commands.command(name="roleinfo", description="🎭 View detailed information about a role")
    @app_commands.describe(role="The role to inspect")
    async def roleinfo(self, interaction: discord.Interaction, role: discord.Role):
        created_ts = int(role.created_at.timestamp())
        members_with_role = len(role.members)

        embed = discord.Embed(
            title=f"🎭 Role: {role.name}",
            color=role.color if role.color != discord.Color.default() else 0x5865f2,
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(name="🆔 Role ID", value=f"`{role.id}`", inline=True)
        embed.add_field(name="📅 Created", value=f"<t:{created_ts}:R>", inline=True)
        embed.add_field(name="📊 Position", value=f"#{role.position} (of {len(interaction.guild.roles)})", inline=True)

        # Color
        hex_color = f"#{role.color.value:06X}" if role.color != discord.Color.default() else "None"
        embed.add_field(name="🎨 Color", value=hex_color, inline=True)
        embed.add_field(name="👥 Members", value=f"{members_with_role:,}", inline=True)

        # Flags
        flags = []
        if role.hoist:
            flags.append("📌 Displayed separately")
        if role.mentionable:
            flags.append("📢 Mentionable")
        if role.managed:
            flags.append("🤖 Managed by integration")
        if role == interaction.guild.premium_subscriber_role:
            flags.append("💎 Boost role")
        if not flags:
            flags.append("—")
        embed.add_field(name="🏷️ Flags", value="\n".join(flags), inline=True)

        # Permissions
        perms = _perm_flags(role.permissions)
        if role.permissions.administrator:
            perm_text = "⚠️ **Administrator** (all permissions)"
        elif perms:
            perm_text = "\n".join(f"• {p}" for p in perms)
        else:
            perm_text = "No notable permissions"

        embed.add_field(name="🔑 Key Permissions", value=perm_text[:1024], inline=False)

        embed.set_footer(text=f"{BOT_NAME} • Role Information", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ────────────────────────── /whitelistinfo ───────────────────

    @app_commands.command(name="whitelistinfo", description="📋 View all current whitelist entries for this server")
    async def whitelistinfo(self, interaction: discord.Interaction):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the server owner, administrators, or authorized bot admins can view whitelist info.",
                color=0xff0000
            ), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Fetch all whitelist data
        global_wl = await self.bot.db.get_whitelist(interaction.guild.id)
        role_wl = await self.bot.db.get_whitelist_roles(interaction.guild.id)
        now = int(time.time())

        # Temp whitelists
        from utils.database import Database
        temp_rows = await self.bot.db._fetchall(
            'SELECT user_id, expires_at FROM whitelist_temp WHERE guild_id = ? AND expires_at > ?',
            (interaction.guild.id, now)
        )

        embed = discord.Embed(
            title="📋 Whitelist Overview",
            description=f"All current whitelist entries for **{interaction.guild.name}**",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )

        # Global whitelist
        if global_wl:
            lines = []
            for uid in global_wl[:20]:
                member = interaction.guild.get_member(uid)
                if member:
                    lines.append(f"{member.mention} `{uid}`")
                else:
                    lines.append(f"*Unknown User* `{uid}`")
            text = "\n".join(lines)
            if len(global_wl) > 20:
                text += f"\n*...and {len(global_wl) - 20} more*"
            embed.add_field(name=f"🌍 Global Whitelist ({len(global_wl)})", value=text, inline=False)
        else:
            embed.add_field(name="🌍 Global Whitelist (0)", value="*No globally whitelisted users.*", inline=False)

        # Temp whitelist
        if temp_rows:
            lines = []
            for row in temp_rows[:10]:
                uid, expires_at = row[0], row[1]
                member = interaction.guild.get_member(uid)
                name_str = member.mention if member else f"*Unknown* `{uid}`"
                lines.append(f"{name_str} — expires <t:{expires_at}:R>")
            embed.add_field(name=f"⏳ Temporary Whitelist ({len(temp_rows)})", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="⏳ Temporary Whitelist (0)", value="*No temporary whitelists active.*", inline=False)

        # Role whitelist
        if role_wl:
            lines = []
            for rid in role_wl:
                role = interaction.guild.get_role(rid)
                if role:
                    lines.append(f"{role.mention} `{rid}` — {len(role.members)} member(s)")
                else:
                    lines.append(f"*Deleted Role* `{rid}`")
            embed.add_field(name=f"🎭 Whitelisted Roles ({len(role_wl)})", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="🎭 Whitelisted Roles (0)", value="*No whitelisted roles.*", inline=False)

        # Summary
        total = len(global_wl) + len(temp_rows) + len(role_wl)
        embed.add_field(name="📊 Summary", value=f"**{total}** total whitelist entries", inline=False)

        embed.set_footer(text=f"{BOT_NAME} • Whitelist Information", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Info(bot))