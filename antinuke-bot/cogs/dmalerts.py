import discord
from discord import app_commands
from discord.ext import commands

BOT_NAME = "VO AntiNuke"

# All event types that can have custom routing
DM_EVENT_TYPES = [
    "antinuke",      # Anti-nuke triggers / punishments
    "ban",           # Manual bans
    "kick",          # Manual kicks
    "warn",          # Warnings issued
    "mute",          # Mutes / timeouts
    "jail",          # Jail actions
    "note",          # Staff notes
    "nuke",          # Nuke command
    "tempban",       # Temp bans
]


async def send_dm_alert(bot, guild: discord.Guild, embed: discord.Embed, event_type: str = "antinuke"):
    """
    Send a DM alert to the configured targets.
    Checks per-event rules first; falls back to global target list; falls back to owner.
    """
    if not await bot.db.get_dm_alerts(guild.id):
        return

    rule = await bot.db.get_dm_alert_rule(guild.id, event_type)
    if not rule['enabled']:
        return

    # Per-event targets override global targets
    if rule['targets']:
        target_ids = rule['targets']
    else:
        target_ids = await bot.db.get_dm_alert_targets(guild.id)

    # Default: only owner
    if not target_ids:
        target_ids = [guild.owner_id]

    for uid in target_ids:
        try:
            user = bot.get_user(uid) or await bot.fetch_user(uid)
            if user:
                await user.send(embed=embed)
        except Exception:
            pass


