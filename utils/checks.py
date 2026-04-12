import discord
from discord import app_commands


def is_owner_or_admin():
    """Server owner OR bot admins added via /addadmin can use this command."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ Server Only",
                                    description="This command can only be used in a server.",
                                    color=0xff0000),
                ephemeral=True)
            return False

        if interaction.guild.owner_id == interaction.user.id:
            return True

        if await interaction.client.db.is_admin(interaction.guild.id, interaction.user.id):
            return True

        await interaction.response.send_message(
            embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the **server owner** or an authorized admin (via `/addadmin`) can use this command.",
                color=0xff0000
            ),
            ephemeral=True
        )
        return False

    return app_commands.check(predicate)


def is_owner_only():
    """Only the server owner can use this command."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ Server Only",
                                    description="This command can only be used in a server.",
                                    color=0xff0000),
                ephemeral=True)
            return False

        if interaction.guild.owner_id == interaction.user.id:
            return True

        await interaction.response.send_message(
            embed=discord.Embed(
                title="❌ Owner Only",
                description="Only the **server owner** can use this command.",
                color=0xff0000
            ),
            ephemeral=True
        )
        return False

    return app_commands.check(predicate)
