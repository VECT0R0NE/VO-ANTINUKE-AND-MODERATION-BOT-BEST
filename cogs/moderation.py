import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import parse_time, format_time
import time
import asyncio

BOT_NAME = "VO AntiNuke"


def _has_mod_perms(interaction: discord.Interaction, perm: str = "manage_messages") -> bool:
    return (
        getattr(interaction.user.guild_permissions, perm, False)
        or interaction.user.id == interaction.guild.owner_id
    )


async def _is_admin(bot, guild_id, user_id):
    return await bot.db.is_admin(guild_id, user_id)


async def _send_log(bot, guild, embed):
    log_channel_id = await bot.db.get_log_channel(guild.id)
    if log_channel_id:
        ch = guild.get_channel(log_channel_id)
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
#  LOCKDOWN CONFIRMATION VIEW
# ─────────────────────────────────────────────────────────────────────────────

class LockdownConfirmView(discord.ui.View):
    def __init__(self, author: discord.Member, mode: str):
        super().__init__(timeout=30)
        self.author = author
        self.mode = mode  # "lock" or "unlock"
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only the command invoker can confirm this.", color=0xff0000),
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="✅  Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⏳ Processing...",
                description=f"{'Locking' if self.mode == 'lock' else 'Unlocking'} all channels, please wait...",
                color=0xffaa00
            ),
            view=self
        )

    @discord.ui.button(label="❌  Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(title="❌ Cancelled", description="No changes were made.", color=0x5865f2),
            view=self
        )


# ─────────────────────────────────────────────────────────────────────────────
#  MASS BAN CONFIRM VIEW
# ─────────────────────────────────────────────────────────────────────────────

class MassBanConfirmView(discord.ui.View):
    def __init__(self, author: discord.Member, count: int):
        super().__init__(timeout=30)
        self.author = author
        self.count = count
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only the command invoker can confirm.", color=0xff0000),
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="✅  Confirm Mass Ban", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⏳ Banning...",
                description=f"Processing **{self.count}** ban(s)...",
                color=0xffaa00
            ),
            view=self
        )

    @discord.ui.button(label="❌  Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(title="❌ Cancelled", description="No bans were issued.", color=0x5865f2),
            view=self
        )


