import discord
from discord import app_commands
from discord.ext import commands
import time
import math

BOT_NAME = "VO AntiNuke"
NOTES_PER_PAGE = 5


async def _send_mod_log(bot, guild: discord.Guild, embed: discord.Embed):
    log_channel_id = await bot.db.get_log_channel(guild.id)
    if log_channel_id:
        ch = guild.get_channel(log_channel_id)
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass


def _has_mod_perms(interaction: discord.Interaction) -> bool:
    return (
        interaction.user.guild_permissions.manage_messages
        or interaction.user.id == interaction.guild.owner_id
    )


def _build_notes_embed(user: discord.Member, notes: list, page: int, total_pages: int) -> discord.Embed:
    start = (page - 1) * NOTES_PER_PAGE
    end = start + NOTES_PER_PAGE
    page_notes = notes[start:end]

    embed = discord.Embed(
        title=f"📝 Staff Notes — {user.display_name}",
        description=f"**{len(notes)}** note(s) on record | Page **{page}/{total_pages}**",
        color=0x5865f2,
        timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    for n in page_notes:
        embed.add_field(
            name=f"#{n['id']} — <t:{n['timestamp']}:d> | Mod ID: {n['moderator_id']}",
            value=n['note'][:512],
            inline=False
        )

    embed.set_footer(text=f"User ID: {user.id} | {BOT_NAME} • Notes  •  Page {page}/{total_pages}")
    return embed


class NotesPaginator(discord.ui.View):
    def __init__(self, user: discord.Member, notes: list, page: int = 1):
        super().__init__(timeout=120)
        self.user = user
        self.notes = notes
        self.page = page
        self.total_pages = math.ceil(len(notes) / NOTES_PER_PAGE)
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.page <= 1
        self.next_btn.disabled = self.page >= self.total_pages
        self.page_label.label = f"Page {self.page}/{self.total_pages}"

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(
            embed=_build_notes_embed(self.user, self.notes, self.page, self.total_pages),
            view=self
        )

    @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(
            embed=_build_notes_embed(self.user, self.notes, self.page, self.total_pages),
            view=self
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class Notes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='note', description='📝 Add or manage internal staff notes on a user')
    @app_commands.describe(
        action='What to do: add, view, remove, or clear',
        user='The target user',
        text='The note text (required for add)',
        note_id='Note ID to remove (required for remove)'
    )
    @app_commands.choices(action=[
        app_commands.Choice(name='add', value='add'),
        app_commands.Choice(name='view', value='view'),
        app_commands.Choice(name='remove', value='remove'),
        app_commands.Choice(name='clear', value='clear'),
    ])
    async def note(
        self,
        interaction: discord.Interaction,
        action: str,
        user: discord.Member,
        text: str = None,
        note_id: int = None
    ):
        is_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not (_has_mod_perms(interaction) or is_admin):
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Manage Messages** permission or be a bot admin to use notes.",
                color=0xff0000
            ), ephemeral=True)
            return

        if action == 'add':
            if not text:
                await interaction.response.send_message(embed=discord.Embed(
                    title="❌ Missing Text",
                    description="Provide note text. Example: `/note action:add @user text:They were warned for spam`",
                    color=0xff0000
                ), ephemeral=True)
                return

            nid = await self.bot.db.add_note(interaction.guild.id, user.id, interaction.user.id, text)
            total = await self.bot.db.get_notes(interaction.guild.id, user.id)

            embed = discord.Embed(
                title="📝 Note Added",
                color=0x5865f2,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="👤 User", value=f"{user.mention}\n`{user.id}`", inline=True)
            embed.add_field(name="🆔 Note ID", value=f"`#{nid}`", inline=True)
            embed.add_field(name="📊 Total Notes", value=str(len(total)), inline=True)
            embed.add_field(name="📋 Note", value=text[:1024], inline=False)
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=f"Added by {interaction.user} | {BOT_NAME}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

            # Log to mod log
            log_embed = discord.Embed(
                title="📝 Staff Note Added",
                color=0x5865f2,
                timestamp=discord.utils.utcnow()
            )
            log_embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
            log_embed.add_field(name="Added By", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=True)
            log_embed.add_field(name="Note ID", value=f"#{nid}", inline=True)
            log_embed.add_field(name="Note", value=text[:512], inline=False)
            log_embed.set_footer(text=f"User ID: {user.id} | {BOT_NAME}")
            await _send_mod_log(self.bot, interaction.guild, log_embed)

        elif action == 'view':
            notes = await self.bot.db.get_notes(interaction.guild.id, user.id)

            if not notes:
                await interaction.response.send_message(embed=discord.Embed(
                    title=f"📝 Notes — {user.display_name}",
                    description="No notes on record for this user.",
                    color=0x57f287
                ), ephemeral=True)
                return

            total_pages = math.ceil(len(notes) / NOTES_PER_PAGE)
            embed = _build_notes_embed(user, notes, 1, total_pages)

            if total_pages > 1:
                view = NotesPaginator(user, notes)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

        elif action == 'remove':
            if note_id is None:
                await interaction.response.send_message(embed=discord.Embed(
                    title="❌ Missing Note ID",
                    description="Provide `note_id` to remove. Use `/note action:view @user` to see IDs.",
                    color=0xff0000
                ), ephemeral=True)
                return

            removed = await self.bot.db.remove_note(interaction.guild.id, note_id)
            if not removed:
                await interaction.response.send_message(embed=discord.Embed(
                    title="❌ Not Found",
                    description=f"No note with ID `#{note_id}` found in this server.",
                    color=0xff0000
                ), ephemeral=True)
                return

            await interaction.response.send_message(embed=discord.Embed(
                title="🗑️ Note Removed",
                description=f"Note `#{note_id}` for {user.mention} has been deleted.",
                color=0x57f287,
                timestamp=discord.utils.utcnow()
            ), ephemeral=True)

            log_embed = discord.Embed(title="🗑️ Staff Note Removed", color=0xff8800, timestamp=discord.utils.utcnow())
            log_embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
            log_embed.add_field(name="Removed By", value=f"{interaction.user.mention}", inline=True)
            log_embed.add_field(name="Note ID", value=f"#{note_id}", inline=True)
            log_embed.set_footer(text=f"User ID: {user.id} | {BOT_NAME}")
            await _send_mod_log(self.bot, interaction.guild, log_embed)

        elif action == 'clear':
            count = await self.bot.db.clear_notes(interaction.guild.id, user.id)
            if count == 0:
                await interaction.response.send_message(embed=discord.Embed(
                    description=f"ℹ️ {user.mention} has no notes to clear.",
                    color=0x5865f2
                ), ephemeral=True)
                return

            await interaction.response.send_message(embed=discord.Embed(
                title="🧹 Notes Cleared",
                description=f"All **{count}** note(s) for {user.mention} have been removed.",
                color=0x57f287,
                timestamp=discord.utils.utcnow()
            ), ephemeral=True)

            log_embed = discord.Embed(title="🧹 All Staff Notes Cleared", color=0xff8800, timestamp=discord.utils.utcnow())
            log_embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
            log_embed.add_field(name="Cleared By", value=interaction.user.mention, inline=True)
            log_embed.add_field(name="Notes Removed", value=str(count), inline=True)
            log_embed.set_footer(text=f"User ID: {user.id} | {BOT_NAME}")
            await _send_mod_log(self.bot, interaction.guild, log_embed)


async def setup(bot):
    await bot.add_cog(Notes(bot))
