import discord
from discord import app_commands
from discord.ext import commands
from utils.checks import is_owner_or_admin
from utils.helpers import ACTIONS

ACTION_CHOICES = [
    app_commands.Choice(name=a.replace('_', ' ').title(), value=a)
    for a in ACTIONS
]


async def _resolve_user(interaction: discord.Interaction, user_id: str):
    """Resolve a user ID string to a Member or User object. Works for bots too."""
    try:
        uid = int(user_id.strip().lstrip('<@!>').rstrip('>'))
    except ValueError:
        return None, "❌ Invalid user ID. Provide a numeric ID or mention."

    member = interaction.guild.get_member(uid)
    if member:
        return member, None

    try:
        user = await interaction.client.fetch_user(uid)
        return user, None
    except discord.NotFound:
        return None, f"❌ No user or bot found with ID `{uid}`."
    except Exception:
        return None, "❌ Failed to look up that user ID."


class Unwhitelist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Remove global whitelist ────────────────────────────────────────────────

    @app_commands.command(name='unwhitelist', description='Remove a user or bot from the global whitelist')
    @app_commands.describe(user_id='User/bot mention or ID to remove from global whitelist')
    @is_owner_or_admin()
    async def unwhitelist(self, interaction: discord.Interaction, user_id: str):
        user, err = await _resolve_user(interaction, user_id)
        if err:
            await interaction.response.send_message(embed=discord.Embed(description=err, color=0xff0000), ephemeral=True)
            return

        if not await self.bot.db.is_globally_whitelisted(interaction.guild.id, user.id):
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ Not Globally Whitelisted",
                description=f"<@{user.id}> is not on the global whitelist.",
                color=0xffaa00), ephemeral=True)
            return

        await self.bot.db.remove_whitelist(interaction.guild.id, user.id)
        await self.bot.db.log_whitelist_audit(
            interaction.guild.id, user.id, 'user',
            'global_whitelist_remove',
            f'Removed {user} ({user.id}) from global whitelist',
            interaction.user.id
        )

        embed = discord.Embed(
            title="✅ Removed from Global Whitelist",
            description=f"<@{user.id}> has been removed and is no longer globally exempt.",
            color=0x00ff00
        )
        embed.add_field(name="User/Bot", value=f"<@{user.id}>\n`{user.id}`", inline=False)
        embed.set_footer(text=f"Removed by {interaction.user}")
        await interaction.response.send_message(embed=embed)

    # ── Remove per-action whitelist ────────────────────────────────────────────

    @app_commands.command(name='unwhitelistaction', description='Remove a user or bot\'s per-action whitelist exemption')
    @app_commands.describe(user_id='User/bot mention or ID', action='Action to remove exemption for')
    @app_commands.choices(action=ACTION_CHOICES)
    @is_owner_or_admin()
    async def unwhitelistaction(self, interaction: discord.Interaction,
                                 user_id: str, action: app_commands.Choice[str]):
        user, err = await _resolve_user(interaction, user_id)
        if err:
            await interaction.response.send_message(embed=discord.Embed(description=err, color=0xff0000), ephemeral=True)
            return

        if not await self.bot.db.is_action_whitelisted(interaction.guild.id, user.id, action.value):
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ Not Whitelisted for That Action",
                description=f"<@{user.id}> has no per-action exemption for **{action.name}**.",
                color=0xffaa00), ephemeral=True)
            return

        await self.bot.db.remove_whitelist_action(interaction.guild.id, user.id, action.value)
        await self.bot.db.log_whitelist_audit(
            interaction.guild.id, user.id, 'user',
            'action_whitelist_remove',
            f'Removed per-action whitelist for {user} ({user.id}): {action.value}',
            interaction.user.id
        )

        embed = discord.Embed(
            title="✅ Per-Action Whitelist Removed",
            description=f"<@{user.id}> is no longer exempt from **{action.name}** protection.",
            color=0x00ff00
        )
        embed.add_field(name="User/Bot", value=f"<@{user.id}>\n`{user.id}`", inline=True)
        embed.add_field(name="Action", value=action.name, inline=True)
        embed.set_footer(text=f"Removed by {interaction.user}")
        await interaction.response.send_message(embed=embed)

    # ── Remove temporary whitelist ─────────────────────────────────────────────

    @app_commands.command(name='untempwhitelist', description='Remove a user or bot\'s temporary whitelist early')
    @app_commands.describe(user_id='User/bot mention or ID to remove temp whitelist from')
    @is_owner_or_admin()
    async def untempwhitelist(self, interaction: discord.Interaction, user_id: str):
        user, err = await _resolve_user(interaction, user_id)
        if err:
            await interaction.response.send_message(embed=discord.Embed(description=err, color=0xff0000), ephemeral=True)
            return

        expiry = await self.bot.db.get_temp_whitelist_expiry(interaction.guild.id, user.id)
        if expiry is None:
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ No Active Temp Whitelist",
                description=f"<@{user.id}> has no active temporary whitelist.",
                color=0xffaa00), ephemeral=True)
            return

        await self.bot.db.remove_temp_whitelist(interaction.guild.id, user.id)
        await self.bot.db.log_whitelist_audit(
            interaction.guild.id, user.id, 'user',
            'temp_whitelist_remove',
            f'Removed temp whitelist for {user} ({user.id}) early',
            interaction.user.id
        )

        embed = discord.Embed(
            title="✅ Temporary Whitelist Removed",
            description=f"<@{user.id}>'s temporary whitelist has been revoked early.",
            color=0x00ff00
        )
        embed.add_field(name="User/Bot", value=f"<@{user.id}>\n`{user.id}`", inline=False)
        embed.set_footer(text=f"Removed by {interaction.user}")
        await interaction.response.send_message(embed=embed)

    # ── Remove role whitelist ──────────────────────────────────────────────────

    @app_commands.command(name='unwhitelistrole', description='Remove a role from the whitelist')
    @app_commands.describe(role='Role to remove from whitelist')
    @is_owner_or_admin()
    async def unwhitelistrole(self, interaction: discord.Interaction, role: discord.Role):
        existing = await self.bot.db.get_whitelist_roles(interaction.guild.id)
        if role.id not in existing:
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ Role Not Whitelisted",
                description=f"{role.mention} is not whitelisted.",
                color=0xffaa00), ephemeral=True)
            return

        await self.bot.db.remove_whitelist_role(interaction.guild.id, role.id)
        await self.bot.db.log_whitelist_audit(
            interaction.guild.id, role.id, 'role',
            'role_whitelist_remove',
            f'Removed whitelist for role @{role.name} ({role.id})',
            interaction.user.id
        )

        embed = discord.Embed(
            title="✅ Role Whitelist Removed",
            description=f"{role.mention} members are no longer exempt from anti-nuke protections.",
            color=0x00ff00
        )
        embed.add_field(name="Role", value=f"{role.mention}\n`{role.id}`", inline=False)
        embed.set_footer(text=f"Removed by {interaction.user}")
        await interaction.response.send_message(embed=embed)

    # ── Whitelist audit log ────────────────────────────────────────────────────

    @app_commands.command(name='whitelistaudit', description='View the whitelist change audit log')
    @is_owner_or_admin()
    async def whitelistaudit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        entries = await self.bot.db.get_whitelist_audit(interaction.guild.id, limit=15)

        if not entries:
            await interaction.followup.send(embed=discord.Embed(
                title="📋 Whitelist Audit Log",
                description="No whitelist changes have been recorded yet.",
                color=0x5865f2), ephemeral=True)
            return

        embed = discord.Embed(
            title="📋 Whitelist Audit Log",
            description=f"Last **{len(entries)}** whitelist changes",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )

        ACTION_EMOJI = {
            'global_whitelist_add':    '✅ Global Add',
            'global_whitelist_remove': '❌ Global Remove',
            'action_whitelist_add':    '✅ Action Add',
            'action_whitelist_remove': '❌ Action Remove',
            'temp_whitelist_add':      '⏰ Temp Add',
            'temp_whitelist_remove':   '⏰ Temp Remove',
            'role_whitelist_add':      '✅ Role Add',
            'role_whitelist_remove':   '❌ Role Remove',
        }

        for e in entries:
            label = ACTION_EMOJI.get(e['action_taken'], e['action_taken'])
            target_type = e['target_type']
            target_id = e['target_id']
            performed_by = e['performed_by']
            ts = e['timestamp']

            value = (
                f"**Target:** <@{'&' if target_type == 'role' else ''}{target_id}> `{target_id}`\n"
                f"**By:** <@{performed_by}>\n"
                f"**Details:** {e['details']}\n"
                f"**When:** <t:{ts}:R>"
            )
            embed.add_field(name=label, value=value, inline=False)

        embed.set_footer(text="VO AntiNuke • Whitelist Audit")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Unwhitelist(bot))
