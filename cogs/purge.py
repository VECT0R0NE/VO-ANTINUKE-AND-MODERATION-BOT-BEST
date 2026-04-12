"""
purge.py — Enhanced bulk message deletion with multiple filter options.

Replaces the original single-filter purge. All existing behaviour is
preserved; new filters are additive. Discord's bulk-delete limit is 14 days
(messages older than that must be deleted one-by-one, which is slow).
"""
import discord
from discord import app_commands
from discord.ext import commands
import re

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


def _build_check(
    user=None,
    contains=None,
    has_attachments=None,
    has_links=None,
    has_embeds=None,
    bots_only=None,
    humans_only=None,
    starts_with=None,
    ends_with=None,
):
    URL_RE = re.compile(r'https?://\S+')

    def check(msg: discord.Message) -> bool:
        if user and msg.author.id != user.id:
            return False
        if bots_only and not msg.author.bot:
            return False
        if humans_only and msg.author.bot:
            return False
        if contains and contains.lower() not in msg.content.lower():
            return False
        if starts_with and not msg.content.lower().startswith(starts_with.lower()):
            return False
        if ends_with and not msg.content.lower().endswith(ends_with.lower()):
            return False
        if has_attachments is True and not msg.attachments:
            return False
        if has_attachments is False and msg.attachments:
            return False
        if has_links is True and not URL_RE.search(msg.content):
            return False
        if has_links is False and URL_RE.search(msg.content):
            return False
        if has_embeds is True and not msg.embeds:
            return False
        if has_embeds is False and msg.embeds:
            return False
        return True

    return check


