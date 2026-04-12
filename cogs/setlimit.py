import discord
from discord import app_commands
from discord.ext import commands
from utils.checks import is_owner_or_admin
from utils.helpers import ACTIONS

class SetLimit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name='setlimit', description='Set action limits for anti-nuke protection')
    @app_commands.describe(
        action='The action to set a limit for',
        limit='The maximum number of times this action can be performed within the timeframe'
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
    async def setlimit(self, interaction: discord.Interaction, action: str, limit: int):
        if limit < 0:
            embed = discord.Embed(
                title="❌ Invalid Limit",
                description="Limit must be at least 0.\n\n**Note:** Setting limit to 0 will instantly punish any user who performs this action.",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await self.bot.db.set_limit(interaction.guild.id, action, limit)
        
        action_name = action.replace('_', ' ').title()
        
        embed = discord.Embed(
            title="✅ Limit Updated",
            description=f"Successfully set limit for **{action_name}**",
            color=0x00ff00
        )
        embed.add_field(name="Action", value=action_name, inline=True)
        embed.add_field(name="Limit", value=f"{limit}" + (" (Instant Punishment)" if limit == 0 else ""), inline=True)
        if limit == 0:
            embed.add_field(name="⚠️ Warning", value="Any user performing this action will be instantly punished!", inline=False)
        embed.set_footer(text=f"Set by {interaction.user}")
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(SetLimit(bot))
