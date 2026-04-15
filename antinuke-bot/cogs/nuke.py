import discord
from discord import app_commands
from discord.ext import commands
import asyncio


class NukeConfirmView(discord.ui.View):
    def __init__(self, channel: discord.TextChannel, author: discord.Member):
        super().__init__(timeout=30)
        self.channel = channel
        self.author = author
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await interaction.response.defer()
        if interaction.user.id != self.author.id:
            await interaction.followup.send(
                embed=discord.Embed(
                    description="❌ Only the command invoker can confirm this action.",
                    color=0xff4444
                ),
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="☢️  Confirm Nuke",
        style=discord.ButtonStyle.danger,
        custom_id="confirm_nuke"
    )
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.confirmed = True
        for item in self.children:
            item.disabled = True
        self.stop()

        processing_embed = discord.Embed(
            title="☢️ Nuking Channel...",
            description="```\n[▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓] 100%\n```\nDestroying and rebuilding channel...",
            color=0xff6600
        )
        await interaction.response.edit_message(embed=processing_embed, view=self)

        channel = self.channel
        guild = channel.guild

        try:
            new_channel = await channel.clone(reason=f"Channel nuked by {self.author}")
            await new_channel.edit(position=channel.position)
            await channel.delete(reason=f"Nuked by {self.author} ({self.author.id})")

            success_embed = discord.Embed(
                title="☢️ Channel Successfully Nuked",
                description=(
                    f"**#{channel.name}** has been obliterated and rebuilt.\n\n"
                    f"> All previous messages have been wiped.\n"
                    f"> Channel permissions and settings preserved."
                ),
                color=0xff4500
            )
            success_embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1171014935499571370.gif" if False else discord.utils.MISSING)
            success_embed.add_field(name="🗑️ Deleted", value=f"#{channel.name}", inline=True)
            success_embed.add_field(name="✨ Recreated", value=f"{new_channel.mention}", inline=True)
            success_embed.add_field(name="👤 Executed By", value=f"{self.author.mention}", inline=True)
            success_embed.set_footer(text="VO AntiNuke • Moderation", icon_url=guild.me.display_avatar.url)
            success_embed.timestamp = discord.utils.utcnow()

            nuke_msg = await new_channel.send(embed=success_embed)

            # Log to mod log channel if set
            bot = interaction.client
            log_channel_id = await bot.db.get_log_channel(guild.id)
            if log_channel_id:
                log_channel = guild.get_channel(log_channel_id)
                if log_channel:
                    log_embed = discord.Embed(
                        title="🔨 Moderation Action — Channel Nuked",
                        color=0xff4500,
                        timestamp=discord.utils.utcnow()
                    )
                    log_embed.add_field(name="Moderator", value=f"{self.author.mention} (`{self.author.id}`)", inline=True)
                    log_embed.add_field(name="Channel", value=f"#{channel.name} → {new_channel.mention}", inline=True)
                    log_embed.add_field(name="Action", value="Channel Nuked (cloned + deleted)", inline=False)
                    log_embed.set_footer(text=f"User ID: {self.author.id}")
                    await log_channel.send(embed=log_embed)

        except discord.Forbidden:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Permission Error",
                    description="I don't have permission to delete or clone this channel.",
                    color=0xff0000
                ),
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Error",
                    description=f"Something went wrong: `{e}`",
                    color=0xff0000
                ),
                ephemeral=True
            )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        custom_id="cancel_nuke"
    )
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        self.stop()

        cancel_embed = discord.Embed(
            title="✅ Nuke Cancelled",
            description="The channel nuke has been called off. No changes were made.",
            color=0x57f287
        )
        cancel_embed.set_footer(text=f"Cancelled by {interaction.user}")
        await interaction.response.edit_message(embed=cancel_embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Nuke(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="nuke", description="☢️ Wipe a channel by cloning it and deleting the original")
    @app_commands.describe(channel="The channel to nuke (defaults to current channel)")
    async def nuke(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await interaction.response.defer()
        # Permission check — administrator, manage channels, server owner, or bot admin
        is_bot_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        has_perm = (
            interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.manage_channels
            or interaction.user.id == interaction.guild.owner_id
            or is_bot_admin
        )
        if not has_perm:
            embed = discord.Embed(
                title="❌ Access Denied",
                description=(
                    "You need one of the following to use this command:\n"
                    "• **Administrator** or **Manage Channels** permission\n"
                    "• Server Owner\n"
                    "• Authorized bot admin (via `/addadmin`)"
                ),
                color=0xff0000
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        target = channel or interaction.channel

        # Don't allow nuking system/rules channels easily
        rules_channel_id = getattr(interaction.guild, 'rules_channel_id', None)
        if rules_channel_id and target.id == rules_channel_id:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Restricted",
                    description="You cannot nuke the server's rules channel.",
                    color=0xff0000
                ),
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="☢️  NUKE WARNING",
            description=(
                f"You are about to **permanently wipe** {target.mention}.\n\n"
                f"**⚠️ This will:**\n"
                f"```\n"
                f"• Delete ALL messages in the channel\n"
                f"• Clone the channel with identical settings\n"
                f"• This action CANNOT be undone\n"
                f"```\n"
                f"**Click the button below to confirm or cancel.**"
            ),
            color=0xff6600
        )
        embed.add_field(name="🎯 Target Channel", value=target.mention, inline=True)
        embed.add_field(name="👤 Initiated By", value=interaction.user.mention, inline=True)
        embed.set_footer(
            text="⏱️ This prompt expires in 30 seconds • VO AntiNuke",
            icon_url=interaction.guild.me.display_avatar.url
        )
        embed.timestamp = discord.utils.utcnow()

        view = NukeConfirmView(target, interaction.user)
        await interaction.followup.send(embed=embed, view=view)

        await view.wait()

        if not view.confirmed:
            # Timeout case — edit to show expired
            try:
                timeout_embed = discord.Embed(
                    title="⏰ Nuke Prompt Expired",
                    description="No response received. The nuke has been cancelled.",
                    color=0x808080
                )
                await interaction.edit_original_response(embed=timeout_embed, view=view)
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(Nuke(bot))