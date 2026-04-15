import discord
from discord import app_commands
from discord.ext import commands
from utils.checks import is_owner_or_admin
from utils.helpers import parse_time, format_time, ACTIONS

class SetTime(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name='settime', description='Set timeframe for action limits')
    @app_commands.describe(
        action='The action to set a timeframe for',
        timeframe='Time format: 1s/1m/1h/1d/1w/1mo/1y (e.g., 5m, 1h, 2d)'
    )
    @app_commands.choices(action=[
        app_commands.Choice(name='Banning Members', value='banning_members'),
        app_commands.Choice(name='Kicking Members', value='kicking_members'),
        app_commands.Choice(name='Pruning Members', value='pruning_members'),
        app_commands.Choice(name='Creating Channels', value='creating_channels'),
        app_commands.Choice(name='Deleting Channels', value='deleting_channels'),
        app_commands.Choice(name='Creating Roles', value='creating_roles'),
        app_commands.Choice(name='Deleting Roles', value='deleting_roles'),
        app_commands.Choice(name='Authorizing Applications', value='authorizing_applications'),
        app_commands.Choice(name='Giving Dangerous Permissions', value='giving_dangerous_permissions'),
        app_commands.Choice(name='Giving Administrative Roles', value='giving_administrative_roles'),
        app_commands.Choice(name='Editing Channels', value='editing_channels'),
        app_commands.Choice(name='Editing Roles', value='editing_roles'),
        app_commands.Choice(name='Adding Bots', value='adding_bots'),
        app_commands.Choice(name='Updating Server', value='updating_server'),
        app_commands.Choice(name='Creating Webhooks', value='creating_webhooks'),
        app_commands.Choice(name='Deleting Webhooks', value='deleting_webhooks'),
        app_commands.Choice(name='Timing Out Members', value='timing_out_members'),
        app_commands.Choice(name='Changing Nicknames', value='changing_nicknames'),
    ])
    @is_owner_or_admin()
    async def settime(self, interaction: discord.Interaction, action: str, timeframe: str):
        await interaction.response.defer()
        seconds = parse_time(timeframe)
        
        if seconds is None or seconds < 1:
            embed = discord.Embed(
                title="❌ Invalid Timeframe",
                description="Please use valid time format:\n`1s` = 1 second\n`1m` = 1 minute\n`1h` = 1 hour\n`1d` = 1 day\n`1w` = 1 week\n`1mo` = 1 month\n`1y` = 1 year\n\nExample: `5m`, `1h`, `2d`",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        await self.bot.db.set_timeframe(interaction.guild.id, action, seconds)
        
        action_name = action.replace('_', ' ').title()
        
        embed = discord.Embed(
            title="✅ Timeframe Updated",
            description=f"Successfully set timeframe for **{action_name}**",
            color=0x00ff00
        )
        embed.add_field(name="Action", value=action_name, inline=True)
        embed.add_field(name="Timeframe", value=format_time(seconds), inline=True)
        embed.set_footer(text=f"Set by {interaction.user}")
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(SetTime(bot))
