import discord
from discord import app_commands
from discord.ext import commands
from utils.checks import is_owner_or_admin
from utils.helpers import ACTIONS, PUNISHMENTS

class SetPunishment(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name='setpunishment', description='Set punishment for exceeding action limits')
    @app_commands.describe(
        action='The action to set a punishment for',
        punishment='The punishment to apply when the limit is exceeded'
    )
    @app_commands.choices(
        action=[
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
        ],
        punishment=[
            app_commands.Choice(name='Ban', value='ban'),
            app_commands.Choice(name='Kick', value='kick'),
            app_commands.Choice(name='Clear Roles', value='clear_roles'),
            app_commands.Choice(name='Timeout (1 day)', value='timeout'),
            app_commands.Choice(name='Warn Only', value='warn')
        ]
    )
    @is_owner_or_admin()
    async def setpunishment(self, interaction: discord.Interaction, action: str, punishment: str):
        await self.bot.db.set_punishment(interaction.guild.id, action, punishment)
        
        action_name = action.replace('_', ' ').title()
        punishment_name = punishment.replace('_', ' ').title()
        
        embed = discord.Embed(
            title="✅ Punishment Updated",
            description=f"Successfully set punishment for **{action_name}**",
            color=0x00ff00
        )
        embed.add_field(name="Action", value=action_name, inline=True)
        embed.add_field(name="Punishment", value=punishment_name, inline=True)
        embed.set_footer(text=f"Set by {interaction.user}")
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(SetPunishment(bot))
