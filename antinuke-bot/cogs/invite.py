import discord
from discord import app_commands
from discord.ext import commands


class Invite(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="invite", description="🔗 Get the bot's invite link")
    async def invite(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # Administrator permission value = 8
        invite_url = discord.utils.oauth_url(
            self.bot.user.id,
            permissions=discord.Permissions(administrator=True),
            scopes=("bot", "applications.commands")
        )

        embed = discord.Embed(
            title="🔗 Invite VO AntiNuke",
            description=(
                "Click the button below to add the bot to your server.\n\n"
                "**The bot requires Administrator permission** to:\n"
                "```\n"
                "• Monitor and reverse nuke attacks\n"
                "• Manage roles for the jail system\n"
                "• Ban/kick malicious users automatically\n"
                "• Restore deleted channels and roles\n"
                "• Access audit logs for threat detection\n"
                "```"
            ),
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="🔒 Required Permission", value="Administrator", inline=True)
        embed.add_field(name="📦 Slash Commands", value="Included", inline=True)
        embed.set_footer(text="VO AntiNuke", icon_url=self.bot.user.display_avatar.url)

        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="➕ Add to Server",
            style=discord.ButtonStyle.link,
            url=invite_url,
            emoji="🔗"
        ))

        await interaction.followup.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Invite(bot))