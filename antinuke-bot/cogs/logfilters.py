import discord
from discord import app_commands
from discord.ext import commands

BOT_NAME = "VO AntiNuke"

TOGGLEABLE_EVENTS = {
    "warns":      ("log_warns",     "⚠️ Warns"),
    "mutes":      ("log_mutes",     "🔇 Mutes"),
    "kicks":      ("log_kicks",     "👢 Kicks"),
    "bans":       ("log_bans",      "🔨 Bans"),
    "unbans":     ("log_unbans",    "🔓 Unbans"),
    "jails":      ("log_jails",     "🔒 Jails"),
    "lockdowns":  ("log_lockdowns", "🚪 Lockdowns"),
    "massbans":   ("log_massbans",  "🔨 Mass Bans"),
    "antinuke":   ("log_antinuke",  "🛡️ Anti-Nuke"),
    "notes":      ("log_notes",     "📝 Notes"),
    "slowmode":   ("log_slowmode",  "⏱️ Slowmode"),
    "purge":      ("log_purge",     "🗑️ Purge"),
}


async def _is_admin(bot, guild_id, user_id):
    return await bot.db.is_admin(guild_id, user_id)


class LogFilters(commands.Cog):
    """Highly customisable moderation log filters."""

    def __init__(self, bot):
        self.bot = bot

    logfilter = app_commands.Group(name="logfilter", description="⚙️ Configure mod-log filters")

    # ─── /logfilter status ───────────────────────────────────────────────────

    @logfilter.command(name="status", description="📊 Show current log filter settings")
    async def lf_status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                description="❌ Access denied.", color=0xff0000), ephemeral=True)
            return

        f = await self.bot.db.get_mod_log_filters(interaction.guild.id)
        embed = discord.Embed(
            title="⚙️ Mod-Log Filter Settings",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )

        # Global toggles
        status_str = "✅ Enabled" if f.get("enabled", 1) else "❌ Disabled"
        ignore_bots_str = "✅ Yes" if f.get("ignore_bots", 0) else "❌ No"
        embed.add_field(name="📋 Logging", value=status_str, inline=True)
        embed.add_field(name="🤖 Ignore Bots", value=ignore_bots_str, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        # Event toggles
        event_lines = []
        for key, (db_key, label) in TOGGLEABLE_EVENTS.items():
            val = "✅" if f.get(db_key, 1) else "❌"
            event_lines.append(f"{val} {label}")

        embed.add_field(
            name="📝 Event Toggles",
            value="\n".join(event_lines) or "*none*",
            inline=False
        )

        # Ignored users
        ignored_users = f.get("ignored_users", [])
        if ignored_users:
            mentions = " ".join(f"<@{uid}>" for uid in ignored_users[:10])
            if len(ignored_users) > 10:
                mentions += f" *+{len(ignored_users)-10} more*"
            embed.add_field(name=f"🚫 Ignored Users ({len(ignored_users)})", value=mentions, inline=False)

        # Ignored roles
        ignored_roles = f.get("ignored_roles", [])
        if ignored_roles:
            roles_str = " ".join(f"<@&{rid}>" for rid in ignored_roles[:10])
            if len(ignored_roles) > 10:
                roles_str += f" *+{len(ignored_roles)-10} more*"
            embed.add_field(name=f"🚫 Ignored Roles ({len(ignored_roles)})", value=roles_str, inline=False)

        # Ignored actions
        ignored_actions = f.get("ignored_actions", [])
        if ignored_actions:
            embed.add_field(name="🚫 Ignored Actions", value=", ".join(f"`{a}`" for a in ignored_actions), inline=False)

        embed.set_footer(text=f"{BOT_NAME} • Log Filters")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── /logfilter enable / disable ────────────────────────────────────────

    @logfilter.command(name="enable", description="✅ Enable mod-log entirely")
    async def lf_enable(self, interaction: discord.Interaction):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                description="❌ Access denied.", color=0xff0000), ephemeral=True)
            return
        await self.bot.db.set_mod_log_filter(interaction.guild.id, "enabled", True)
        await interaction.followup.send(embed=discord.Embed(
            title="✅ Mod-Log Enabled",
            description="All moderation actions will now be logged (subject to event filters).",
            color=0x57f287
        ), ephemeral=True)

    @logfilter.command(name="disable", description="❌ Disable mod-log entirely")
    async def lf_disable(self, interaction: discord.Interaction):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                description="❌ Access denied.", color=0xff0000), ephemeral=True)
            return
        await self.bot.db.set_mod_log_filter(interaction.guild.id, "enabled", False)
        await interaction.followup.send(embed=discord.Embed(
            title="❌ Mod-Log Disabled",
            description="No moderation actions will be logged until you re-enable it.",
            color=0xff4444
        ), ephemeral=True)

    # ─── /logfilter ignorebots ───────────────────────────────────────────────

    @logfilter.command(name="ignorebots", description="🤖 Toggle whether bot moderators are ignored in logs")
    @app_commands.describe(ignore="True to ignore bots, False to log bot actions")
    async def lf_ignorebots(self, interaction: discord.Interaction, ignore: bool):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                description="❌ Access denied.", color=0xff0000), ephemeral=True)
            return
        await self.bot.db.set_mod_log_filter(interaction.guild.id, "ignore_bots", ignore)
        await interaction.followup.send(embed=discord.Embed(
            title="🤖 Bot Ignore Setting Updated",
            description=f"Bot moderator actions will now be **{'ignored' if ignore else 'logged'}**.",
            color=0x5865f2
        ), ephemeral=True)

    # ─── /logfilter event ────────────────────────────────────────────────────

    @logfilter.command(name="event", description="🎛️ Toggle logging for a specific event type")
    @app_commands.describe(
        event="The event type to toggle",
        enabled="True to log, False to suppress"
    )
    @app_commands.choices(event=[
        app_commands.Choice(name=label, value=key)
        for key, (_, label) in TOGGLEABLE_EVENTS.items()
    ])
    async def lf_event(self, interaction: discord.Interaction, event: str, enabled: bool):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                description="❌ Access denied.", color=0xff0000), ephemeral=True)
            return

        if event not in TOGGLEABLE_EVENTS:
            await interaction.followup.send(embed=discord.Embed(
                description="❌ Unknown event type.", color=0xff0000), ephemeral=True)
            return

        db_key, label = TOGGLEABLE_EVENTS[event]
        await self.bot.db.set_mod_log_filter(interaction.guild.id, db_key, enabled)
        await interaction.followup.send(embed=discord.Embed(
            title=f"{'✅' if enabled else '❌'} {label} Logging {'Enabled' if enabled else 'Disabled'}",
            description=f"{label} actions will now be **{'logged' if enabled else 'suppressed'}** in the mod-log.",
            color=0x57f287 if enabled else 0xff4444
        ), ephemeral=True)

    # ─── /logfilter ignoreuser ───────────────────────────────────────────────

    @logfilter.command(name="ignoreuser", description="🚫 Ignore or un-ignore a moderator in mod-logs")
    @app_commands.describe(
        user="The moderator to ignore/un-ignore",
        ignore="True to ignore, False to stop ignoring"
    )
    async def lf_ignoreuser(self, interaction: discord.Interaction, user: discord.Member, ignore: bool):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                description="❌ Access denied.", color=0xff0000), ephemeral=True)
            return

        f = await self.bot.db.get_mod_log_filters(interaction.guild.id)
        ignored = f.get("ignored_users", [])

        if ignore:
            if user.id not in ignored:
                ignored.append(user.id)
        else:
            if user.id in ignored:
                ignored.remove(user.id)

        await self.bot.db.set_mod_log_filter(interaction.guild.id, "ignored_users", ignored)
        await interaction.followup.send(embed=discord.Embed(
            title=f"{'🚫 User Ignored' if ignore else '✅ User Un-ignored'}",
            description=f"{user.mention}'s moderation actions will now be **{'suppressed from' if ignore else 'shown in'}** the mod-log.",
            color=0xff4444 if ignore else 0x57f287
        ), ephemeral=True)

    # ─── /logfilter ignorerole ───────────────────────────────────────────────

    @logfilter.command(name="ignorerole", description="🚫 Ignore or un-ignore a role in mod-logs")
    @app_commands.describe(
        role="The role to ignore/un-ignore",
        ignore="True to ignore, False to stop ignoring"
    )
    async def lf_ignorerole(self, interaction: discord.Interaction, role: discord.Role, ignore: bool):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                description="❌ Access denied.", color=0xff0000), ephemeral=True)
            return

        f = await self.bot.db.get_mod_log_filters(interaction.guild.id)
        ignored = f.get("ignored_roles", [])

        if ignore:
            if role.id not in ignored:
                ignored.append(role.id)
        else:
            if role.id in ignored:
                ignored.remove(role.id)

        await self.bot.db.set_mod_log_filter(interaction.guild.id, "ignored_roles", ignored)
        await interaction.followup.send(embed=discord.Embed(
            title=f"{'🚫 Role Ignored' if ignore else '✅ Role Un-ignored'}",
            description=f"Moderators with {role.mention} will now be **{'suppressed from' if ignore else 'shown in'}** the mod-log.",
            color=0xff4444 if ignore else 0x57f287
        ), ephemeral=True)

    # ─── /logfilter reset ────────────────────────────────────────────────────

    @logfilter.command(name="reset", description="🔄 Reset all log filters to defaults")
    async def lf_reset(self, interaction: discord.Interaction):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                description="❌ Access denied.", color=0xff0000), ephemeral=True)
            return

        # Re-insert defaults by deleting and re-ensuring
        await self.bot.db._execute(
            "DELETE FROM mod_log_filters WHERE guild_id=?", (interaction.guild.id,)
        )
        await self.bot.db._ensure_mod_log_filters(interaction.guild.id)

        await interaction.followup.send(embed=discord.Embed(
            title="🔄 Log Filters Reset",
            description="All mod-log filters have been reset to their defaults (all events enabled, no ignores).",
            color=0x57f287
        ), ephemeral=True)


async def setup(bot):
    await bot.add_cog(LogFilters(bot))