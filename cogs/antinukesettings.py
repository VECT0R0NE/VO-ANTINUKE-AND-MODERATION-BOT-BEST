import discord
from discord import app_commands
from discord.ext import commands
from utils.checks import is_owner_or_admin

ACTION_LABELS = {
    'banning_members':              ('🔨', 'Banning Members'),
    'kicking_members':              ('👢', 'Kicking Members'),
    'creating_channels':            ('📢', 'Creating Channels'),
    'deleting_channels':            ('🗑️', 'Deleting Channels'),
    'creating_roles':               ('🏷️', 'Creating Roles'),
    'deleting_roles':               ('❌', 'Deleting Roles'),
    'editing_channels':             ('✏️', 'Editing Channels'),
    'editing_roles':                ('📝', 'Editing Roles'),
    'giving_dangerous_permissions': ('⚠️', 'Dangerous Permissions'),
    'giving_administrative_roles':  ('👑', 'Admin Role Grants'),
    'adding_bots':                  ('🤖', 'Adding Bots'),
    'updating_server':              ('🌐', 'Updating Server'),
    'creating_webhooks':            ('🔗', 'Creating Webhooks'),
    'deleting_webhooks':            ('🔗', 'Deleting Webhooks'),
    'authorizing_applications':     ('🔌', 'Authorizing Apps'),
    'timing_out_members':           ('⏰', 'Timing Out Members'),
    'changing_nicknames':           ('📛', 'Changing Nicknames'),
    'pruning_members':              ('✂️', 'Pruning Members'),
}

PUNISHMENT_LABELS = {
    'ban':         '🔨 Ban',
    'kick':        '👢 Kick',
    'clear_roles': '🔓 Clear Roles',
    'timeout':     '⏰ Timeout',
    'warn':        '⚠️ Warn',
}


class AntiNukeSettings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="antinukestatus",
        description="🛡️ View the full Anti-Nuke protection status and settings for this server"
    )
    @is_owner_or_admin()
    async def antinukestatus(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        guild_id = interaction.guild.id

        toggles = await self.bot.db.get_all_toggles(guild_id)
        rows = []
        for action, (emoji, label) in ACTION_LABELS.items():
            limit = await self.bot.db.get_limit(guild_id, action)
            timeframe = await self.bot.db.get_timeframe(guild_id, action)
            punishment = await self.bot.db.get_punishment(guild_id, action)
            enabled = toggles.get(action, True)  # default True if never set

            limit_str = str(limit) if limit is not None else '—'
            timeframe_str = str(timeframe) if timeframe is not None else '—'
            punishment_str = PUNISHMENT_LABELS.get(punishment, punishment or '—')
            status_icon = '🟢' if enabled else '🔴'

            rows.append((emoji, label, limit_str, timeframe_str, punishment_str, status_icon))

        embeds = []
        half = len(rows) // 2 + len(rows) % 2

        for chunk_index, chunk in enumerate([rows[:half], rows[half:]]):
            title = "🛡️ Anti-Nuke Status" if chunk_index == 0 else "🛡️ Anti-Nuke Status (cont.)"
            embed = discord.Embed(title=title, color=0x5865f2, timestamp=discord.utils.utcnow())

            if chunk_index == 0:
                embed.description = (
                    f"Protection status for **{interaction.guild.name}**.\n"
                    "🟢 = enabled  🔴 = disabled\n"
                    "**Format:** `Max / Timeframe(s) → Punishment`"
                )

            for emoji, label, limit_str, timeframe_str, punishment_str, status_icon in chunk:
                embed.add_field(
                    name=f"{status_icon} {emoji} {label}",
                    value=f"`{limit_str}` / `{timeframe_str}s` → {punishment_str}",
                    inline=True,
                )

            remainder = len(chunk) % 3
            if remainder != 0:
                for _ in range(3 - remainder):
                    embed.add_field(name="\u200b", value="\u200b", inline=True)

            embed.set_footer(text="VO AntiNuke • Use /toggleprotection to enable/disable",
                             icon_url=interaction.guild.me.display_avatar.url)
            embeds.append(embed)

        # Summary embed
        whitelist_count = len(await self.bot.db.get_whitelist(guild_id))
        whitelist_roles = await self.bot.db.get_whitelist_roles(guild_id)
        log_channel_id = await self.bot.db.get_log_channel(guild_id)
        log_channel = interaction.guild.get_channel(log_channel_id) if log_channel_id else None
        prefix = await self.bot.db.get_prefix(guild_id)
        dm_alerts = await self.bot.db.get_dm_alerts(guild_id)
        backup_count = await self.bot.db.count_server_backups(guild_id)
        enabled_count = sum(1 for a in ACTION_LABELS if toggles.get(a, True))

        summary = discord.Embed(title="⚙️ Server Configuration", color=0x57f287, timestamp=discord.utils.utcnow())
        summary.add_field(name="📋 Log Channel", value=log_channel.mention if log_channel else '`Not set`', inline=True)
        summary.add_field(name="🔤 Prefix", value=f"`{prefix}`", inline=True)
        summary.add_field(name="🔔 DM Alerts", value='`Enabled`' if dm_alerts else '`Disabled`', inline=True)
        summary.add_field(name="✅ Global Whitelisted", value=str(whitelist_count), inline=True)
        summary.add_field(name="🎭 Whitelisted Roles", value=str(len(whitelist_roles)), inline=True)
        summary.add_field(name="📦 Backups Saved", value=f"{backup_count}/10", inline=True)
        summary.add_field(name="🛡️ Active Protections", value=f"{enabled_count}/{len(ACTION_LABELS)}", inline=True)
        summary.set_footer(text="VO AntiNuke • Protection System", icon_url=interaction.guild.me.display_avatar.url)

        await interaction.followup.send(embeds=[*embeds, summary])


async def setup(bot):
    await bot.add_cog(AntiNukeSettings(bot))
