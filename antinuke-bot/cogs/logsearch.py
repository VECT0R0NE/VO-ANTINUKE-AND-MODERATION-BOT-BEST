import discord
from discord import app_commands
from discord.ext import commands
import time

BOT_NAME = "VO AntiNuke"

ACTION_CHOICES = [
    app_commands.Choice(name="warn",      value="warn"),
    app_commands.Choice(name="mute",      value="mute"),
    app_commands.Choice(name="kick",      value="kick"),
    app_commands.Choice(name="ban",       value="ban"),
    app_commands.Choice(name="unban",     value="unban"),
    app_commands.Choice(name="jail",      value="jail"),
    app_commands.Choice(name="lockdown",  value="lockdown"),
    app_commands.Choice(name="massban",   value="massban"),
    app_commands.Choice(name="antinuke",  value="antinuke"),
    app_commands.Choice(name="note",      value="note"),
    app_commands.Choice(name="slowmode",  value="slowmode"),
    app_commands.Choice(name="purge",     value="purge"),
]


async def _is_admin(bot, guild_id, user_id):
    return await bot.db.is_admin(guild_id, user_id)


class LogSearch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="logsearch",
        description="🔍 Search moderation action history with filters"
    )
    @app_commands.describe(
        target="Filter by a specific target user",
        moderator="Filter by a specific moderator",
        action="Filter by action type",
        page="Page number (default 1)"
    )
    @app_commands.choices(action=ACTION_CHOICES)
    async def logsearch(
        self,
        interaction: discord.Interaction,
        target: discord.User = None,
        moderator: discord.User = None,
        action: str = None,
        page: int = 1
    ):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.manage_messages or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Manage Messages** permission or be a bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        # Defer immediately to avoid 3-second timeout
        await interaction.response.defer(thinking=True)

        page = max(1, page)
        per_page = 10
        offset = (page - 1) * per_page

        results = await self.bot.db.search_mod_actions(
            guild_id=interaction.guild.id,
            target_id=target.id if target else None,
            moderator_id=moderator.id if moderator else None,
            action=action,
            limit=per_page,
            offset=offset
        )

        total = await self.bot.db.count_mod_actions(
            guild_id=interaction.guild.id,
            target_id=target.id if target else None,
            moderator_id=moderator.id if moderator else None,
            action=action
        )

        total_pages = max(1, (total + per_page - 1) // per_page)

        # Build filter summary
        filters = []
        if target:
            filters.append(f"Target: {target.mention}")
        if moderator:
            filters.append(f"Moderator: {moderator.mention}")
        if action:
            filters.append(f"Action: `{action}`")
        filter_str = " | ".join(filters) if filters else "No filters"

        embed = discord.Embed(
            title="🔍 Moderation Log Search",
            description=f"**Filters:** {filter_str}\n**Total results:** {total}",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )

        if not results:
            embed.add_field(name="No Results", value="No moderation actions matched your search.", inline=False)
        else:
            for entry in results:
                target_user = self.bot.get_user(entry["target_id"])
                target_str = str(target_user) if target_user else f"Unknown (`{entry['target_id']}`)"

                mod_user = self.bot.get_user(entry["moderator_id"])
                mod_str = str(mod_user) if mod_user else f"Unknown (`{entry['moderator_id']}`)"

                ts = f"<t:{entry['timestamp']}:R>"
                reason = entry.get("reason") or "No reason"
                if len(reason) > 80:
                    reason = reason[:77] + "..."

                embed.add_field(
                    name=f"#{entry['id']} — `{entry['action'].upper()}` {ts}",
                    value=f"**Target:** {target_str}\n**Mod:** {mod_str}\n**Reason:** {reason}",
                    inline=False
                )

        embed.set_footer(
            text=f"Page {page}/{total_pages} • {BOT_NAME} • Log Search",
            icon_url=interaction.guild.me.display_avatar.url
        )

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="logrecord",
        description="📝 Manually add a moderation action to the history log"
    )
    @app_commands.describe(
        target="The user who was actioned",
        action="The action taken",
        reason="Reason for the action"
    )
    @app_commands.choices(action=ACTION_CHOICES)
    async def logrecord(
        self,
        interaction: discord.Interaction,
        target: discord.User,
        action: str,
        reason: str = "No reason provided"
    ):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.manage_messages or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Manage Messages** permission or be a bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.log_mod_action(
            guild_id=interaction.guild.id,
            target_id=target.id,
            moderator_id=interaction.user.id,
            action=action,
            reason=reason
        )

        await interaction.followup.send(embed=discord.Embed(
            title="📝 Action Recorded",
            description=f"Manually logged `{action}` against {target.mention}.",
            color=0x57f287
        ).add_field(name="Reason", value=reason, inline=False), ephemeral=True)


async def setup(bot):
    await bot.add_cog(LogSearch(bot))