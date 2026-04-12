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


class Whitelist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Global whitelist ──────────────────────────────────────────────────────

    @app_commands.command(name='whitelist', description='Whitelist a user or bot from ALL anti-nuke punishments')
    @app_commands.describe(user_id='User/bot mention or ID to whitelist globally')
    @is_owner_or_admin()
    async def whitelist(self, interaction: discord.Interaction, user_id: str):
        user, err = await _resolve_user(interaction, user_id)
        if err:
            await interaction.response.send_message(embed=discord.Embed(description=err, color=0xff0000), ephemeral=True)
            return

        if user.id == interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ Already Immune",
                description="The server owner is already immune to all punishments.",
                color=0xffaa00
            ), ephemeral=True)
            return

        if await self.bot.db.is_globally_whitelisted(interaction.guild.id, user.id):
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ Already Whitelisted",
                description=f"<@{user.id}> is already globally whitelisted.",
                color=0xffaa00
            ), ephemeral=True)
            return

        await self.bot.db.add_whitelist(interaction.guild.id, user.id)
        await self.bot.db.log_whitelist_audit(
            interaction.guild.id, user.id, 'user',
            'global_whitelist_add', f'Globally whitelisted {user} ({user.id})',
            interaction.user.id
        )

        is_bot = getattr(user, 'bot', False)
        embed = discord.Embed(
            title=f"✅ {'Bot' if is_bot else 'User'} Globally Whitelisted",
            description=f"<@{user.id}> is now immune to **all** anti-nuke punishments.",
            color=0x00ff00
        )
        embed.add_field(name="User/Bot", value=f"<@{user.id}>\n`{user.id}`", inline=True)
        if is_bot:
            embed.add_field(name="⚠️ Note", value="This bot's actions will no longer be tracked. Make sure you trust it.", inline=False)
        embed.set_thumbnail(url=user.display_avatar.url if hasattr(user, 'display_avatar') else user.avatar.url if user.avatar else None)
        embed.set_footer(text=f"Whitelisted by {interaction.user}")
        await interaction.response.send_message(embed=embed)

    # ── Per-action whitelist ───────────────────────────────────────────────────

    @app_commands.command(name='whitelistaction', description='Whitelist a user or bot for a specific anti-nuke action only')
    @app_commands.describe(
        user_id='User/bot mention or ID to whitelist',
        action='The specific action to whitelist them for'
    )
    @app_commands.choices(action=ACTION_CHOICES)
    @is_owner_or_admin()
    async def whitelistaction(self, interaction: discord.Interaction,
                               user_id: str, action: app_commands.Choice[str]):
        user, err = await _resolve_user(interaction, user_id)
        if err:
            await interaction.response.send_message(embed=discord.Embed(description=err, color=0xff0000), ephemeral=True)
            return

        if user.id == interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ Already Immune", description="The server owner is already immune.",
                color=0xffaa00), ephemeral=True)
            return

        already = await self.bot.db.is_action_whitelisted(interaction.guild.id, user.id, action.value)
        if already:
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ Already Whitelisted",
                description=f"<@{user.id}> is already whitelisted for **{action.name}**.",
                color=0xffaa00), ephemeral=True)
            return

        await self.bot.db.add_whitelist_action(interaction.guild.id, user.id, action.value)
        await self.bot.db.log_whitelist_audit(
            interaction.guild.id, user.id, 'user',
            'action_whitelist_add',
            f'Whitelisted {user} ({user.id}) for action: {action.value}',
            interaction.user.id
        )

        embed = discord.Embed(
            title="✅ Per-Action Whitelist Added",
            description=f"<@{user.id}> is now exempt from **{action.name}** protection only.",
            color=0x00ff00
        )
        embed.add_field(name="User/Bot", value=f"<@{user.id}>\n`{user.id}`", inline=True)
        embed.add_field(name="Exempt Action", value=action.name, inline=True)
        embed.set_footer(text=f"Set by {interaction.user}")
        await interaction.response.send_message(embed=embed)

    # ── Temporary whitelist ────────────────────────────────────────────────────

    @app_commands.command(name='tempwhitelist', description='Temporarily whitelist a user or bot (auto-expires)')
    @app_commands.describe(
        user_id='User/bot mention or ID to whitelist',
        duration='Duration e.g. 30m, 2h, 1d'
    )
    @is_owner_or_admin()
    async def tempwhitelist(self, interaction: discord.Interaction,
                             user_id: str, duration: str):
        from utils.helpers import parse_time, format_time
        import time

        user, err = await _resolve_user(interaction, user_id)
        if err:
            await interaction.response.send_message(embed=discord.Embed(description=err, color=0xff0000), ephemeral=True)
            return

        seconds = parse_time(duration)
        if not seconds or seconds <= 0:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Invalid Duration",
                description="Use formats like `30m`, `2h`, `1d`. Example: `/tempwhitelist 123456789 2h`",
                color=0xff0000), ephemeral=True)
            return

        if seconds > 60 * 60 * 24 * 30:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Duration Too Long",
                description="Maximum temporary whitelist duration is **30 days**.",
                color=0xff0000), ephemeral=True)
            return

        if user.id == interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ Already Immune", description="The server owner is already immune.",
                color=0xffaa00), ephemeral=True)
            return

        expires_at = int(time.time()) + seconds
        await self.bot.db.add_temp_whitelist(interaction.guild.id, user.id, expires_at)
        await self.bot.db.log_whitelist_audit(
            interaction.guild.id, user.id, 'user',
            'temp_whitelist_add',
            f'Temp whitelisted {user} ({user.id}) for {format_time(seconds)} (expires <t:{expires_at}:R>)',
            interaction.user.id
        )

        embed = discord.Embed(
            title="✅ Temporary Whitelist Added",
            description=f"<@{user.id}> is temporarily whitelisted for **{format_time(seconds)}**.",
            color=0x00ff00
        )
        embed.add_field(name="User/Bot", value=f"<@{user.id}>\n`{user.id}`", inline=True)
        embed.add_field(name="Duration", value=format_time(seconds), inline=True)
        embed.add_field(name="Expires", value=f"<t:{expires_at}:R>", inline=True)
        embed.set_footer(text=f"Set by {interaction.user}")
        await interaction.response.send_message(embed=embed)

    # ── Role whitelist ─────────────────────────────────────────────────────────

    @app_commands.command(name='whitelistrole', description='Whitelist all members of a role from anti-nuke punishments')
    @app_commands.describe(role='Role to whitelist')
    @is_owner_or_admin()
    async def whitelistrole(self, interaction: discord.Interaction, role: discord.Role):
        if role == interaction.guild.default_role:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Invalid Role",
                description="You cannot whitelist the `@everyone` role.",
                color=0xff0000), ephemeral=True)
            return

        existing = await self.bot.db.get_whitelist_roles(interaction.guild.id)
        if role.id in existing:
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ Already Whitelisted",
                description=f"{role.mention} is already whitelisted.",
                color=0xffaa00), ephemeral=True)
            return

        await self.bot.db.add_whitelist_role(interaction.guild.id, role.id)
        await self.bot.db.log_whitelist_audit(
            interaction.guild.id, role.id, 'role',
            'role_whitelist_add',
            f'Whitelisted role @{role.name} ({role.id}) — {len(role.members)} members affected',
            interaction.user.id
        )

        embed = discord.Embed(
            title="✅ Role Whitelisted",
            description=f"All members with {role.mention} are now exempt from anti-nuke punishments.",
            color=0x00ff00
        )
        embed.add_field(name="Role", value=f"{role.mention}\n`{role.id}`", inline=True)
        embed.add_field(name="Members Affected", value=str(len(role.members)), inline=True)
        embed.set_footer(text=f"Set by {interaction.user}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Whitelist(bot))
