import discord
from discord import app_commands
from discord.ext import commands
import json
import time
from utils.checks import is_owner_or_admin

MAX_BACKUPS = 10


class SaveServerSettings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='saveserversettings', description='Save a server backup (channels, roles, emojis). Max 10 backups.')
    @app_commands.describe(label='Optional label to identify this backup')
    @is_owner_or_admin()
    async def saveserversettings(self, interaction: discord.Interaction, label: str = ''):
        await interaction.response.defer()
        guild = interaction.guild

        count = await self.bot.db.count_server_backups(guild.id)
        if count >= MAX_BACKUPS:
            # Will auto-delete oldest — warn user
            embed_warn = discord.Embed(
                title="⚠️ Backup Limit Reached",
                description=(
                    f"You have **{count}/{MAX_BACKUPS}** backups. "
                    "The **oldest** backup will be automatically deleted to make room."
                ),
                color=0xffaa00
            )
            await interaction.followup.send(embed=embed_warn)

        backup_data = {
            'guild_id': guild.id,
            'guild_name': guild.name,
            'vanity_url': guild.vanity_url_code,
            'icon_url': str(guild.icon.url) if guild.icon else None,
            'banner_url': str(guild.banner.url) if guild.banner else None,
            'description': guild.description,
            'channels': [],
            'roles': [],
            'emojis': []
        }

        for channel in guild.channels:
            channel_data = {
                'id': channel.id,
                'name': channel.name,
                'type': str(channel.type),
                'position': channel.position,
                'category_id': channel.category.id if channel.category else None,
                'overwrites': {}
            }
            if isinstance(channel, discord.TextChannel):
                channel_data['topic'] = channel.topic
                channel_data['slowmode_delay'] = channel.slowmode_delay
                channel_data['nsfw'] = channel.nsfw
            elif isinstance(channel, discord.VoiceChannel):
                channel_data['bitrate'] = channel.bitrate
                channel_data['user_limit'] = channel.user_limit

            for target, overwrite in channel.overwrites.items():
                key = f"role_{target.id}" if isinstance(target, discord.Role) else f"member_{target.id}"
                channel_data['overwrites'][key] = {
                    'allow': overwrite.pair()[0].value,
                    'deny': overwrite.pair()[1].value
                }
            backup_data['channels'].append(channel_data)

        for role in guild.roles:
            if role != guild.default_role:
                backup_data['roles'].append({
                    'id': role.id,
                    'name': role.name,
                    'color': role.color.value,
                    'permissions': role.permissions.value,
                    'position': role.position,
                    'hoist': role.hoist,
                    'mentionable': role.mentionable
                })

        for emoji in guild.emojis:
            backup_data['emojis'].append({
                'id': emoji.id,
                'name': emoji.name,
                'animated': emoji.animated,
                'url': str(emoji.url)
            })

        timestamp = int(time.time())
        await self.bot.db.save_server_backup(guild.id, json.dumps(backup_data), timestamp, label)

        new_count = await self.bot.db.count_server_backups(guild.id)
        embed = discord.Embed(
            title="✅ Server Backup Saved",
            description=f"Backup **{label or 'Untitled'}** saved successfully.",
            color=0x00ff00
        )
        embed.add_field(name="📁 Channels", value=str(len(backup_data['channels'])), inline=True)
        embed.add_field(name="🏷️ Roles", value=str(len(backup_data['roles'])), inline=True)
        embed.add_field(name="😀 Emojis", value=str(len(backup_data['emojis'])), inline=True)
        embed.add_field(name="🕒 Timestamp", value=f"<t:{timestamp}:F>", inline=False)
        embed.add_field(name="📦 Backups Used", value=f"{new_count}/{MAX_BACKUPS}", inline=True)
        embed.set_footer(text=f"Saved by {interaction.user}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name='listbackups', description='List all saved server backups')
    @is_owner_or_admin()
    async def listbackups(self, interaction: discord.Interaction):
        backups = await self.bot.db.list_server_backups(interaction.guild.id)

        if not backups:
            await interaction.response.send_message(embed=discord.Embed(
                title="📦 No Backups Found",
                description="No backups have been saved. Use `/saveserversettings` to create one.",
                color=0xffaa00), ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📦 Server Backups ({len(backups)}/{MAX_BACKUPS})",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        for b in backups:
            label = b['label'] or 'Untitled'
            embed.add_field(
                name=f"ID #{b['id']} — {label}",
                value=f"Saved: <t:{b['timestamp']}:R> (<t:{b['timestamp']}:f>)",
                inline=False
            )
        embed.set_footer(text="Use /deletebackup <id> to remove | /loadfromsave <id> to restore")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='deletebackup', description='Delete a specific server backup by ID')
    @app_commands.describe(backup_id='The backup ID (from /listbackups)')
    @is_owner_or_admin()
    async def deletebackup(self, interaction: discord.Interaction, backup_id: int):
        deleted = await self.bot.db.delete_server_backup(interaction.guild.id, backup_id)
        if not deleted:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Backup Not Found",
                description=f"No backup with ID **#{backup_id}** exists for this server.",
                color=0xff0000), ephemeral=True)
            return

        embed = discord.Embed(
            title="🗑️ Backup Deleted",
            description=f"Backup **#{backup_id}** has been permanently deleted.",
            color=0x00ff00
        )
        embed.set_footer(text=f"Deleted by {interaction.user}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(SaveServerSettings(bot))
