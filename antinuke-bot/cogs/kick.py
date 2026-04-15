import discord
from discord import app_commands
from discord.ext import commands


class Kick(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="kick", description="👢 Kick a member from the server")
    @app_commands.describe(
        user="The member to kick",
        reason="Reason for the kick"
    )
    async def kick(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "No reason provided"
    ):
        await interaction.response.defer()
        is_bot_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        has_perm = (
            interaction.user.guild_permissions.kick_members
            or interaction.user.id == interaction.guild.owner_id
            or is_bot_admin
        )
        if not has_perm:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description=(
                        "You need one of the following to use this command:\n"
                        "• **Kick Members** permission\n"
                        "• Server Owner\n"
                        "• Authorized bot admin (via `/addadmin`)"
                    ),
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        if user.id == interaction.user.id:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ You cannot kick yourself.", color=0xff0000),
                ephemeral=True
            )
            return

        if user.id == interaction.guild.owner_id:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ You cannot kick the server owner.", color=0xff0000),
                ephemeral=True
            )
            return

        bot_member = interaction.guild.get_member(self.bot.user.id)
        if user.top_role >= bot_member.top_role:
            await interaction.followup.send(
                embed=discord.Embed(
                    description="❌ I cannot kick this user — their role is higher than or equal to mine.",
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        if user.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send(
                embed=discord.Embed(
                    description="❌ You cannot kick someone with a higher or equal role.",
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        try:
            dm_embed = discord.Embed(
                title=f"👢 You have been kicked from {interaction.guild.name}",
                color=0xffa500,
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="Reason", value=reason, inline=False)
            dm_embed.add_field(name="Kicked By", value=str(interaction.user), inline=True)
            dm_embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
            await user.send(embed=dm_embed)
        except Exception:
            pass

        full_reason = f"{reason} | Kicked by {interaction.user} ({interaction.user.id})"
        await user.kick(reason=full_reason)

        embed = discord.Embed(
            title="👢 Member Kicked",
            color=0xffa500,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 Kicked User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="🛡️ Moderator", value=f"{interaction.user.mention}", inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="VO AntiNuke • Moderation", icon_url=interaction.guild.me.display_avatar.url)

        await interaction.followup.send(embed=embed)

        # Log to mod log
        log_channel_id = await self.bot.db.get_log_channel(interaction.guild.id)
        if log_channel_id:
            log_channel = interaction.guild.get_channel(log_channel_id)
            if log_channel:
                log_embed = discord.Embed(
                    title="👢 Moderation Action — Kick",
                    color=0xffa500,
                    timestamp=discord.utils.utcnow()
                )
                log_embed.add_field(name="Kicked User", value=f"{user} (`{user.id}`)", inline=True)
                log_embed.add_field(name="Moderator", value=f"{interaction.user.mention}", inline=True)
                log_embed.add_field(name="Reason", value=reason, inline=False)
                log_embed.set_thumbnail(url=user.display_avatar.url)
                log_embed.set_footer(text=f"User ID: {user.id}")
                await log_channel.send(embed=log_embed)

        # Anti-nuke: track kicks via this command against the moderator.
        protection = self.bot.get_cog('Protection')
        if protection:
            await protection.check_and_punish(
                interaction.guild,
                interaction.user,
                'kicking_members',
                f"Used /kick on {user}",
                {'kicked_user_id': user.id},
                responsible_user=interaction.user,
            )


async def setup(bot):
    await bot.add_cog(Kick(bot))
