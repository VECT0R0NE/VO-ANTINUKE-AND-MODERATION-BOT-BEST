import discord
from discord import app_commands
from discord.ext import commands
import json
import io
import time
from utils.checks import is_owner_or_admin
from utils.helpers import ACTIONS, PUNISHMENTS

EXPORT_FILE_EXTENSION = '.antinuke'
MAX_IMPORT_BYTES = 50_000  # 50 KB hard limit


class ConfigExport(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='exportconfig', description='Export your anti-nuke settings as a file')
    @is_owner_or_admin()
    async def exportconfig(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id

        config = {
            'version': 1,
            'exported_at': int(time.time()),
            'guild_name': interaction.guild.name,
            'actions': {}
        }

        for action in ACTIONS:
            limit = await self.bot.db.get_limit(guild_id, action)
            timeframe = await self.bot.db.get_timeframe(guild_id, action)
            punishment = await self.bot.db.get_punishment(guild_id, action)
            enabled = await self.bot.db.is_protection_enabled(guild_id, action)
            config['actions'][action] = {
                'limit': limit,
                'timeframe': timeframe,
                'punishment': punishment,
                'enabled': enabled
            }

        json_bytes = json.dumps(config, indent=2).encode('utf-8')
        file = discord.File(
            fp=io.BytesIO(json_bytes),
            filename=f"antinuke_config_{interaction.guild.id}{EXPORT_FILE_EXTENSION}"
        )

        embed = discord.Embed(
            title="📤 Config Exported",
            description=(
                "Your anti-nuke settings have been exported.\n"
                f"Use `/importconfig` and attach this `{EXPORT_FILE_EXTENSION}` file to import it on another server."
            ),
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Actions Exported", value=str(len(config['actions'])), inline=True)
        embed.add_field(name="File", value=f"`antinuke_config_{interaction.guild.id}{EXPORT_FILE_EXTENSION}`", inline=True)
        embed.set_footer(text=f"Exported by {interaction.user}")
        await interaction.followup.send(embed=embed, file=file, ephemeral=True)

    @app_commands.command(name='importconfig', description='Import anti-nuke settings from an exported .antinuke file')
    @is_owner_or_admin()
    async def importconfig(self, interaction: discord.Interaction, file: discord.Attachment):
        await interaction.response.defer()
        # Validate file
        if not file.filename.endswith(EXPORT_FILE_EXTENSION):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Invalid File Type",
                description=(
                    f"Only `{EXPORT_FILE_EXTENSION}` files are accepted.\n"
                    "Export your config first using `/exportconfig`."
                ),
                color=0xff0000), ephemeral=True)
            return

        if file.size > MAX_IMPORT_BYTES:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ File Too Large",
                description=f"Config file must be under **{MAX_IMPORT_BYTES // 1000} KB**.",
                color=0xff0000), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            raw = await file.read()
            config = json.loads(raw.decode('utf-8'))
        except Exception:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Invalid File",
                description="Could not parse the config file. Make sure it's a valid exported config.",
                color=0xff0000), ephemeral=True)
            return

        # Validate structure
        if config.get('version') != 1 or 'actions' not in config:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Invalid Config Format",
                description="This file doesn't look like a valid anti-nuke config. Export a fresh one with `/exportconfig`.",
                color=0xff0000), ephemeral=True)
            return

        guild_id = interaction.guild.id
        imported = 0
        skipped = 0

        for action, settings in config['actions'].items():
            if action not in ACTIONS:
                skipped += 1
                continue

            limit = settings.get('limit')
            timeframe = settings.get('timeframe')
            punishment = settings.get('punishment')
            enabled = settings.get('enabled', True)

            # Validate values before writing
            if not isinstance(limit, int) or limit < 0:
                skipped += 1
                continue
            if not isinstance(timeframe, int) or timeframe < 1:
                skipped += 1
                continue
            if punishment not in PUNISHMENTS:
                skipped += 1
                continue

            await self.bot.db.set_limit(guild_id, action, limit)
            await self.bot.db.set_timeframe(guild_id, action, timeframe)
            await self.bot.db.set_punishment(guild_id, action, punishment)
            await self.bot.db.set_protection_enabled(guild_id, action, bool(enabled))
            imported += 1

        source_guild = config.get('guild_name', 'Unknown Server')
        exported_at = config.get('exported_at', 0)

        embed = discord.Embed(
            title="📥 Config Imported",
            description=f"Successfully imported anti-nuke settings from **{source_guild}**.",
            color=0x00ff00,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="✅ Imported", value=str(imported), inline=True)
        embed.add_field(name="⚠️ Skipped", value=str(skipped), inline=True)
        if exported_at:
            embed.add_field(name="📅 Originally Exported", value=f"<t:{exported_at}:R>", inline=True)
        embed.set_footer(text=f"Imported by {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ConfigExport(bot))
