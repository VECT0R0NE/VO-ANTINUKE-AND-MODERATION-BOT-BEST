import discord
from discord import app_commands
from discord.ext import commands


class ModerationLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="moderationlog", description="📜 Set the channel for bot moderation & anti-nuke action logs")
    @app_commands.describe(channel="The channel to send logs to")
    async def moderationlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer()
        if not (
            interaction.user.guild_permissions.administrator
            or interaction.user.id == interaction.guild.owner_id
            or await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        ):
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description="You need **Administrator** permission or be a bot admin to set the log channel.",
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        # Check bot can send to that channel
        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Missing Permissions",
                    description=f"I don't have permission to send messages in {channel.mention}.",
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        await self.bot.db.set_log_channel(interaction.guild.id, channel.id)

        embed = discord.Embed(
            title="📜 Moderation Log Channel Set",
            description=f"All bot moderation & anti-nuke actions will now be logged in {channel.mention}.",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="📌 Log Channel", value=channel.mention, inline=True)
        embed.add_field(name="👤 Set By", value=interaction.user.mention, inline=True)
        embed.add_field(
            name="📋 What Gets Logged",
            value=(
                "• Anti-Nuke Actions (bans, kicks, reverts)\n"
                "• Ban / Kick / Mute / Unmute / Softban\n"
                "• Mass Ban / Unban / Slowmode\n"
                "• Channel Lockdown / Unlockdown / Mass Lockdown\n"
                "• Warning Issues, Removals & Clears\n"
                "• History lookups\n"
                "• Jail / Unjail Actions"
            ),
            inline=False
        )
        embed.set_footer(text="VO AntiNuke • Configuration", icon_url=interaction.guild.me.display_avatar.url)

        await interaction.followup.send(embed=embed)

        # Send a test message to the log channel
        test_embed = discord.Embed(
            title="✅ Moderation Log Activated",
            description=f"This channel has been set as the moderation log channel by {interaction.user.mention}.\nAll future moderation actions will appear here.",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        test_embed.set_footer(text="VO AntiNuke • Moderation Log")
        await channel.send(embed=test_embed)


async def setup(bot):
    await bot.add_cog(ModerationLog(bot))