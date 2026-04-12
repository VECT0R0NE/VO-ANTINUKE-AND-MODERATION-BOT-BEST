import discord
from discord import app_commands
from discord.ext import commands


class Ban(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ban", description="🔨 Ban a member from the server")
    @app_commands.describe(
        user="The member to ban",
        reason="Reason for the ban",
        delete_messages="How many days of messages to delete (0-7)"
    )
    @app_commands.choices(delete_messages=[
        app_commands.Choice(name="Don't delete any", value=0),
        app_commands.Choice(name="Last 24 hours", value=1),
        app_commands.Choice(name="Last 3 days", value=3),
        app_commands.Choice(name="Last 7 days", value=7),
    ])
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "No reason provided",
        delete_messages: int = 0
    ):
        is_bot_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        has_perm = (
            interaction.user.guild_permissions.ban_members
            or interaction.user.id == interaction.guild.owner_id
            or is_bot_admin
        )
        if not has_perm:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description=(
                        "You need one of the following to use this command:\n"
                        "• **Ban Members** permission\n"
                        "• Server Owner\n"
                        "• Authorized bot admin (via `/addadmin`)"
                    ),
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        if user.id == interaction.user.id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You cannot ban yourself.", color=0xff0000),
                ephemeral=True
            )
            return

        if user.id == interaction.guild.owner_id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You cannot ban the server owner.", color=0xff0000),
                ephemeral=True
            )
            return

        bot_member = interaction.guild.get_member(self.bot.user.id)
        if user.top_role >= bot_member.top_role:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ I cannot ban this user — their role is higher than or equal to mine.",
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        if user.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ You cannot ban someone with a higher or equal role.",
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        # DM the banned user before banning so they can receive it
        dm_sent = False
        try:
            dm_embed = discord.Embed(
                title="🔨 You Have Been Banned",
                description=(
                    f"You have been permanently banned from **{interaction.guild.name}**.\n"
                    f"If you believe this was a mistake, please contact the server staff."
                ),
                color=0xff0000,
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="🏠 Server", value=interaction.guild.name, inline=True)
            dm_embed.add_field(name="🛡️ Banned By", value=str(interaction.user), inline=True)
            dm_embed.add_field(name="📋 Reason", value=reason, inline=False)
            dm_embed.add_field(
                name="🗑️ Messages Deleted",
                value=f"Last {delete_messages} day(s)" if delete_messages else "None",
                inline=True
            )
            dm_embed.add_field(
                name="⏰ Time",
                value=f"<t:{int(discord.utils.utcnow().timestamp())}:F>",
                inline=True
            )
            dm_embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
            dm_embed.set_footer(
                text=f"Server ID: {interaction.guild.id}",
                icon_url=interaction.guild.icon.url if interaction.guild.icon else None
            )
            await user.send(embed=dm_embed)
            dm_sent = True
        except Exception:
            pass

        full_reason = f"{reason} | Banned by {interaction.user} ({interaction.user.id})"
        await interaction.guild.ban(user, reason=full_reason, delete_message_days=delete_messages)

        embed = discord.Embed(
            title="🔨 Member Banned",
            color=0xff4444,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 Banned User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="🛡️ Moderator", value=f"{interaction.user.mention}", inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.add_field(
            name="🗑️ Messages Deleted",
            value=f"Last {delete_messages} day(s)" if delete_messages else "None",
            inline=True
        )
        embed.add_field(name="📨 DM Sent", value="✅ Yes" if dm_sent else "❌ DMs closed", inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="VO AntiNuke • Moderation", icon_url=interaction.guild.me.display_avatar.url)

        await interaction.response.send_message(embed=embed)

        # Log to mod log
        log_channel_id = await self.bot.db.get_log_channel(interaction.guild.id)
        if log_channel_id:
            log_ch = interaction.guild.get_channel(log_channel_id)
            if log_ch:
                log_embed = discord.Embed(title="🔨 Moderation Action — Ban", color=0xff4444, timestamp=discord.utils.utcnow())
                log_embed.add_field(name="Banned User", value=f"{user} (`{user.id}`)", inline=True)
                log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
                log_embed.add_field(name="Reason", value=reason, inline=False)
                log_embed.add_field(name="Messages Deleted", value=f"{delete_messages} day(s)" if delete_messages else "None", inline=True)
                log_embed.set_thumbnail(url=user.display_avatar.url)
                log_embed.set_footer(text=f"User ID: {user.id}")
                await log_ch.send(embed=log_embed)

        # Anti-nuke: track bans issued via this command against the moderator.
        # If they hit the banning_members limit/timeframe they get punished.
        # Whitelisted users and the owner are skipped inside check_and_punish.
        protection = self.bot.get_cog('Protection')
        if protection:
            await protection.check_and_punish(
                interaction.guild,
                interaction.user,
                'banning_members',
                f"Used /ban on {user}",
                {'banned_user': user},
                responsible_user=interaction.user,
            )


async def setup(bot):
    await bot.add_cog(Ban(bot))
