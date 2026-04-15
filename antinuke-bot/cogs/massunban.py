import discord
from discord import app_commands
from discord.ext import commands
import asyncio

BOT_NAME = "VO AntiNuke"


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


class MassUnbanConfirmView(discord.ui.View):
    def __init__(self, author: discord.Member, count: int):
        super().__init__(timeout=30)
        self.author = author
        self.count = count
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await interaction.response.defer()
        if interaction.user.id != self.author.id:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ Only the command invoker can confirm.", color=0xff0000),
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="✅  Confirm Mass Unban", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.value = True
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⏳ Unbanning...",
                description=f"Processing **{self.count}** unban(s)...",
                color=0xffaa00
            ),
            view=self
        )

    @discord.ui.button(label="❌  Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.value = False
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(title="❌ Cancelled", description="No users were unbanned.", color=0x5865f2),
            view=self
        )


class MassUnban(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="massunban", description="🔓 Unban all currently banned users from the server")
    @app_commands.describe(reason="Reason for the mass unban")
    async def massunban(self, interaction: discord.Interaction, reason: str = "Mass unban"):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        has_perm = (
            interaction.user.guild_permissions.ban_members
            or interaction.user.id == interaction.guild.owner_id
            or is_admin
        )
        if not has_perm:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Ban Members** permission, be the server owner, or be an authorized bot admin.",
                color=0xff0000
            ), ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        try:
            ban_entries = [entry async for entry in interaction.guild.bans(limit=None)]
        except discord.Forbidden:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Missing Permission",
                description="I don't have permission to view the ban list.",
                color=0xff0000
            ), ephemeral=True)
            return

        if not ban_entries:
            await interaction.followup.send(embed=discord.Embed(
                title="ℹ️ No Banned Users",
                description="There are no banned users in this server.",
                color=0x5865f2
            ), ephemeral=True)
            return

        count = len(ban_entries)
        preview_lines = []
        for entry in ban_entries[:15]:
            preview_lines.append(f"• `{entry.user.id}` — {entry.user} (ban reason: {entry.reason or 'none'})")
        preview = "\n".join(preview_lines)
        if count > 15:
            preview += f"\n*...and {count - 15} more.*"

        confirm_embed = discord.Embed(
            title="⚠️ Mass Unban Confirmation",
            description=(
                f"You are about to **unban {count} user(s)** from **{interaction.guild.name}**.\n\n"
                f"**Reason:** {reason}\n\n"
                f"**Banned users (preview):**\n{preview}\n\n"
                f"⚠️ This will lift **all** bans. You have **30 seconds** to confirm."
            ),
            color=0xffaa00
        )
        confirm_embed.set_footer(text=f"{BOT_NAME} • Destructive Action Warning")

        view = MassUnbanConfirmView(interaction.user, count)
        await interaction.followup.send(embed=confirm_embed, view=view)
        await view.wait()

        if not view.value:
            return

        unbanned = []
        failed = []
        for entry in ban_entries:
            try:
                await interaction.guild.unban(
                    entry.user,
                    reason=f"{reason} | Mass unban by {interaction.user} ({interaction.user.id})"
                )
                unbanned.append(entry.user)
            except Exception:
                failed.append(entry.user)
            await asyncio.sleep(0.4)

        result_embed = discord.Embed(
            title="🔓 Mass Unban Complete",
            color=0x57f287 if not failed else 0xffaa00,
            timestamp=discord.utils.utcnow()
        )
        result_embed.add_field(name="✅ Successfully Unbanned", value=str(len(unbanned)), inline=True)
        result_embed.add_field(name="❌ Failed", value=str(len(failed)), inline=True)
        result_embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
        result_embed.add_field(name="📋 Reason", value=reason, inline=False)
        if failed:
            result_embed.add_field(
                name="❌ Failed IDs",
                value="\n".join(f"`{u.id}`" for u in failed[:10]) + ("..." if len(failed) > 10 else ""),
                inline=False
            )
        result_embed.set_footer(text=f"{BOT_NAME} • Mass Unban", icon_url=interaction.guild.me.display_avatar.url)
        await interaction.edit_original_response(embed=result_embed, view=None)

        log_embed = discord.Embed(
            title="🔓 Moderation Action — Mass Unban",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Unbanned", value=str(len(unbanned)), inline=True)
        log_embed.add_field(name="Failed", value=str(len(failed)), inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.set_footer(text=f"Moderator ID: {interaction.user.id} • {BOT_NAME}")
        await _send_log(self.bot, interaction.guild, log_embed)


async def setup(bot):
    await bot.add_cog(MassUnban(bot))