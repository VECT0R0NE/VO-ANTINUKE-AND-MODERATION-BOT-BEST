import discord
from discord import app_commands
from discord.ext import commands
from utils.checks import is_owner_only


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


class AddAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='addadmin', description='Add a user or bot as an admin who can modify anti-nuke settings')
    @app_commands.describe(user_id='User/bot mention or ID to add as admin')
    @is_owner_only()
    async def addadmin(self, interaction: discord.Interaction, user_id: str):
        user, err = await _resolve_user(interaction, user_id)
        if err:
            await interaction.response.send_message(embed=discord.Embed(description=err, color=0xff0000), ephemeral=True)
            return

        if user.id == interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ Already Admin",
                description="The server owner already has full admin permissions.",
                color=0xffaa00
            ), ephemeral=True)
            return

        if await self.bot.db.is_admin(interaction.guild.id, user.id):
            await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ Already Admin",
                description=f"<@{user.id}> is already an admin.",
                color=0xffaa00
            ), ephemeral=True)
            return

        await self.bot.db.add_admin(interaction.guild.id, user.id)

        is_bot = getattr(user, 'bot', False)
        embed = discord.Embed(
            title=f"✅ {'Bot' if is_bot else 'User'} Added as Admin",
            description=f"<@{user.id}> has been added as an admin and can now modify anti-nuke settings.",
            color=0x00ff00
        )
        embed.add_field(name="User/Bot", value=f"<@{user.id}>\n`{user.id}`", inline=True)
        embed.add_field(
            name="Permissions",
            value="• Set limits\n• Set timeframes\n• Set punishments\n• View configurations",
            inline=False
        )
        if is_bot:
            embed.add_field(name="⚠️ Note", value="This bot has been granted admin trust. Its actions will not be flagged by proxy detection.", inline=False)
        embed.set_footer(text=f"Added by {interaction.user}")

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(AddAdmin(bot))
