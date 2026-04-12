import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import time as _time


BOT_NAME = "VO AntiNuke"


def _perm_check(interaction: discord.Interaction) -> bool:
    """Returns True if the user has Manage Messages OR is server owner OR is a bot admin."""
    return (
        interaction.user.guild_permissions.manage_messages
        or interaction.user.id == interaction.guild.owner_id
    )


class Warn(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── /warn ────────────────────────────────────────────────────

    @app_commands.command(name="warn", description="⚠️ Issue a warning to a member")
    @app_commands.describe(user="The member to warn", reason="Reason for the warning")
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):

        # Permission check — Manage Messages, server owner, or bot admin
        is_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not _perm_check(interaction) and not is_admin:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description=(
                        "You need one of the following to use this command:\n"
                        "• **Manage Messages** permission\n"
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
                embed=discord.Embed(description="❌ You cannot warn yourself.", color=0xff0000),
                ephemeral=True
            )
            return

        if user.bot:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You cannot warn bots.", color=0xff0000),
                ephemeral=True
            )
            return

        warn_id = await self.bot.warns_db.add_warn(
            interaction.guild.id, user.id, interaction.user.id, reason
        )
        warn_count = await self.bot.warns_db.get_warn_count(interaction.guild.id, user.id)
        issued_at = int(_time.time())

        # ── Rich DM to the warned user ────────────────────────────
        dm_sent = False
        try:
            dm_embed = discord.Embed(
                title="⚠️  You Have Received a Warning",
                description=(
                    f"A moderator has issued a formal warning against you in **{interaction.guild.name}**.\n"
                    f"Please review the reason below and ensure you follow the server rules going forward."
                ),
                color=0xffcc00,
                timestamp=discord.utils.utcnow()
            )

            # Server info
            dm_embed.add_field(
                name="🏠 Server",
                value=f"{interaction.guild.name}\n`ID: {interaction.guild.id}`",
                inline=True
            )
            dm_embed.add_field(
                name="👤 Member Count",
                value=f"{interaction.guild.member_count:,} members",
                inline=True
            )
            dm_embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

            # Warning info
            dm_embed.add_field(
                name="🛡️ Warned By",
                value=f"{interaction.user}\n`ID: {interaction.user.id}`",
                inline=True
            )
            dm_embed.add_field(
                name="🆔 Warning ID",
                value=f"`#{warn_id}`",
                inline=True
            )
            dm_embed.add_field(
                name="📊 Your Total Warnings",
                value=f"**{warn_count}** warning(s) on record",
                inline=True
            )

            # Reason — full width
            dm_embed.add_field(
                name="📋 Reason",
                value=f"```{reason}```",
                inline=False
            )

            # Time info
            dm_embed.add_field(
                name="⏰ Issued At",
                value=f"<t:{issued_at}:F> (<t:{issued_at}:R>)",
                inline=False
            )

            # Warning level indicator
            if warn_count == 1:
                level_text = "🟡 **First Warning** — Please be more careful."
            elif warn_count == 2:
                level_text = "🟠 **Second Warning** — Further violations may result in a mute or kick."
            elif warn_count == 3:
                level_text = "🔴 **Third Warning** — You are at serious risk of being kicked or banned."
            else:
                level_text = f"🚨 **Warning #{warn_count}** — You are at extreme risk of severe punishment."

            dm_embed.add_field(name="⚡ Warning Level", value=level_text, inline=False)

            dm_embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
            dm_embed.set_author(
                name=f"{BOT_NAME} — {interaction.guild.name}",
                icon_url=interaction.guild.icon.url if interaction.guild.icon else None
            )
            dm_embed.set_footer(
                text=f"Warning ID: #{warn_id} • {BOT_NAME}",
                icon_url=self.bot.user.display_avatar.url
            )

            await user.send(embed=dm_embed)
            dm_sent = True
        except Exception:
            pass

        # ── Response in server ────────────────────────────────────
        embed = discord.Embed(
            title="⚠️ Member Warned",
            color=0xffcc00,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 Warned User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="🛡️ Moderator", value=f"{interaction.user.mention}", inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.add_field(name="📊 Total Warnings", value=f"**{warn_count}** warning(s)", inline=True)
        embed.add_field(name="🆔 Warning ID", value=f"`#{warn_id}`", inline=True)
        embed.add_field(name="📨 DM Sent", value="✅ Yes" if dm_sent else "❌ DMs closed", inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        # ── Log ───────────────────────────────────────────────────
        log_channel_id = await self.bot.db.get_log_channel(interaction.guild.id)
        if log_channel_id:
            log_ch = interaction.guild.get_channel(log_channel_id)
            if log_ch:
                log_embed = discord.Embed(
                    title="⚠️ Moderation Action — Warn",
                    color=0xffcc00,
                    timestamp=discord.utils.utcnow()
                )
                log_embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
                log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
                log_embed.add_field(name="Reason", value=reason, inline=False)
                log_embed.add_field(name="Total Warnings", value=str(warn_count), inline=True)
                log_embed.add_field(name="Warning ID", value=f"#{warn_id}", inline=True)
                log_embed.add_field(name="DM Delivered", value="✅" if dm_sent else "❌", inline=True)
                log_embed.set_thumbnail(url=user.display_avatar.url)
                log_embed.set_footer(text=f"User ID: {user.id} • {BOT_NAME}")
                await log_ch.send(embed=log_embed)

    # ─── /warnings ────────────────────────────────────────────────

    @app_commands.command(name="warnings", description="📋 View all warnings for a member")
    @app_commands.describe(user="The member to view warnings for")
    async def warnings(self, interaction: discord.Interaction, user: discord.Member):
        is_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not _perm_check(interaction) and not is_admin:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description="You need **Manage Messages** permission, be the server owner, or be an authorized bot admin.",
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        warns = await self.bot.warns_db.get_warns(interaction.guild.id, user.id)

        if not warns:
            embed = discord.Embed(
                title=f"📋 Warnings — {user.display_name}",
                description="✅ This user has no warnings on record.",
                color=0x57f287,
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
            await interaction.response.send_message(embed=embed)
            return

        embed = discord.Embed(
            title=f"📋 Warnings — {user.display_name}",
            description=f"**{len(warns)}** warning(s) on record",
            color=0xffcc00,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        for warn_id, moderator_id, reason, timestamp in warns[:10]:
            mod = interaction.guild.get_member(moderator_id)
            mod_str = str(mod) if mod else f"Unknown (`{moderator_id}`)"
            dt = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M UTC")
            embed.add_field(
                name=f"#{warn_id} — {dt}",
                value=f"**Reason:** {reason}\n**By:** {mod_str}",
                inline=False
            )

        footer_text = f"Showing 10/{len(warns)} warnings • {BOT_NAME}" if len(warns) > 10 else f"{BOT_NAME} • Moderation"
        embed.set_footer(text=footer_text, icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ─── /removewarn ──────────────────────────────────────────────

    @app_commands.command(name="removewarn", description="🗑️ Remove a specific warning by ID")
    @app_commands.describe(warn_id="The warning ID to remove")
    async def removewarn(self, interaction: discord.Interaction, warn_id: int):
        is_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not _perm_check(interaction) and not is_admin:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description="You need **Manage Messages** permission, be the server owner, or be an authorized bot admin.",
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        warn = await self.bot.warns_db.get_warn_by_id(interaction.guild.id, warn_id)
        if not warn:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Not Found",
                    description=f"No warning found with ID `#{warn_id}` in this server.",
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        user_id, reason = warn
        await self.bot.warns_db.remove_warn(interaction.guild.id, warn_id)

        user = interaction.guild.get_member(user_id)
        user_str = user.mention if user else f"Unknown (`{user_id}`)"

        embed = discord.Embed(title="🗑️ Warning Removed", color=0x57f287, timestamp=discord.utils.utcnow())
        embed.add_field(name="Warning ID", value=f"`#{warn_id}`", inline=True)
        embed.add_field(name="User", value=user_str, inline=True)
        embed.add_field(name="Original Reason", value=reason, inline=False)
        embed.add_field(name="Removed By", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        # Log to mod log
        log_channel_id = await self.bot.db.get_log_channel(interaction.guild.id)
        if log_channel_id:
            log_ch = interaction.guild.get_channel(log_channel_id)
            if log_ch:
                log_embed = discord.Embed(
                    title="🗑️ Moderation Action — Remove Warning",
                    color=0x57f287,
                    timestamp=discord.utils.utcnow()
                )
                log_embed.add_field(name="Warning ID", value=f"#{warn_id}", inline=True)
                log_embed.add_field(name="User", value=user_str, inline=True)
                log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
                log_embed.add_field(name="Original Reason", value=reason, inline=False)
                log_embed.set_footer(text=f"User ID: {user_id} • {BOT_NAME}")
                await log_ch.send(embed=log_embed)

    # ─── /clearwarns ──────────────────────────────────────────────

    @app_commands.command(name="clearwarns", description="🧹 Clear ALL warnings for a member")
    @app_commands.describe(user="The member to clear all warnings for")
    async def clearwarns(self, interaction: discord.Interaction, user: discord.Member):
        is_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not _perm_check(interaction) and not is_admin:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description="You need **Manage Messages** permission, be the server owner, or be an authorized bot admin.",
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        count = await self.bot.warns_db.get_warn_count(interaction.guild.id, user.id)
        if count == 0:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"ℹ️ {user.mention} has no warnings to clear.", color=0x5865f2),
                ephemeral=True
            )
            return

        await self.bot.warns_db.clear_warns(interaction.guild.id, user.id)

        embed = discord.Embed(
            title="🧹 Warnings Cleared",
            description=f"All **{count}** warning(s) for {user.mention} have been removed.",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="Cleared By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Warnings Removed", value=str(count), inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        # Log to mod log
        log_channel_id = await self.bot.db.get_log_channel(interaction.guild.id)
        if log_channel_id:
            log_ch = interaction.guild.get_channel(log_channel_id)
            if log_ch:
                log_embed = discord.Embed(
                    title="🧹 Moderation Action — Clear Warnings",
                    color=0x57f287,
                    timestamp=discord.utils.utcnow()
                )
                log_embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
                log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
                log_embed.add_field(name="Warnings Cleared", value=str(count), inline=True)
                log_embed.set_thumbnail(url=user.display_avatar.url)
                log_embed.set_footer(text=f"User ID: {user.id} • {BOT_NAME}")
                await log_ch.send(embed=log_embed)


async def setup(bot):
    await bot.add_cog(Warn(bot))