class DmAlerts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _can_manage(self, interaction: discord.Interaction) -> bool:
        """Returns True if the user is allowed to manage DM alert settings."""
        if interaction.user.id == interaction.guild.owner_id:
            return True
        # Admins can manage only if owner has allowed it
        return False  # checked async below

    async def _can_manage_async(self, interaction: discord.Interaction) -> bool:
        await interaction.response.defer()
        if interaction.user.id == interaction.guild.owner_id:
            return True
        admin_can = await self.bot.db.get_dm_alert_admin_can_manage(interaction.guild.id)
        if admin_can and await self.bot.db.is_admin(interaction.guild.id, interaction.user.id):
            return True
        return False

    # ── /dmalerts ─────────────────────────────────────────────────────────────

    @app_commands.command(name="dmalerts", description="🔔 Enable or disable DM alerts for anti-nuke events")
    @app_commands.describe(enabled="True to enable, False to disable")
    async def dmalerts(self, interaction: discord.Interaction, enabled: bool):
        await interaction.response.defer()
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Owner Only",
                description="Only the **server owner** can toggle DM alerts.",
                color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_dm_alerts(interaction.guild.id, enabled)
        status = "✅ Enabled" if enabled else "❌ Disabled"
        color = 0x00ff00 if enabled else 0xff4444

        embed = discord.Embed(
            title=f"🔔 DM Alerts {status}",
            color=color,
            timestamp=discord.utils.utcnow()
        )
        if enabled:
            embed.description = (
                "DM alerts are now **enabled**. You will receive a DM whenever the anti-nuke "
                "system detects a threat or a moderation action is taken.\n\n"
                "Use `/dmalerts addtarget` to add extra notification recipients.\n"
                "Use `/dmalerts events` to configure per-event routing."
            )
        else:
            embed.description = "DM alerts are now **disabled**."
        embed.set_footer(text=f"VO AntiNuke • {interaction.guild.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /dmalerts addtarget ───────────────────────────────────────────────────

    @app_commands.command(name="dmalerts_addtarget", description="🔔 Add a user to receive DM alert notifications")
    @app_commands.describe(user="User to add as a DM alert recipient")
    async def dmalerts_addtarget(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer()
        if not await self._can_manage_async(interaction):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the **server owner** (or authorized admins) can manage DM alert targets.",
                color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.add_dm_alert_target(interaction.guild.id, user.id)
        targets = await self.bot.db.get_dm_alert_targets(interaction.guild.id)

        embed = discord.Embed(
            title="✅ DM Alert Target Added",
            description=f"{user.mention} will now receive DM alerts.",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="📋 All Targets", value="\n".join(f"<@{uid}>" for uid in targets) or "None", inline=False)
        embed.set_footer(text=f"VO AntiNuke • {interaction.guild.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /dmalerts removetarget ────────────────────────────────────────────────

    @app_commands.command(name="dmalerts_removetarget", description="🔔 Remove a user from DM alert notifications")
    @app_commands.describe(user="User to remove from DM alert recipients")
    async def dmalerts_removetarget(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer()
        if not await self._can_manage_async(interaction):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the **server owner** (or authorized admins) can manage DM alert targets.",
                color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.remove_dm_alert_target(interaction.guild.id, user.id)
        targets = await self.bot.db.get_dm_alert_targets(interaction.guild.id)

        embed = discord.Embed(
            title="🗑️ DM Alert Target Removed",
            description=f"{user.mention} has been removed from DM alerts.",
            color=0xff8800,
            timestamp=discord.utils.utcnow()
        )
        remaining = "\n".join(f"<@{uid}>" for uid in targets) if targets else "*(defaults to server owner)*"
        embed.add_field(name="📋 Remaining Targets", value=remaining, inline=False)
        embed.set_footer(text=f"VO AntiNuke • {interaction.guild.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /dmalerts allowadmins ─────────────────────────────────────────────────

    @app_commands.command(name="dmalerts_allowadmins", description="🔔 Allow or disallow bot admins to manage DM alert targets")
    @app_commands.describe(allowed="True = admins can manage targets, False = owner only")
    async def dmalerts_allowadmins(self, interaction: discord.Interaction, allowed: bool):
        await interaction.response.defer()
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Owner Only",
                description="Only the **server owner** can change admin management permissions.",
                color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_dm_alert_admin_can_manage(interaction.guild.id, allowed)
        status = "✅ Allowed" if allowed else "❌ Restricted"
        embed = discord.Embed(
            title=f"🔔 Admin DM Alert Management {status}",
            description=(
                f"Bot admins **{'can' if allowed else 'cannot'}** now manage DM alert targets.\n"
                f"The server owner always retains full control."
            ),
            color=0x57f287 if allowed else 0xff4444,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"VO AntiNuke • {interaction.guild.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /dmalerts setevent ────────────────────────────────────────────────────

    @app_commands.command(name="dmalerts_setevent", description="🔔 Configure DM alerts for a specific event type")
    @app_commands.describe(
        event="The event type to configure",
        enabled="Enable or disable alerts for this event",
        user="Optional: route this event's alerts only to this user (leave blank = use global targets)"
    )
    @app_commands.choices(event=[app_commands.Choice(name=e, value=e) for e in DM_EVENT_TYPES])
    async def dmalerts_setevent(
        self,
        interaction: discord.Interaction,
        event: str,
        enabled: bool,
        user: discord.Member = None
    ):
        await interaction.response.defer()
        if not await self._can_manage_async(interaction):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the **server owner** (or authorized admins) can manage DM alert events.",
                color=0xff0000
            ), ephemeral=True)
            return

        # Get current rule to preserve targets if not setting a new one
        rule = await self.bot.db.get_dm_alert_rule(interaction.guild.id, event)
        targets = rule.get('targets')
        if user is not None:
            targets = [user.id]

        await self.bot.db.set_dm_alert_rule(interaction.guild.id, event, enabled, targets)

        embed = discord.Embed(
            title=f"🔔 DM Alert Rule Updated: `{event}`",
            color=0x57f287 if enabled else 0xff4444,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Event", value=f"`{event}`", inline=True)
        embed.add_field(name="Status", value="✅ Enabled" if enabled else "❌ Disabled", inline=True)
        if targets:
            embed.add_field(name="Custom Target", value="\n".join(f"<@{uid}>" for uid in targets), inline=True)
        else:
            embed.add_field(name="Target", value="*(global targets / owner)*", inline=True)
        embed.set_footer(text=f"VO AntiNuke • {interaction.guild.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /dmalerts status ──────────────────────────────────────────────────────

    @app_commands.command(name="dmalerts_status", description="🔔 View the current DM alert configuration")
    async def dmalerts_status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not await self._can_manage_async(interaction):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the **server owner** (or authorized admins) can view DM alert status.",
                color=0xff0000
            ), ephemeral=True)
            return

        global_enabled = await self.bot.db.get_dm_alerts(interaction.guild.id)
        admin_can = await self.bot.db.get_dm_alert_admin_can_manage(interaction.guild.id)
        global_targets = await self.bot.db.get_dm_alert_targets(interaction.guild.id)
        rules = await self.bot.db.get_all_dm_alert_rules(interaction.guild.id)

        embed = discord.Embed(
            title="🔔 DM Alert Configuration",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Global Status", value="✅ Enabled" if global_enabled else "❌ Disabled", inline=True)
        embed.add_field(name="Admin Can Manage", value="✅ Yes" if admin_can else "❌ No", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        # Global targets
        if global_targets:
            target_str = "\n".join(f"<@{uid}>" for uid in global_targets)
        else:
            target_str = f"*(defaults to server owner: <@{interaction.guild.owner_id}>)*"
        embed.add_field(name="📋 Global Targets", value=target_str, inline=False)

        # Per-event rules
        if rules:
            rules_by_event = {r['event_type']: r for r in rules}
            event_lines = []
            for evt in DM_EVENT_TYPES:
                rule = rules_by_event.get(evt, {'enabled': True, 'targets': None})
                status_icon = "✅" if rule['enabled'] else "❌"
                custom = f" → <@{rule['targets'][0]}>" if rule.get('targets') else ""
                event_lines.append(f"{status_icon} `{evt}`{custom}")
            embed.add_field(name="📡 Per-Event Rules", value="\n".join(event_lines), inline=False)
        else:
            embed.add_field(name="📡 Per-Event Rules", value="*(all events use global defaults)*", inline=False)

        embed.set_footer(text=f"VO AntiNuke • {interaction.guild.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /dmalerts cleartargets ────────────────────────────────────────────────

    @app_commands.command(name="dmalerts_cleartargets", description="🔔 Remove all DM alert targets (resets to owner-only)")
    async def dmalerts_cleartargets(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Owner Only",
                description="Only the **server owner** can clear all DM alert targets.",
                color=0xff0000
            ), ephemeral=True)
            return

        await self.bot.db.set_dm_alert_targets(interaction.guild.id, [])
        embed = discord.Embed(
            title="🧹 DM Alert Targets Cleared",
            description="All custom targets removed. DM alerts will now go to the **server owner** only.",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"VO AntiNuke • {interaction.guild.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(DmAlerts(bot))