class Purge(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _check_perms(self, interaction: discord.Interaction) -> bool:
        is_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        return (
            interaction.user.guild_permissions.manage_messages
            or interaction.user.id == interaction.guild.owner_id
            or is_admin
        )

    async def _do_purge(self, interaction, amount, check, reason, description):
        bot_member = interaction.guild.get_member(self.bot.user.id)
        if not interaction.channel.permissions_for(bot_member).manage_messages:
            await interaction.response.send_message(embed=discord.Embed(
                title='Missing Permissions',
                description='I need **Manage Messages** permission in this channel.',
                color=0xff0000
            ), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            deleted = await interaction.channel.purge(
                limit=amount, check=check,
                reason=f'{reason} | Purge by {interaction.user}'
            )
        except discord.Forbidden:
            await interaction.followup.send(embed=discord.Embed(
                title='Permission Error', description="I don't have permission to delete messages here.", color=0xff0000
            ), ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(embed=discord.Embed(
                title='Error', description=f'Failed: `{e}`', color=0xff0000
            ), ephemeral=True)
            return

        result_embed = discord.Embed(
            title='Purge Complete',
            description=f'Deleted **{len(deleted)}** message(s).\n{description}',
            color=0x57f287, timestamp=discord.utils.utcnow()
        )
        result_embed.add_field(name='Channel', value=interaction.channel.mention, inline=True)
        result_embed.add_field(name='Moderator', value=interaction.user.mention, inline=True)
        result_embed.add_field(name='Deleted', value=str(len(deleted)), inline=True)
        result_embed.add_field(name='Reason', value=reason, inline=False)
        result_embed.set_footer(text=f'{BOT_NAME} • Moderation', icon_url=interaction.guild.me.display_avatar.url)
        await interaction.followup.send(embed=result_embed, ephemeral=True)

        log_embed = discord.Embed(
            title='Moderation Action — Purge', color=0x57f287, timestamp=discord.utils.utcnow()
        )
        log_embed.add_field(name='Channel', value=f'{interaction.channel.mention} (`{interaction.channel.id}`)', inline=True)
        log_embed.add_field(name='Moderator', value=interaction.user.mention, inline=True)
        log_embed.add_field(name='Messages Deleted', value=str(len(deleted)), inline=True)
        log_embed.add_field(name='Filter', value=description, inline=True)
        log_embed.add_field(name='Reason', value=reason, inline=False)
        log_embed.set_footer(text=f'Moderator ID: {interaction.user.id} • {BOT_NAME}')
        await _send_log(self.bot, interaction.guild, log_embed)

    @app_commands.command(name='purge', description='Bulk delete messages with optional filters')
    @app_commands.describe(
        amount='Number of messages to scan (1-500)',
        user='Only delete messages from this user',
        contains='Only delete messages containing this text',
        has_attachments='Messages with (True) or without (False) attachments',
        has_links='Messages with (True) or without (False) links',
        has_embeds='Messages with (True) or without (False) embeds',
        bots_only='Only delete messages from bots',
        humans_only='Only delete messages from humans',
        starts_with='Only delete messages starting with this text',
        ends_with='Only delete messages ending with this text',
        reason='Reason for the purge'
    )
    async def purge(
        self, interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 500],
        user: discord.Member = None,
        contains: str = None,
        has_attachments: bool = None,
        has_links: bool = None,
        has_embeds: bool = None,
        bots_only: bool = None,
        humans_only: bool = None,
        starts_with: str = None,
        ends_with: str = None,
        reason: str = 'No reason provided',
    ):
        if not await self._check_perms(interaction):
            await interaction.response.send_message(embed=discord.Embed(
                title='Access Denied',
                description='You need **Manage Messages** permission, be the server owner, or be an authorized bot admin.',
                color=0xff0000
            ), ephemeral=True)
            return

        if bots_only and humans_only:
            await interaction.response.send_message(embed=discord.Embed(
                title='Conflicting Filters',
                description='`bots_only` and `humans_only` cannot both be True.',
                color=0xff0000
            ), ephemeral=True)
            return

        check = _build_check(user, contains, has_attachments, has_links, has_embeds, bots_only, humans_only, starts_with, ends_with)
        parts = []
        if user: parts.append(f'from {user.mention}')
        if contains: parts.append(f'containing `{contains}`')
        if has_attachments is True: parts.append('with attachments')
        elif has_attachments is False: parts.append('without attachments')
        if has_links is True: parts.append('with links')
        elif has_links is False: parts.append('without links')
        if has_embeds is True: parts.append('with embeds')
        elif has_embeds is False: parts.append('without embeds')
        if bots_only: parts.append('from bots only')
        if humans_only: parts.append('from humans only')
        if starts_with: parts.append(f'starting with `{starts_with}`')
        if ends_with: parts.append(f'ending with `{ends_with}`')
        description = ('Filters: ' + ', '.join(parts)) if parts else 'No filters (all messages)'
        await self._do_purge(interaction, amount, check, reason, description)

    @app_commands.command(name='purgeuser', description='Delete all recent messages from a specific user')
    @app_commands.describe(user='User', amount='Messages to scan (default 100)', reason='Reason')
    async def purgeuser(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, 500] = 100, reason: str = 'No reason provided'):
        if not await self._check_perms(interaction):
            await interaction.response.send_message(embed=discord.Embed(title='Access Denied', color=0xff0000), ephemeral=True)
            return
        await self._do_purge(interaction, amount, _build_check(user=user), reason, f'All messages from {user.mention}')

    @app_commands.command(name='purgebots', description='Delete recent messages from bots only')
    @app_commands.describe(amount='Messages to scan (default 100)', reason='Reason')
    async def purgebots(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 500] = 100, reason: str = 'No reason provided'):
        if not await self._check_perms(interaction):
            await interaction.response.send_message(embed=discord.Embed(title='Access Denied', color=0xff0000), ephemeral=True)
            return
        await self._do_purge(interaction, amount, _build_check(bots_only=True), reason, 'Bot messages only')

    @app_commands.command(name='purgelinks', description='Delete messages containing links')
    @app_commands.describe(amount='Messages to scan (default 100)', reason='Reason')
    async def purgelinks(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 500] = 100, reason: str = 'No reason provided'):
        if not await self._check_perms(interaction):
            await interaction.response.send_message(embed=discord.Embed(title='Access Denied', color=0xff0000), ephemeral=True)
            return
        await self._do_purge(interaction, amount, _build_check(has_links=True), reason, 'Messages with links')

    @app_commands.command(name='purgeattachments', description='Delete messages with attachments/files')
    @app_commands.describe(amount='Messages to scan (default 100)', reason='Reason')
    async def purgeattachments(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 500] = 100, reason: str = 'No reason provided'):
        if not await self._check_perms(interaction):
            await interaction.response.send_message(embed=discord.Embed(title='Access Denied', color=0xff0000), ephemeral=True)
            return
        await self._do_purge(interaction, amount, _build_check(has_attachments=True), reason, 'Messages with attachments')

    @app_commands.command(name='purgecontains', description='Delete messages containing specific text')
    @app_commands.describe(text='Text to search for (case-insensitive)', amount='Messages to scan (default 100)', reason='Reason')
    async def purgecontains(self, interaction: discord.Interaction, text: str, amount: app_commands.Range[int, 1, 500] = 100, reason: str = 'No reason provided'):
        if not await self._check_perms(interaction):
            await interaction.response.send_message(embed=discord.Embed(title='Access Denied', color=0xff0000), ephemeral=True)
            return
        await self._do_purge(interaction, amount, _build_check(contains=text), reason, f'Messages containing `{text}`')

    @app_commands.command(name='purgeembeds', description='Delete messages that contain embeds')
    @app_commands.describe(amount='Messages to scan (default 100)', reason='Reason')
    async def purgeembeds(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 500] = 100, reason: str = 'No reason provided'):
        if not await self._check_perms(interaction):
            await interaction.response.send_message(embed=discord.Embed(title='Access Denied', color=0xff0000), ephemeral=True)
            return
        await self._do_purge(interaction, amount, _build_check(has_embeds=True), reason, 'Messages with embeds')


async def setup(bot):
    await bot.add_cog(Purge(bot))