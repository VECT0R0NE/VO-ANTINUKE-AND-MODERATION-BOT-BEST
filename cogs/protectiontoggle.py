import discord
from discord import app_commands
from discord.ext import commands
from utils.checks import is_owner_or_admin
from utils.helpers import ACTIONS

ACTION_CHOICES = [
    app_commands.Choice(name=a.replace('_', ' ').title(), value=a)
    for a in ACTIONS
]


class ProtectionToggle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='toggleprotection', description='Enable or disable a specific anti-nuke protection')
    @app_commands.describe(
        action='Which protection to toggle',
        enabled='True to enable, False to disable'
    )
    @app_commands.choices(action=ACTION_CHOICES)
    @is_owner_or_admin()
    async def toggleprotection(self, interaction: discord.Interaction,
                                action: app_commands.Choice[str], enabled: bool):
        await self.bot.db.set_protection_enabled(interaction.guild.id, action.value, enabled)

        status = "✅ Enabled" if enabled else "❌ Disabled"
        color = 0x00ff00 if enabled else 0xff4444

        embed = discord.Embed(
            title=f"🛡️ Protection {status}",
            description=f"**{action.name}** protection has been **{'enabled' if enabled else 'disabled'}**.",
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Action", value=action.name, inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.set_footer(text=f"Changed by {interaction.user} | VO AntiNuke")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(ProtectionToggle(bot))
