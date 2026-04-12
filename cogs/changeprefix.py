import discord
from discord import app_commands
from discord.ext import commands


class ChangePrefix(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="changeprefix", description="🔧 Change the bot's command prefix for this server")
    @app_commands.describe(prefix="The new prefix to use (e.g. !, ?, ., >)")
    async def changeprefix(self, interaction: discord.Interaction, prefix: str):
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description="Only the **server owner** can change the command prefix.",
                    color=0xff0000
                ), ephemeral=True
            )
            return

        if len(prefix) > 5:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Invalid Prefix",
                    description="The prefix must be **5 characters or fewer**.",
                    color=0xff0000
                ), ephemeral=True
            )
            return

        if " " in prefix:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Invalid Prefix",
                    description="The prefix cannot contain spaces.",
                    color=0xff0000
                ), ephemeral=True
            )
            return

        # Fix: always read the stored prefix; fall back to literal "!" not the function
        old_prefix = await self.bot.db.get_prefix(interaction.guild.id) or "!"
        await self.bot.db.set_prefix(interaction.guild.id, prefix)

        embed = discord.Embed(
            title="✅ Prefix Updated",
            description="The command prefix for this server has been changed.",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Old Prefix", value=f"`{old_prefix}`", inline=True)
        embed.add_field(name="New Prefix", value=f"`{prefix}`", inline=True)
        embed.add_field(
            name="ℹ️ Note",
            value=f"Prefix commands now use `{prefix}`. Slash commands `/` are unaffected.",
            inline=False
        )
        embed.set_footer(
            text=f"Changed by {interaction.user} • VO AntiNuke",
            icon_url=interaction.guild.me.display_avatar.url
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(ChangePrefix(bot))
