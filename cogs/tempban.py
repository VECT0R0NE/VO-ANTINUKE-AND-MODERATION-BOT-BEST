import discord
from discord import app_commands
from discord.ext import commands, tasks
from utils.helpers import parse_time, format_time
import time

BOT_NAME = "VO AntiNuke"


async def _send_log(bot, guild: discord.Guild, embed: discord.Embed):
    log_channel_id = await bot.db.get_log_channel(guild.id)
    if log_channel_id:
        ch = guild.get_channel(log_channel_id)
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass


class TempBan(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_temp_bans.start()

    def cog_unload(self):
        self.check_temp_bans.cancel()

    @tasks.loop(minutes=1)
    async def check_temp_bans(self):
        """Auto-unban users whose temp ban has expired."""
        try:
            expired = await self.bot.db.get_expired_temp_bans()
            for row in expired:
                guild = self.bot.get_guild(row['guild_id'])
                if not guild:
                    await self.bot.db.remove_temp_ban(row['guild_id'], row['user_id'])
                    continue
                try:
                    target = discord.Object(id=row['user_id'])
                    await guild.unban(target, reason=f"Temp ban expired | {BOT_NAME}")

                    log_embed = discord.Embed(
                        title="⏰ Temp Ban Expired — Auto Unban",
                        description=f"User `{row['user_id']}` was automatically unbanned.",
                        color=0x57f287,
                        timestamp=discord.utils.utcnow()
                    )
                    log_embed.add_field(name="User ID", value=str(row['user_id']), inline=True)
                    log_embed.add_field(name="Original Reason", value=row.get('reason', 'N/A'), inline=True)
                    log_embed.set_footer(text=f"{BOT_NAME} • Temp Ban System")
                    await _send_log(self.bot, guild, log_embed)

                except discord.NotFound:
                    pass  # Already unbanned
                except discord.Forbidden:
                    print(f"[TempBan] Cannot unban {row['user_id']} in {guild.id} — missing perms")
                except Exception as e:
                    print(f"[TempBan] Error unbanning {row['user_id']}: {e}")
                finally:
                    await self.bot.db.remove_temp_ban(row['guild_id'], row['user_id'])
        except Exception as e:
            print(f"[TempBan] Loop error: {e}")

    @check_temp_bans.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ── /tempban ──────────────────────────────────────────────────────────────

    @app_commands.command(name='tempban', description='🔨 Temporarily ban a member (auto-unbans after duration)')
    @app_commands.describe(
        user='Member to temp-ban',
        duration='Duration e.g. 1h, 2d, 1w',
        reason='Reason for the temp ban',
        delete_messages='How many days of messages to delete (0-7)'
    )
    @app_commands.choices(delete_messages=[
        app_commands.Choice(name="Don't delete any", value=0),
        app_commands.Choice(name="Last 24 hours", value=1),
        app_commands.Choice(name="Last 7 days", value=7),
    ])
    async def tempban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: str,
        reason: str = "No reason provided",
        delete_messages: int = 0
    ):
        is_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        has_perm = (
            interaction.user.guild_permissions.ban_members
            or interaction.user.id == interaction.guild.owner_id
            or is_admin
        )
        if not has_perm:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Ban Members** permission, be the server owner, or be an authorized bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        if user.id == interaction.user.id:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ You cannot temp-ban yourself.", color=0xff0000), ephemeral=True)
            return

        if user.id == interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ You cannot temp-ban the server owner.", color=0xff0000), ephemeral=True)
            return

        bot_member = interaction.guild.get_member(self.bot.user.id)
        if user.top_role >= bot_member.top_role:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ I cannot ban this user — their role is higher than or equal to mine.",
                color=0xff0000
            ), ephemeral=True)
            return

        if user.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ You cannot temp-ban someone with a higher or equal role.",
                color=0xff0000
            ), ephemeral=True)
            return

        seconds = parse_time(duration)
        if not seconds or seconds <= 0:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Invalid Duration",
                description="Use formats like `30m`, `2h`, `1d`, `1w`. Example: `/tempban @user 2h`",
                color=0xff0000
            ), ephemeral=True)
            return

        if seconds > 60 * 60 * 24 * 365:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Duration Too Long",
                description="Maximum temp ban is **1 year**.",
                color=0xff0000
            ), ephemeral=True)
            return

        expires_at = int(time.time()) + seconds

        # DM before ban
        dm_sent = False
        try:
            dm_embed = discord.Embed(
                title="🔨 You Have Been Temporarily Banned",
                description=(
                    f"You have been temporarily banned from **{interaction.guild.name}**.\n"
                    f"You will be automatically unbanned after **{format_time(seconds)}**."
                ),
                color=0xff4444,
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="🏠 Server", value=interaction.guild.name, inline=True)
            dm_embed.add_field(name="🛡️ Banned By", value=str(interaction.user), inline=True)
            dm_embed.add_field(name="⏱️ Duration", value=format_time(seconds), inline=True)
            dm_embed.add_field(name="📋 Reason", value=reason, inline=False)
            dm_embed.add_field(name="🔓 Unban Time", value=f"<t:{expires_at}:F>", inline=False)
            dm_embed.set_footer(text=f"{BOT_NAME} • Temp Ban")
            await user.send(embed=dm_embed)
            dm_sent = True
        except Exception:
            pass

        full_reason = f"{reason} | Temp banned for {format_time(seconds)} by {interaction.user} ({interaction.user.id})"
        await interaction.guild.ban(user, reason=full_reason, delete_message_days=delete_messages)
        await self.bot.db.add_temp_ban(interaction.guild.id, user.id, expires_at, reason, interaction.user.id)

        embed = discord.Embed(
            title="🔨 Member Temporarily Banned",
            color=0xff4444,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 Banned User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="⏱️ Duration", value=format_time(seconds), inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.add_field(name="🔓 Auto Unban", value=f"<t:{expires_at}:R>", inline=True)
        embed.add_field(name="📨 DM Sent", value="✅ Yes" if dm_sent else "❌ DMs closed", inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"{BOT_NAME} • Temp Ban System", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        log_embed = discord.Embed(
            title="🔨 Moderation Action — Temp Ban",
            color=0xff4444,
            timestamp=discord.utils.utcnow()
        )
        log_embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Duration", value=format_time(seconds), inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.add_field(name="Auto Unban", value=f"<t:{expires_at}:R>", inline=True)
        log_embed.add_field(name="DM Delivered", value="✅" if dm_sent else "❌", inline=True)
        log_embed.set_thumbnail(url=user.display_avatar.url)
        log_embed.set_footer(text=f"User ID: {user.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)

        # Anti-nuke: track temp bans via this command against the moderator.
        protection = self.bot.get_cog('Protection')
        if protection:
            await protection.check_and_punish(
                interaction.guild,
                interaction.user,
                'banning_members',
                f"Used /tempban on {user}",
                {'banned_user': user},
                responsible_user=interaction.user,
            )


async def setup(bot):
    await bot.add_cog(TempBan(bot))