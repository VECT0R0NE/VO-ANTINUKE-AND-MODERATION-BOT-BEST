import discord
from discord.ext import commands
import asyncio
import os
from utils.database import Database
from utils.warns_database import WarnsDatabase
from utils.jail_database import JailDatabase

# Load token from environment variable (set in .env or your host's env settings)
TOKEN = os.environ.get('DISCORD_TOKEN', 'set ur token here')
APPLICATION_ID = int(os.environ.get('APPLICATION_ID', 'set ur application id here'))

intents = discord.Intents.all()


async def get_prefix(bot, message):
    if message.guild:
        prefix = await bot.db.get_prefix(message.guild.id)
        return prefix or '!'
    return '!'


class AntiNukeBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=get_prefix,
            intents=intents,
            application_id=APPLICATION_ID,
            help_command=None
        )
        self.db = Database()
        self.warns_db = WarnsDatabase()
        self.jail_db = JailDatabase()

    async def setup_hook(self):
        await self.db.initialize()
        await self.warns_db.initialize()
        await self.jail_db.initialize()

        cogs = [
            # Anti-nuke core
            'cogs.setlimit',
            'cogs.settime',
            'cogs.setpunishment',
            'cogs.whitelist',
            'cogs.unwhitelist',
            'cogs.addadmin',
            'cogs.saveserversettings',
            'cogs.loadfromsave',
            'cogs.protection',
            'cogs.protectiontoggle',
            'cogs.dmalerts',
            'cogs.configexport',
            # Moderation
            'cogs.ban',
            'cogs.kick',
            'cogs.warn',
            'cogs.nuke',
            'cogs.jail',
            'cogs.moderation',
            # Information
            'cogs.info',
            # Configuration
            'cogs.changeprefix',
            'cogs.moderationlog',
            'cogs.invite',
            # Help
            'cogs.help',
            # Settings / status
            'cogs.antinukesettings',
            # New features
            'cogs.notes',
            'cogs.tempban',
            'cogs.purge',
            'cogs.serverauditlog',
            'cogs.msglog',
            'cogs.joinlog',
            'cogs.role_persistence',
            'cogs.suspicious_setup',
            'cogs.thread_protection',
            # New features (Phase 2)
            'cogs.trustedrole',
            'cogs.massunban',
            'cogs.logfilters',
            'cogs.logsearch',
            'cogs.invitetracker',
        ]

        for cog in cogs:
            try:
                await self.load_extension(cog)
                print(f'✓ Loaded {cog}')
            except Exception as e:
                print(f'✗ Failed to load {cog}: {e}')

        synced = await self.tree.sync()
        print(f'✓ Synced {len(synced)} slash commands')

    async def on_ready(self):
        print(f'\n{"=" * 50}')
        print(f'Bot:     {self.user.name}')
        print(f'ID:      {self.user.id}')
        print(f'Servers: {len(self.guilds)}')
        print(f'{"=" * 50}\n')

        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="for threats | /help"
        )
        await self.change_presence(activity=activity, status=discord.Status.dnd)


bot = AntiNukeBot()

if __name__ == '__main__':
    if not TOKEN or TOKEN == '':
        print('Error: Please set your bot token in bot.py (TOKEN variable)')
    else:
        bot.run(TOKEN)