# ─────────────────────────────────────────────────────────────────────────────
#  MODERATION COG
# ─────────────────────────────────────────────────────────────────────────────

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Store lockdown channel overwrites: guild_id -> {channel_id -> {target_id -> overwrite}}
        self._lockdown_backups: dict[int, dict] = {}

    # ────────────────────────── /mute ────────────────────────────

    @app_commands.command(name="mute", description="🔇 Timeout (mute) a member for a duration")
    @app_commands.describe(
        user="Member to mute",
        duration="Duration e.g. 10m, 1h, 1d (max 28 days)",
        reason="Reason for the mute"
    )
    async def mute(self, interaction: discord.Interaction, user: discord.Member,
                   duration: str, reason: str = "No reason provided"):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (_has_mod_perms(interaction, "moderate_members") or is_admin):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Moderate Members** permission, be the server owner, or be an authorized bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        if user.id == interaction.user.id:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ You cannot mute yourself.", color=0xff0000), ephemeral=True)
            return

        if user.id == interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ You cannot mute the server owner.", color=0xff0000), ephemeral=True)
            return

        bot_member = interaction.guild.get_member(self.bot.user.id)
        if user.top_role >= bot_member.top_role:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ I cannot mute this user — their role is higher than or equal to mine.", color=0xff0000
            ), ephemeral=True)
            return

        if user.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ You cannot mute someone with a higher or equal role.", color=0xff0000
            ), ephemeral=True)
            return

        seconds = parse_time(duration)
        if not seconds or seconds <= 0:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Invalid Duration",
                description="Use formats like `10m`, `1h`, `12h`, `1d`. Example: `/mute @user 1h`",
                color=0xff0000
            ), ephemeral=True)
            return

        max_timeout = 28 * 24 * 3600  # Discord's limit
        if seconds > max_timeout:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Duration Too Long",
                description="Maximum mute duration is **28 days** (Discord limit).",
                color=0xff0000
            ), ephemeral=True)
            return

        until = discord.utils.utcnow() + discord.utils.timedelta(seconds=seconds)

        dm_sent = False
        try:
            dm_embed = discord.Embed(
                title="🔇 You Have Been Muted",
                description=f"You have been timed out in **{interaction.guild.name}**.",
                color=0xff6600,
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="🏠 Server", value=interaction.guild.name, inline=True)
            dm_embed.add_field(name="🛡️ Muted By", value=str(interaction.user), inline=True)
            dm_embed.add_field(name="⏱️ Duration", value=format_time(seconds), inline=True)
            dm_embed.add_field(name="📋 Reason", value=reason, inline=False)
            dm_embed.add_field(name="⏰ Expires", value=f"<t:{int(until.timestamp())}:R>", inline=True)
            dm_embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
            dm_embed.set_footer(text=f"{BOT_NAME} • Moderation")
            await user.send(embed=dm_embed)
            dm_sent = True
        except Exception:
            pass

        await user.timeout(until, reason=f"{reason} | Muted by {interaction.user} ({interaction.user.id})")

        embed = discord.Embed(title="🔇 Member Muted", color=0xff6600, timestamp=discord.utils.utcnow())
        embed.add_field(name="👤 Muted User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="⏱️ Duration", value=format_time(seconds), inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.add_field(name="⏰ Expires", value=f"<t:{int(until.timestamp())}:R>", inline=True)
        embed.add_field(name="📨 DM Sent", value="✅ Yes" if dm_sent else "❌ DMs closed", inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        log_embed = discord.Embed(title="🔇 Moderation Action — Mute", color=0xff6600, timestamp=discord.utils.utcnow())
        log_embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Duration", value=format_time(seconds), inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.add_field(name="Expires", value=f"<t:{int(until.timestamp())}:R>", inline=True)
        log_embed.add_field(name="DM Delivered", value="✅" if dm_sent else "❌", inline=True)
        log_embed.set_thumbnail(url=user.display_avatar.url)
        log_embed.set_footer(text=f"User ID: {user.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)

        # Anti-nuke: track timeouts/mutes issued via this command
        protection = self.bot.get_cog('Protection')
        if protection:
            await protection.check_and_punish(
                interaction.guild,
                interaction.user,
                'timing_out_members',
                f"Used /mute on {user}",
                {'member': user},
                responsible_user=interaction.user,
            )

    # ────────────────────────── /unmute ──────────────────────────

    @app_commands.command(name="unmute", description="🔊 Remove timeout (unmute) from a member")
    @app_commands.describe(user="Member to unmute", reason="Reason for unmuting")
    async def unmute(self, interaction: discord.Interaction, user: discord.Member,
                     reason: str = "No reason provided"):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (_has_mod_perms(interaction, "moderate_members") or is_admin):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Moderate Members** permission, be the server owner, or be an authorized bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        if not user.is_timed_out():
            await interaction.response.send_message(embed=discord.Embed(
                description=f"ℹ️ {user.mention} is not currently muted.",
                color=0x5865f2
            ), ephemeral=True)
            return

        await user.timeout(None, reason=f"{reason} | Unmuted by {interaction.user} ({interaction.user.id})")

        dm_sent = False
        try:
            dm_embed = discord.Embed(
                title="🔊 You Have Been Unmuted",
                description=f"Your timeout in **{interaction.guild.name}** has been removed.",
                color=0x57f287,
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="🏠 Server", value=interaction.guild.name, inline=True)
            dm_embed.add_field(name="🛡️ Unmuted By", value=str(interaction.user), inline=True)
            dm_embed.add_field(name="📋 Reason", value=reason, inline=False)
            dm_embed.set_footer(text=f"{BOT_NAME} • Moderation")
            await user.send(embed=dm_embed)
            dm_sent = True
        except Exception:
            pass

        embed = discord.Embed(title="🔊 Member Unmuted", color=0x57f287, timestamp=discord.utils.utcnow())
        embed.add_field(name="👤 User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.add_field(name="📨 DM Sent", value="✅ Yes" if dm_sent else "❌ DMs closed", inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        log_embed = discord.Embed(title="🔊 Moderation Action — Unmute", color=0x57f287, timestamp=discord.utils.utcnow())
        log_embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.add_field(name="DM Delivered", value="✅" if dm_sent else "❌", inline=True)
        log_embed.set_thumbnail(url=user.display_avatar.url)
        log_embed.set_footer(text=f"User ID: {user.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)

    # ────────────────────────── /softban ─────────────────────────

    @app_commands.command(name="softban", description="🔨 Softban a member (ban + immediate unban to purge messages)")
    @app_commands.describe(
        user="Member to softban",
        reason="Reason for the softban",
        delete_days="Days of messages to delete (1-7)"
    )
    @app_commands.choices(delete_days=[
        app_commands.Choice(name="Last 24 hours", value=1),
        app_commands.Choice(name="Last 3 days", value=3),
        app_commands.Choice(name="Last 7 days", value=7),
    ])
    async def softban(self, interaction: discord.Interaction, user: discord.Member,
                      reason: str = "No reason provided", delete_days: int = 1):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        has_perm = interaction.user.guild_permissions.ban_members or interaction.user.id == interaction.guild.owner_id or is_admin
        if not has_perm:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Ban Members** permission, be the server owner, or be an authorized bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        if user.id == interaction.user.id:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ You cannot softban yourself.", color=0xff0000), ephemeral=True)
            return

        if user.id == interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ You cannot softban the server owner.", color=0xff0000), ephemeral=True)
            return

        bot_member = interaction.guild.get_member(self.bot.user.id)
        if user.top_role >= bot_member.top_role:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ I cannot softban this user — their role is higher than or equal to mine.", color=0xff0000
            ), ephemeral=True)
            return

        if user.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ You cannot softban someone with a higher or equal role.", color=0xff0000
            ), ephemeral=True)
            return

        dm_sent = False
        try:
            dm_embed = discord.Embed(
                title="🔨 You Have Been Softbanned",
                description=(
                    f"You were softbanned from **{interaction.guild.name}**.\n"
                    "A softban removes your recent messages but you are **not** permanently banned — you may rejoin with an invite."
                ),
                color=0xff8800,
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="🏠 Server", value=interaction.guild.name, inline=True)
            dm_embed.add_field(name="🛡️ Moderator", value=str(interaction.user), inline=True)
            dm_embed.add_field(name="📋 Reason", value=reason, inline=False)
            dm_embed.add_field(name="🗑️ Messages Deleted", value=f"Last {delete_days} day(s)", inline=True)
            dm_embed.set_footer(text=f"{BOT_NAME} • Moderation")
            await user.send(embed=dm_embed)
            dm_sent = True
        except Exception:
            pass

        full_reason = f"{reason} | Softbanned by {interaction.user} ({interaction.user.id})"
        await interaction.guild.ban(user, reason=full_reason, delete_message_days=delete_days)
        await interaction.guild.unban(user, reason="Softban — automatic immediate unban")

        embed = discord.Embed(title="🔨 Member Softbanned", color=0xff8800, timestamp=discord.utils.utcnow())
        embed.add_field(name="👤 User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.add_field(name="🗑️ Messages Deleted", value=f"Last {delete_days} day(s)", inline=True)
        embed.add_field(name="📨 DM Sent", value="✅ Yes" if dm_sent else "❌ DMs closed", inline=True)
        embed.add_field(name="ℹ️ Note", value="User was banned and immediately unbanned. They may rejoin.", inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        log_embed = discord.Embed(title="🔨 Moderation Action — Softban", color=0xff8800, timestamp=discord.utils.utcnow())
        log_embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.add_field(name="Messages Deleted", value=f"{delete_days} day(s)", inline=True)
        log_embed.add_field(name="DM Delivered", value="✅" if dm_sent else "❌", inline=True)
        log_embed.set_thumbnail(url=user.display_avatar.url)
        log_embed.set_footer(text=f"User ID: {user.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)

        # Anti-nuke: softban still counts as a ban action
        protection = self.bot.get_cog('Protection')
        if protection:
            await protection.check_and_punish(
                interaction.guild,
                interaction.user,
                'banning_members',
                f"Used /softban on {user}",
                {'banned_user': user},
                responsible_user=interaction.user,
            )

    # ────────────────────────── /massban ─────────────────────────

    @app_commands.command(name="massban", description="🔨 Ban multiple users by ID (space-separated)")
    @app_commands.describe(
        user_ids="Space-separated list of user IDs to ban",
        reason="Reason for the mass ban",
        delete_days="Days of messages to delete (0-7)"
    )
    @app_commands.choices(delete_days=[
        app_commands.Choice(name="Don't delete any", value=0),
        app_commands.Choice(name="Last 24 hours", value=1),
        app_commands.Choice(name="Last 7 days", value=7),
    ])
    async def massban(self, interaction: discord.Interaction, user_ids: str,
                      reason: str = "Mass ban", delete_days: int = 0):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        has_perm = interaction.user.guild_permissions.ban_members or interaction.user.id == interaction.guild.owner_id or is_admin
        if not has_perm:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Ban Members** permission, be the server owner, or be an authorized bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        raw_ids = user_ids.split()
        parsed_ids = []
        invalid = []
        for raw in raw_ids:
            cleaned = raw.strip().strip(",")
            if cleaned.isdigit():
                uid = int(cleaned)
                if uid not in parsed_ids:
                    parsed_ids.append(uid)
            else:
                invalid.append(cleaned)

        if not parsed_ids:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ No Valid IDs",
                description="No valid user IDs were found. Provide space-separated numeric IDs.",
                color=0xff0000
            ), ephemeral=True)
            return

        # Remove self and owner
        parsed_ids = [uid for uid in parsed_ids if uid != interaction.user.id and uid != interaction.guild.owner_id]

        if not parsed_ids:
            await interaction.response.send_message(embed=discord.Embed(
                description="❌ No valid targets after filtering (cannot ban yourself or the owner).",
                color=0xff0000
            ), ephemeral=True)
            return

        confirm_embed = discord.Embed(
            title="⚠️ Mass Ban Confirmation",
            description=(
                f"You are about to ban **{len(parsed_ids)} user(s)**.\n\n"
                f"**Reason:** {reason}\n"
                f"**Messages Deleted:** {'None' if not delete_days else f'Last {delete_days} day(s)'}\n\n"
                f"**IDs to ban:**\n```{chr(10).join(str(uid) for uid in parsed_ids[:20])}{'...' if len(parsed_ids) > 20 else ''}```"
            ),
            color=0xff4444
        )
        if invalid:
            confirm_embed.add_field(name="⚠️ Invalid/Skipped IDs", value=" ".join(f"`{i}`" for i in invalid[:10]), inline=False)
        confirm_embed.set_footer(text="This action cannot be undone. You have 30 seconds to confirm.")

        view = MassBanConfirmView(interaction.user, len(parsed_ids))
        await interaction.response.send_message(embed=confirm_embed, view=view)
        await view.wait()

        if not view.value:
            return

        # Perform the bans
        banned = []
        failed = []
        for uid in parsed_ids:
            try:
                await interaction.guild.ban(
                    discord.Object(id=uid),
                    reason=f"{reason} | Mass ban by {interaction.user} ({interaction.user.id})",
                    delete_message_days=delete_days
                )
                banned.append(uid)
            except Exception:
                failed.append(uid)
            await asyncio.sleep(0.5)

        result_embed = discord.Embed(
            title="🔨 Mass Ban Complete",
            color=0xff4444 if failed else 0x57f287,
            timestamp=discord.utils.utcnow()
        )
        result_embed.add_field(name="✅ Successfully Banned", value=str(len(banned)), inline=True)
        result_embed.add_field(name="❌ Failed", value=str(len(failed)), inline=True)
        result_embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
        result_embed.add_field(name="📋 Reason", value=reason, inline=False)
        if failed:
            result_embed.add_field(
                name="❌ Failed IDs",
                value="\n".join(str(uid) for uid in failed[:10]) + ("..." if len(failed) > 10 else ""),
                inline=False
            )
        result_embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.edit_original_response(embed=result_embed, view=None)

        log_embed = discord.Embed(title="🔨 Moderation Action — Mass Ban", color=0xff4444, timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Banned", value=str(len(banned)), inline=True)
        log_embed.add_field(name="Failed", value=str(len(failed)), inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.add_field(name="IDs", value=", ".join(str(uid) for uid in banned[:30]), inline=False)
        log_embed.set_footer(text=f"Moderator ID: {interaction.user.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)

        # Anti-nuke: each successful ban in a mass ban counts against the moderator.
        # If they banned enough people fast enough, check_and_punish will fire.
        protection = self.bot.get_cog('Protection')
        if protection and banned:
            for uid in banned:
                banned_user_obj = discord.Object(id=uid)
                await protection.check_and_punish(
                    interaction.guild,
                    interaction.user,
                    'banning_members',
                    f"Used /massban (ID: {uid})",
                    {'banned_user': banned_user_obj},
                    responsible_user=interaction.user,
                )

    # ────────────────────────── /unban ───────────────────────────

    @app_commands.command(name="unban", description="🔓 Unban a user by ID or username")
    @app_commands.describe(user_id="The user ID to unban", reason="Reason for the unban")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        has_perm = interaction.user.guild_permissions.ban_members or interaction.user.id == interaction.guild.owner_id or is_admin
        if not has_perm:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Ban Members** permission, be the server owner, or be an authorized bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        if not user_id.strip().isdigit():
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Invalid ID",
                description="Please provide a valid numeric user ID.",
                color=0xff0000
            ), ephemeral=True)
            return

        uid = int(user_id.strip())

        try:
            ban_entry = await interaction.guild.fetch_ban(discord.Object(id=uid))
        except discord.NotFound:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Not Banned",
                description=f"No ban was found for user ID `{uid}` in this server.",
                color=0xff0000
            ), ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Error",
                description=f"Could not fetch ban entry: `{e}`",
                color=0xff0000
            ), ephemeral=True)
            return

        user = ban_entry.user
        await interaction.guild.unban(user, reason=f"{reason} | Unbanned by {interaction.user} ({interaction.user.id})")

        dm_sent = False
        try:
            dm_embed = discord.Embed(
                title="🔓 You Have Been Unbanned",
                description=f"Your ban in **{interaction.guild.name}** has been lifted. You may rejoin using an invite link.",
                color=0x57f287,
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="🏠 Server", value=interaction.guild.name, inline=True)
            dm_embed.add_field(name="🛡️ Unbanned By", value=str(interaction.user), inline=True)
            dm_embed.add_field(name="📋 Reason", value=reason, inline=False)
            dm_embed.set_footer(text=f"{BOT_NAME} • Moderation")
            await user.send(embed=dm_embed)
            dm_sent = True
        except Exception:
            pass

        embed = discord.Embed(title="🔓 User Unbanned", color=0x57f287, timestamp=discord.utils.utcnow())
        embed.add_field(name="👤 User", value=f"{user}\n`{user.id}`", inline=True)
        embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.add_field(name="📝 Original Ban Reason", value=ban_entry.reason or "No reason recorded", inline=False)
        embed.add_field(name="📨 DM Sent", value="✅ Yes" if dm_sent else "❌ DMs closed", inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        log_embed = discord.Embed(title="🔓 Moderation Action — Unban", color=0x57f287, timestamp=discord.utils.utcnow())
        log_embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.add_field(name="DM Delivered", value="✅" if dm_sent else "❌", inline=True)
        log_embed.set_thumbnail(url=user.display_avatar.url)
        log_embed.set_footer(text=f"User ID: {user.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)

    # ────────────────────────── /slowmode ────────────────────────

    @app_commands.command(name="slowmode", description="⏱️ Set slowmode on a channel")
    @app_commands.describe(
        seconds="Slowmode delay in seconds (0 to disable, max 21600)",
        channel="Channel to apply slowmode to (defaults to current channel)",
        reason="Reason for the slowmode"
    )
    async def slowmode(self, interaction: discord.Interaction, seconds: int,
                       channel: discord.TextChannel = None, reason: str = "No reason provided"):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (_has_mod_perms(interaction, "manage_channels") or is_admin):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Manage Channels** permission, be the server owner, or be an authorized bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        if seconds < 0 or seconds > 21600:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Invalid Value",
                description="Slowmode must be between **0** (off) and **21600** seconds (6 hours).",
                color=0xff0000
            ), ephemeral=True)
            return

        target = channel or interaction.channel
        old_slowmode = target.slowmode_delay
        await target.edit(slowmode_delay=seconds, reason=f"{reason} | Set by {interaction.user}")

        if seconds == 0:
            desc = f"Slowmode has been **disabled** in {target.mention}."
            color = 0x57f287
            title = "⏱️ Slowmode Disabled"
        else:
            desc = f"Slowmode set to **{format_time(seconds)}** in {target.mention}."
            color = 0x5865f2
            title = "⏱️ Slowmode Updated"

        embed = discord.Embed(title=title, description=desc, color=color, timestamp=discord.utils.utcnow())
        embed.add_field(name="📌 Channel", value=target.mention, inline=True)
        embed.add_field(name="⏱️ New Delay", value=f"{seconds}s" if seconds else "Off", inline=True)
        embed.add_field(name="📋 Previous", value=f"{old_slowmode}s" if old_slowmode else "Off", inline=True)
        embed.add_field(name="🛡️ Set By", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        log_embed = discord.Embed(title=f"⏱️ Moderation Action — Slowmode {'Set' if seconds else 'Disabled'}", color=color, timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Channel", value=f"{target.mention} (`{target.id}`)", inline=True)
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="New Delay", value=f"{seconds}s" if seconds else "Disabled", inline=True)
        log_embed.add_field(name="Previous", value=f"{old_slowmode}s" if old_slowmode else "Off", inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.set_footer(text=f"Channel ID: {target.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)

    # ────────────────────────── /history ─────────────────────────

    @app_commands.command(name="history", description="📜 View moderation history for a user")
    @app_commands.describe(user="The member to view history for")
    async def history(self, interaction: discord.Interaction, user: discord.Member):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (_has_mod_perms(interaction, "manage_messages") or is_admin):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Manage Messages** permission or be a bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        await interaction.response.defer()

        warns = await self.bot.warns_db.get_warns(interaction.guild.id, user.id)
        warn_count = len(warns)

        is_jailed = await self.bot.jail_db.get_jailed_user(interaction.guild.id, user.id) is not None
        jail_data = await self.bot.jail_db.get_jailed_user(interaction.guild.id, user.id)

        is_muted = user.is_timed_out()
        muted_until = user.timed_out_until

        try:
            ban_entry = await interaction.guild.fetch_ban(user)
            is_banned = True
        except Exception:
            is_banned = False
            ban_entry = None

        color = 0xff4444 if (warn_count >= 3 or is_banned or is_jailed) else (0xffcc00 if warn_count > 0 else 0x57f287)

        embed = discord.Embed(
            title=f"📜 Moderation History — {user.display_name}",
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="👤 User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="📅 Account Created", value=f"<t:{int(user.created_at.timestamp())}:R>", inline=True)
        embed.add_field(name="📥 Joined Server", value=f"<t:{int(user.joined_at.timestamp())}:R>" if user.joined_at else "Unknown", inline=True)

        # Status indicators
        status_lines = []
        if is_banned:
            status_lines.append("🔴 **Currently Banned**")
        elif is_jailed:
            status_lines.append("🟠 **Currently Jailed**")
        elif is_muted:
            status_lines.append(f"🟡 **Currently Muted** (until <t:{int(muted_until.timestamp())}:R>)")
        else:
            status_lines.append("🟢 **No Active Punishments**")

        embed.add_field(name="⚡ Current Status", value="\n".join(status_lines), inline=False)
        embed.add_field(name="⚠️ Total Warnings", value=f"**{warn_count}** warning(s)", inline=True)

        if is_jailed and jail_data:
            _, jail_reason, _, _, jail_expires = jail_data
            embed.add_field(
                name="🔒 Jail Info",
                value=f"**Reason:** {jail_reason}\n**Expires:** {'Never' if not jail_expires else f'<t:{jail_expires}:R>'}",
                inline=False
            )

        # Last 5 warnings
        if warns:
            warn_lines = []
            for warn_id, moderator_id, reason, ts in warns[:5]:
                mod = interaction.guild.get_member(moderator_id)
                mod_str = str(mod) if mod else f"Unknown (`{moderator_id}`)"
                warn_lines.append(f"**#{warn_id}** — <t:{ts}:d> — {reason[:60]} *(by {mod_str})*")
            embed.add_field(
                name=f"⚠️ Recent Warnings ({min(5, warn_count)} of {warn_count})",
                value="\n".join(warn_lines),
                inline=False
            )

        embed.set_footer(text=f"{BOT_NAME} • Moderation History", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.followup.send(embed=embed)

        log_embed = discord.Embed(title="📜 History Lookup", color=0x5865f2, timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Target User", value=f"{user} (`{user.id}`)", inline=True)
        log_embed.add_field(name="Requested By", value=interaction.user.mention, inline=True)
        log_embed.set_footer(text=f"User ID: {user.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)

    # ────────────────────────── /lockdown (single channel) ───────

    @app_commands.command(name="lockdown", description="🔒 Lock a specific channel (deny @everyone from sending messages)")
    @app_commands.describe(
        channel="Channel to lock (defaults to current channel)",
        reason="Reason for the lockdown"
    )
    async def lockdown(self, interaction: discord.Interaction,
                       channel: discord.TextChannel = None, reason: str = "No reason provided"):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (_has_mod_perms(interaction, "manage_channels") or is_admin):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Manage Channels** permission or be a bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        target = channel or interaction.channel
        overwrite = target.overwrites_for(interaction.guild.default_role)
        if overwrite.send_messages is False:
            await interaction.response.send_message(embed=discord.Embed(
                description=f"ℹ️ {target.mention} is already locked.",
                color=0x5865f2
            ), ephemeral=True)
            return

        overwrite.send_messages = False
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite,
                                     reason=f"Lockdown by {interaction.user}: {reason}")

        embed = discord.Embed(
            title="🔒 Channel Locked",
            description=f"{target.mention} has been locked. Members can no longer send messages.",
            color=0xff4444,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="📌 Channel", value=target.mention, inline=True)
        embed.add_field(name="🛡️ Locked By", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        try:
            lock_notice = discord.Embed(
                title="🔒 This channel has been locked",
                description=f"**Reason:** {reason}",
                color=0xff4444,
                timestamp=discord.utils.utcnow()
            )
            lock_notice.set_footer(text=f"Locked by {interaction.user}")
            await target.send(embed=lock_notice)
        except Exception:
            pass

        log_embed = discord.Embed(title="🔒 Moderation Action — Channel Lockdown", color=0xff4444, timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Channel", value=f"{target.mention} (`{target.id}`)", inline=True)
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.set_footer(text=f"Channel ID: {target.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)

    # ────────────────────────── /unlockdown (single channel) ─────

    @app_commands.command(name="unlockdown", description="🔓 Unlock a specific channel")
    @app_commands.describe(
        channel="Channel to unlock (defaults to current channel)",
        reason="Reason for unlocking"
    )
    async def unlockdown(self, interaction: discord.Interaction,
                         channel: discord.TextChannel = None, reason: str = "No reason provided"):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (_has_mod_perms(interaction, "manage_channels") or is_admin):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Manage Channels** permission or be a bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        target = channel or interaction.channel
        overwrite = target.overwrites_for(interaction.guild.default_role)
        if overwrite.send_messages is not False:
            await interaction.response.send_message(embed=discord.Embed(
                description=f"ℹ️ {target.mention} is not currently locked.",
                color=0x5865f2
            ), ephemeral=True)
            return

        overwrite.send_messages = None
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite,
                                     reason=f"Unlock by {interaction.user}: {reason}")

        embed = discord.Embed(
            title="🔓 Channel Unlocked",
            description=f"{target.mention} has been unlocked. Members can send messages again.",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="📌 Channel", value=target.mention, inline=True)
        embed.add_field(name="🛡️ Unlocked By", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.set_footer(text=f"{BOT_NAME} • Moderation", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        try:
            unlock_notice = discord.Embed(
                title="🔓 This channel has been unlocked",
                description=f"**Reason:** {reason}",
                color=0x57f287,
                timestamp=discord.utils.utcnow()
            )
            unlock_notice.set_footer(text=f"Unlocked by {interaction.user}")
            await target.send(embed=unlock_notice)
        except Exception:
            pass

        log_embed = discord.Embed(title="🔓 Moderation Action — Channel Unlock", color=0x57f287, timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Channel", value=f"{target.mention} (`{target.id}`)", inline=True)
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.set_footer(text=f"Channel ID: {target.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)

    # ────────────────────────── /masslockdown ────────────────────

    @app_commands.command(name="masslockdown", description="🔒 Lock ALL text channels (requires confirmation)")
    @app_commands.describe(reason="Reason for the mass lockdown")
    async def masslockdown(self, interaction: discord.Interaction, reason: str = "No reason provided"):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator or is_admin):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the server owner, administrators, or authorized bot admins can use mass lockdown.",
                color=0xff0000
            ), ephemeral=True)
            return

        text_channels = [c for c in interaction.guild.text_channels
                         if c.permissions_for(interaction.guild.me).manage_channels]

        confirm_embed = discord.Embed(
            title="⚠️ Mass Lockdown Confirmation",
            description=(
                f"You are about to **lock {len(text_channels)} text channel(s)** in **{interaction.guild.name}**.\n\n"
                f"This will deny `@everyone` from sending messages in **all** text channels.\n\n"
                f"**Reason:** {reason}\n\n"
                f"⚠️ Use `/massunlockdown` to restore all channels.\n"
                f"You have **30 seconds** to confirm."
            ),
            color=0xff4444
        )
        confirm_embed.set_footer(text=f"{BOT_NAME} • Destructive Action Warning")

        view = LockdownConfirmView(interaction.user, "lock")
        await interaction.response.send_message(embed=confirm_embed, view=view)
        await view.wait()

        if not view.value:
            return

        backup = {}
        locked = 0
        failed = 0
        everyone = interaction.guild.default_role

        for ch in text_channels:
            try:
                ow = ch.overwrites_for(everyone)
                # Save current state
                backup[ch.id] = ow.send_messages
                # Lock
                ow.send_messages = False
                await ch.set_permissions(everyone, overwrite=ow,
                                         reason=f"Mass lockdown by {interaction.user}: {reason}")
                locked += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.3)

        self._lockdown_backups[interaction.guild.id] = backup

        result_embed = discord.Embed(
            title="🔒 Mass Lockdown Active",
            description=f"**{locked}** channel(s) have been locked. Use `/massunlockdown` to restore.",
            color=0xff4444,
            timestamp=discord.utils.utcnow()
        )
        result_embed.add_field(name="✅ Locked", value=str(locked), inline=True)
        result_embed.add_field(name="❌ Failed", value=str(failed), inline=True)
        result_embed.add_field(name="🛡️ Initiated By", value=interaction.user.mention, inline=True)
        result_embed.add_field(name="📋 Reason", value=reason, inline=False)
        result_embed.set_footer(text=f"{BOT_NAME} • Mass Lockdown", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.edit_original_response(embed=result_embed, view=None)

        log_embed = discord.Embed(title="🔒 MASS LOCKDOWN ACTIVATED", color=0xff4444, timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Channels Locked", value=str(locked), inline=True)
        log_embed.add_field(name="Failed", value=str(failed), inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.set_footer(text=f"Moderator ID: {interaction.user.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)

    # ────────────────────────── /massunlockdown ──────────────────

    @app_commands.command(name="massunlockdown", description="🔓 Unlock ALL channels and restore permissions (requires confirmation)")
    @app_commands.describe(reason="Reason for the unlock")
    async def massunlockdown(self, interaction: discord.Interaction, reason: str = "No reason provided"):
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator or is_admin):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the server owner, administrators, or authorized bot admins can use mass unlockdown.",
                color=0xff0000
            ), ephemeral=True)
            return

        text_channels = [c for c in interaction.guild.text_channels
                         if c.permissions_for(interaction.guild.me).manage_channels]

        confirm_embed = discord.Embed(
            title="⚠️ Mass Unlockdown Confirmation",
            description=(
                f"You are about to **unlock {len(text_channels)} text channel(s)** in **{interaction.guild.name}**.\n\n"
                f"This will restore `@everyone` send permissions to all text channels.\n\n"
                f"**Reason:** {reason}\n\n"
                f"You have **30 seconds** to confirm."
            ),
            color=0x57f287
        )
        confirm_embed.set_footer(text=f"{BOT_NAME} • Restore Permissions")

        view = LockdownConfirmView(interaction.user, "unlock")
        await interaction.response.send_message(embed=confirm_embed, view=view)
        await view.wait()

        if not view.value:
            return

        backup = self._lockdown_backups.get(interaction.guild.id, {})
        everyone = interaction.guild.default_role
        unlocked = 0
        failed = 0

        for ch in text_channels:
            try:
                ow = ch.overwrites_for(everyone)
                # Restore to backed up state, or set to None (inherit)
                previous = backup.get(ch.id, None)
                ow.send_messages = previous
                await ch.set_permissions(everyone, overwrite=ow,
                                         reason=f"Mass unlockdown by {interaction.user}: {reason}")
                unlocked += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.3)

        self._lockdown_backups.pop(interaction.guild.id, None)

        result_embed = discord.Embed(
            title="🔓 Mass Unlockdown Complete",
            description=f"**{unlocked}** channel(s) have been restored.",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        result_embed.add_field(name="✅ Unlocked", value=str(unlocked), inline=True)
        result_embed.add_field(name="❌ Failed", value=str(failed), inline=True)
        result_embed.add_field(name="🛡️ Initiated By", value=interaction.user.mention, inline=True)
        result_embed.add_field(name="📋 Reason", value=reason, inline=False)
        result_embed.set_footer(text=f"{BOT_NAME} • Mass Unlockdown", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.edit_original_response(embed=result_embed, view=None)

        log_embed = discord.Embed(title="🔓 MASS UNLOCKDOWN", color=0x57f287, timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Channels Unlocked", value=str(unlocked), inline=True)
        log_embed.add_field(name="Failed", value=str(failed), inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.set_footer(text=f"Moderator ID: {interaction.user.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)


async def setup(bot):
    await bot.add_cog(Moderation(bot))