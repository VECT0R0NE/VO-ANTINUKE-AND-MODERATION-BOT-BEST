import discord
from discord import app_commands
from discord.ext import commands
import time

BOT_NAME = "VO AntiNuke"


async def _is_admin(bot, guild_id, user_id):
    return await bot.db.is_admin(guild_id, user_id)


class InviteTracker(commands.Cog):
    """Tracks which invite was used when a member joins and stores who invited who."""

    def __init__(self, bot):
        self.bot = bot
        # guild_id -> {invite_code -> uses}
        self._invite_cache: dict[int, dict[str, int]] = {}

    # ─── Cache helpers ───────────────────────────────────────────────────────

    async def _build_cache(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self._invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _find_used_invite(self, guild: discord.Guild):
        """Return (invite_code, inviter) for the invite just used, or (None, None)."""
        old_cache = self._invite_cache.get(guild.id, {})
        try:
            current_invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return None, None

        used_code = None
        inviter = None
        for inv in current_invites:
            old_uses = old_cache.get(inv.code, 0)
            if inv.uses > old_uses:
                used_code = inv.code
                inviter = inv.inviter
                break

        # Refresh the cache
        self._invite_cache[guild.id] = {inv.code: inv.uses for inv in current_invites}
        return used_code, inviter

    # ─── Events ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._build_cache(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._build_cache(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild:
            cache = self._invite_cache.get(invite.guild.id, {})
            cache[invite.code] = invite.uses or 0
            self._invite_cache[invite.guild.id] = cache

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild:
            cache = self._invite_cache.get(invite.guild.id, {})
            cache.pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        used_code, inviter = await self._find_used_invite(member.guild)
        if used_code and inviter:
            await self.bot.db.record_invite(
                guild_id=member.guild.id,
                user_id=member.id,
                inviter_id=inviter.id,
                invite_code=used_code
            )

    # ─── /whoinvited ─────────────────────────────────────────────────────────

    @app_commands.command(name="whoinvited", description="🔗 Show who invited a member to the server")
    @app_commands.describe(member="The member to look up")
    async def whoinvited(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.manage_guild or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Manage Server** permission or be a bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        data = await self.bot.db.get_inviter(interaction.guild.id, member.id)

        embed = discord.Embed(
            title="🔗 Invite Information",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤 Member", value=f"{member.mention}\n`{member.id}`", inline=True)

        if data:
            inviter = interaction.guild.get_member(data["inviter_id"]) or self.bot.get_user(data["inviter_id"])
            inviter_str = inviter.mention if inviter else f"Unknown (`{data['inviter_id']}`)"
            embed.add_field(name="✉️ Invited By", value=inviter_str, inline=True)
            embed.add_field(name="🔑 Invite Code", value=f"`{data['invite_code']}`", inline=True)
            embed.add_field(name="📅 Joined", value=f"<t:{data['joined_at']}:R>", inline=True)
        else:
            embed.add_field(
                name="ℹ️ No Data",
                value="No invite record found. They may have joined before invite tracking was set up, or used a bot/vanity URL.",
                inline=False
            )

        embed.set_footer(text=f"{BOT_NAME} • Invite Tracker")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── /invites ────────────────────────────────────────────────────────────

    @app_commands.command(name="invites", description="📊 Show how many users a member has invited")
    @app_commands.describe(member="The member to check (defaults to yourself)")
    async def invites(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        target = member or interaction.user

        await interaction.response.defer(thinking=True)

        invited = await self.bot.db.get_invited_by(interaction.guild.id, target.id)

        embed = discord.Embed(
            title=f"📊 Invites — {target.display_name}",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="👤 Member", value=f"{target.mention}\n`{target.id}`", inline=True)
        embed.add_field(name="✉️ Total Invites", value=str(len(invited)), inline=True)

        if invited:
            lines = []
            for row in invited[:15]:
                user = interaction.guild.get_member(row["user_id"]) or self.bot.get_user(row["user_id"])
                user_str = str(user) if user else f"Unknown (`{row['user_id']}`)"
                lines.append(f"• {user_str} — <t:{row['joined_at']}:d> (`{row['invite_code']}`)")
            embed.add_field(
                name=f"📋 Invited Members (showing {min(15, len(invited))} of {len(invited)})",
                value="\n".join(lines),
                inline=False
            )

        embed.set_footer(text=f"{BOT_NAME} • Invite Tracker")
        await interaction.followup.send(embed=embed)

    # ─── /inviteleaderboard ──────────────────────────────────────────────────

    @app_commands.command(name="inviteleaderboard", description="🏆 Show the top inviters in the server")
    async def inviteleaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.manage_guild or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                description="❌ You need **Manage Server** permission.", color=0xff0000
            ), ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        leaderboard = await self.bot.db.get_invite_leaderboard(interaction.guild.id, limit=15)

        embed = discord.Embed(
            title="🏆 Invite Leaderboard",
            color=0xffd700,
            timestamp=discord.utils.utcnow()
        )

        if not leaderboard:
            embed.description = "*No invite data recorded yet.*"
        else:
            lines = []
            medals = ["🥇", "🥈", "🥉"]
            for i, row in enumerate(leaderboard):
                prefix = medals[i] if i < 3 else f"`#{i+1}`"
                user = interaction.guild.get_member(row["inviter_id"]) or self.bot.get_user(row["inviter_id"])
                user_str = str(user) if user else f"Unknown (`{row['inviter_id']}`)"
                lines.append(f"{prefix} **{user_str}** — {row['count']} invite(s)")
            embed.description = "\n".join(lines)

        embed.set_footer(text=f"{BOT_NAME} • Invite Tracker")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(InviteTracker(bot))