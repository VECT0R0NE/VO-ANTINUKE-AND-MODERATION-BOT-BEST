"""
suspicious_setup.py — Highly customisable suspicious account detection.

Extends the existing joinlog suspicious detection with full DB-backed
configuration, auto-actions, DM messages, custom alert channels, and
role-ping. Bot ships with sensible defaults; nothing needs to be configured
for it to work. All settings are adjustable via /suspicious commands.
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import asyncio

BOT_NAME = "VO AntiNuke"

AUTO_ACTIONS = ['none', 'kick', 'ban', 'timeout']

DEFAULTS = {
    'enabled': 1,
    'min_account_age_days': 7,
    'warn_no_avatar': 1,
    'warn_new_account': 1,
    'warn_default_username': 0,
    'auto_action': 'none',
    'action_threshold_days': 3,
    'ping_role_id': None,
    'alert_channel_id': None,
    'dm_user': 1,
    'dm_message': None,
    'log_to_antinuke_channel': 1,
}


def _account_age_days(member: discord.Member) -> int:
    return (datetime.now(timezone.utc) - member.created_at).days


def _is_suspicious(member: discord.Member, cfg: dict) -> tuple[bool, list[str]]:
    flags = []
    age_days = _account_age_days(member)
    threshold = cfg.get('min_account_age_days', 7)

    if cfg.get('warn_new_account', 1) and age_days < threshold:
        flags.append(f'⚠️ Account is only **{age_days}** day(s) old (threshold: {threshold}d)')
    if cfg.get('warn_no_avatar', 1) and member.display_avatar == member.default_avatar:
        flags.append('⚠️ No custom profile picture (default avatar)')
    if cfg.get('warn_default_username', 0):
        # Discord's "new username" system uses discriminator 0 for migrated users
        if str(member).endswith('#0000') or (hasattr(member, 'discriminator') and member.discriminator == '0'):
            flags.append('⚠️ Default / unset username pattern detected')

    return bool(flags), flags


async def _can_manage(bot, interaction: discord.Interaction) -> bool:
    if interaction.user.id == interaction.guild.owner_id:
        return True
    return await bot.db.is_admin(interaction.guild.id, interaction.user.id)


class SuspiciousSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── on_member_join: run suspicious checks ─────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        cfg = await self.bot.db.get_suspicious_config(guild.id)

        if not cfg.get('enabled', 1):
            return

        is_sus, flags = _is_suspicious(member, cfg)
        if not is_sus:
            return

        age_days = _account_age_days(member)
        auto_action = cfg.get('auto_action', 'none')
        action_threshold = cfg.get('action_threshold_days', 3)

        # Build alert embed
        embed = discord.Embed(
            title='🚨 Suspicious Account Joined',
            description=f'{member.mention} (`{member.id}`) has joined with the following flags:',
            color=0xff6600,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name='🚩 Flags', value='\n'.join(flags), inline=False)
        embed.add_field(name='Account Age', value=f'{age_days} day(s)', inline=True)
        embed.add_field(name='Account Created', value=f'<t:{int(member.created_at.timestamp())}:F>', inline=True)
        embed.add_field(name='User Tag', value=str(member), inline=True)
        embed.set_footer(text=f'VO AntiNuke • Suspicious Detection | User ID: {member.id}')

        # Send to alert channel if configured
        alert_ch_id = cfg.get('alert_channel_id')
        logged = False
        if alert_ch_id:
            alert_ch = guild.get_channel(alert_ch_id)
            if alert_ch:
                try:
                    ping_role_id = cfg.get('ping_role_id')
                    ping_content = f'<@&{ping_role_id}>' if ping_role_id else None
                    await alert_ch.send(content=ping_content, embed=embed)
                    logged = True
                except Exception:
                    pass

        # Fall back to antinuke log channel
        if not logged and cfg.get('log_to_antinuke_channel', 1):
            log_channel_id = await self.bot.db.get_log_channel(guild.id)
            if log_channel_id:
                log_ch = guild.get_channel(log_channel_id)
                if log_ch:
                    try:
                        ping_role_id = cfg.get('ping_role_id')
                        ping_content = f'<@&{ping_role_id}>' if ping_role_id else None
                        await log_ch.send(content=ping_content, embed=embed)
                    except Exception:
                        pass

        # DM the user if enabled
        if cfg.get('dm_user', 1):
            custom_msg = cfg.get('dm_message')
            dm_embed = discord.Embed(
                title=f'👋 Welcome to {guild.name}',
                description=(
                    custom_msg
                    or (
                        f'Your account has been flagged as suspicious by our security system. '
                        f'If you are a real person, please wait — you will not be automatically removed. '
                        f'Contact a moderator if you have any issues.'
                    )
                ),
                color=0xffaa00,
                timestamp=discord.utils.utcnow()
            )
            try:
                await member.send(embed=dm_embed)
            except Exception:
                pass

        # Auto-action if account is extremely new (below action_threshold_days)
        if auto_action != 'none' and age_days < action_threshold:
            await asyncio.sleep(2)
            bot_me = guild.get_member(self.bot.user.id)
            if not bot_me:
                return

            action_reason = f'Suspicious account auto-action: {age_days}d old account joined'

            try:
                if auto_action == 'kick':
                    await member.kick(reason=action_reason)
                elif auto_action == 'ban':
                    await member.ban(reason=action_reason, delete_message_days=0)
                elif auto_action == 'timeout':
                    import datetime as dt
                    until = discord.utils.utcnow() + dt.timedelta(hours=24)
                    await member.timeout(until, reason=action_reason)

                action_embed = discord.Embed(
                    title=f'🤖 Suspicious Auto-Action: {auto_action.title()}',
                    description=(
                        f'{member.mention} (`{member.id}`) was automatically **{auto_action}ed** '
                        f'because their account was only **{age_days}** day(s) old '
                        f'(threshold: {action_threshold}d).'
                    ),
                    color=0xff0000,
                    timestamp=discord.utils.utcnow()
                )
                action_embed.set_footer(text='VO AntiNuke • Suspicious Auto-Action')
                log_channel_id = await self.bot.db.get_log_channel(guild.id)
                if log_channel_id:
                    log_ch = guild.get_channel(log_channel_id)
                    if log_ch:
                        try:
                            await log_ch.send(embed=action_embed)
                        except Exception:
                            pass
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f'[SuspiciousSetup] Auto-action error: {e}')

    # ── /suspicious group ─────────────────────────────────────────────────────

    suspicious = app_commands.Group(
        name='suspicious',
        description='🚨 Configure suspicious account detection'
    )

    @suspicious.command(name='status', description='📊 View current suspicious account detection settings')
    async def suspicious_status(self, interaction: discord.Interaction):
        if not await _can_manage(self.bot, interaction):
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Access Denied', color=0xff0000
            ), ephemeral=True)
            return

        cfg = await self.bot.db.get_suspicious_config(interaction.guild.id)

        def tog(v):
            return '✅' if cfg.get(v, DEFAULTS.get(v)) else '❌'

        alert_ch = interaction.guild.get_channel(cfg.get('alert_channel_id', 0)) if cfg.get('alert_channel_id') else None
        ping_role = interaction.guild.get_role(cfg.get('ping_role_id', 0)) if cfg.get('ping_role_id') else None
        auto_action = cfg.get('auto_action', 'none')
        action_threshold = cfg.get('action_threshold_days', 3)

        embed = discord.Embed(
            title='🚨 Suspicious Account Detection — Settings',
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name='Status', value=tog('enabled'), inline=True)
        embed.add_field(name='Min Account Age', value=f'{cfg.get("min_account_age_days", 7)} days', inline=True)
        embed.add_field(name='Warn New Accounts', value=tog('warn_new_account'), inline=True)
        embed.add_field(name='Warn No Avatar', value=tog('warn_no_avatar'), inline=True)
        embed.add_field(name='Warn Default Username', value=tog('warn_default_username'), inline=True)
        embed.add_field(name='DM User on Flag', value=tog('dm_user'), inline=True)
        embed.add_field(name='Log to AntiNuke Channel', value=tog('log_to_antinuke_channel'), inline=True)
        embed.add_field(name='Alert Channel', value=alert_ch.mention if alert_ch else '*(antinuke log)*', inline=True)
        embed.add_field(name='Ping Role', value=ping_role.mention if ping_role else '*(none)*', inline=True)
        embed.add_field(
            name='Auto Action',
            value=f'`{auto_action}` (if account < **{action_threshold}d** old)' if auto_action != 'none' else '*(none)*',
            inline=False
        )
        custom_dm = cfg.get('dm_message')
        embed.add_field(
            name='Custom DM Message',
            value=f'`{custom_dm[:80]}...`' if custom_dm and len(custom_dm) > 80 else (custom_dm or '*(default)*'),
            inline=False
        )
        embed.set_footer(text=f'VO AntiNuke • {interaction.guild.name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @suspicious.command(name='toggle', description='🔔 Enable or disable suspicious account detection')
    @app_commands.describe(enabled='True = enabled, False = disabled')
    async def suspicious_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not await _can_manage(self.bot, interaction):
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Access Denied', color=0xff0000
            ), ephemeral=True)
            return
        await self.bot.db.set_suspicious_config(interaction.guild.id, 'enabled', 1 if enabled else 0)
        embed = discord.Embed(
            title=f'🚨 Suspicious Detection {"Enabled" if enabled else "Disabled"}',
            color=0x57f287 if enabled else 0xff4444,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f'VO AntiNuke • {interaction.guild.name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @suspicious.command(name='setage', description='📅 Set the minimum account age to avoid being flagged')
    @app_commands.describe(days='Accounts younger than this many days will be flagged')
    async def suspicious_setage(self, interaction: discord.Interaction, days: int):
        if not await _can_manage(self.bot, interaction):
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Access Denied', color=0xff0000
            ), ephemeral=True)
            return
        if days < 1 or days > 365:
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Invalid Value', color=0xff0000,
                description='Age threshold must be between 1 and 365 days.'
            ), ephemeral=True)
            return
        await self.bot.db.set_suspicious_config(interaction.guild.id, 'min_account_age_days', days)
        embed = discord.Embed(
            title='📅 Account Age Threshold Updated',
            description=f'Accounts younger than **{days}** day(s) will now be flagged.',
            color=0x57f287, timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f'VO AntiNuke • {interaction.guild.name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @suspicious.command(name='flags', description='🚩 Toggle which checks are used to flag accounts')
    @app_commands.describe(
        warn_new_account='Flag accounts below the age threshold',
        warn_no_avatar='Flag accounts with no profile picture',
        warn_default_username='Flag accounts with default/unset usernames'
    )
    async def suspicious_flags(
        self,
        interaction: discord.Interaction,
        warn_new_account: bool = None,
        warn_no_avatar: bool = None,
        warn_default_username: bool = None,
    ):
        if not await _can_manage(self.bot, interaction):
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Access Denied', color=0xff0000
            ), ephemeral=True)
            return

        changed = []
        if warn_new_account is not None:
            await self.bot.db.set_suspicious_config(interaction.guild.id, 'warn_new_account', 1 if warn_new_account else 0)
            changed.append(f'Warn new account: {"✅" if warn_new_account else "❌"}')
        if warn_no_avatar is not None:
            await self.bot.db.set_suspicious_config(interaction.guild.id, 'warn_no_avatar', 1 if warn_no_avatar else 0)
            changed.append(f'Warn no avatar: {"✅" if warn_no_avatar else "❌"}')
        if warn_default_username is not None:
            await self.bot.db.set_suspicious_config(interaction.guild.id, 'warn_default_username', 1 if warn_default_username else 0)
            changed.append(f'Warn default username: {"✅" if warn_default_username else "❌"}')

        if not changed:
            await interaction.response.send_message(embed=discord.Embed(
                description='No flags were changed.', color=0xffcc00
            ), ephemeral=True)
            return

        embed = discord.Embed(
            title='🚩 Suspicious Flags Updated',
            description='\n'.join(changed),
            color=0x57f287, timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f'VO AntiNuke • {interaction.guild.name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @suspicious.command(name='setaction', description='⚡ Set an automatic action for very new accounts')
    @app_commands.describe(
        action='What to do automatically (none = just alert)',
        threshold_days='Only auto-act on accounts younger than this many days'
    )
    @app_commands.choices(action=[app_commands.Choice(name=a, value=a) for a in AUTO_ACTIONS])
    async def suspicious_setaction(
        self,
        interaction: discord.Interaction,
        action: str,
        threshold_days: int = 3
    ):
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Owner Only', color=0xff0000,
                description='Only the server owner can set auto-actions.'
            ), ephemeral=True)
            return
        if threshold_days < 1 or threshold_days > 30:
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Invalid Threshold', color=0xff0000,
                description='Threshold must be between 1 and 30 days.'
            ), ephemeral=True)
            return
        await self.bot.db.set_suspicious_config(interaction.guild.id, 'auto_action', action)
        await self.bot.db.set_suspicious_config(interaction.guild.id, 'action_threshold_days', threshold_days)

        embed = discord.Embed(
            title='⚡ Suspicious Auto-Action Updated',
            color=0x57f287, timestamp=discord.utils.utcnow()
        )
        if action == 'none':
            embed.description = 'Auto-action is now **disabled** — suspicious accounts will only be alerted.'
        else:
            embed.description = (
                f'Accounts younger than **{threshold_days}** day(s) will automatically be **{action}ed**.\n'
                f'Accounts between {threshold_days}–{(await self.bot.db.get_suspicious_config(interaction.guild.id)).get("min_account_age_days", 7)}d will be flagged but not actioned.'
            )
        embed.set_footer(text=f'VO AntiNuke • {interaction.guild.name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @suspicious.command(name='setalertchannel', description='📢 Set where suspicious join alerts are sent')
    @app_commands.describe(channel='Alert channel (leave blank to use antinuke log channel)')
    async def suspicious_setalertchannel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not await _can_manage(self.bot, interaction):
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Access Denied', color=0xff0000
            ), ephemeral=True)
            return
        await self.bot.db.set_suspicious_config(
            interaction.guild.id, 'alert_channel_id', channel.id if channel else None
        )
        embed = discord.Embed(
            title='📢 Suspicious Alert Channel Set',
            description=f'Alerts will be sent to {channel.mention}.' if channel else 'Alerts will use the antinuke log channel.',
            color=0x57f287, timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f'VO AntiNuke • {interaction.guild.name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @suspicious.command(name='setpingrole', description='🔔 Set a role to ping when a suspicious account joins')
    @app_commands.describe(role='Role to ping (leave blank to clear)')
    async def suspicious_setpingrole(self, interaction: discord.Interaction, role: discord.Role = None):
        if not await _can_manage(self.bot, interaction):
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Access Denied', color=0xff0000
            ), ephemeral=True)
            return
        await self.bot.db.set_suspicious_config(
            interaction.guild.id, 'ping_role_id', role.id if role else None
        )
        embed = discord.Embed(
            title='🔔 Suspicious Ping Role Updated',
            description=f'{role.mention} will be pinged on suspicious joins.' if role else 'Ping role cleared.',
            color=0x57f287, timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f'VO AntiNuke • {interaction.guild.name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @suspicious.command(name='setdm', description='💬 Customise the DM sent to flagged accounts')
    @app_commands.describe(
        enabled='Whether to DM flagged users at all',
        message='Custom DM message (leave blank to use default)'
    )
    async def suspicious_setdm(
        self,
        interaction: discord.Interaction,
        enabled: bool = None,
        message: str = None
    ):
        if not await _can_manage(self.bot, interaction):
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Access Denied', color=0xff0000
            ), ephemeral=True)
            return

        if enabled is not None:
            await self.bot.db.set_suspicious_config(interaction.guild.id, 'dm_user', 1 if enabled else 0)
        if message is not None:
            await self.bot.db.set_suspicious_config(interaction.guild.id, 'dm_message', message if message else None)

        embed = discord.Embed(
            title='💬 Suspicious DM Settings Updated',
            color=0x57f287, timestamp=discord.utils.utcnow()
        )
        if enabled is not None:
            embed.add_field(name='DM Enabled', value='✅' if enabled else '❌', inline=True)
        if message is not None:
            embed.add_field(name='Custom Message', value=message[:200] if message else '*(cleared, using default)*', inline=False)
        embed.set_footer(text=f'VO AntiNuke • {interaction.guild.name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @suspicious.command(name='reset', description='🔄 Reset all suspicious detection settings to defaults')
    async def suspicious_reset(self, interaction: discord.Interaction):
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Owner Only', color=0xff0000
            ), ephemeral=True)
            return
        for key, value in DEFAULTS.items():
            await self.bot.db.set_suspicious_config(interaction.guild.id, key, value)
        embed = discord.Embed(
            title='🔄 Suspicious Detection Reset',
            description='All suspicious account detection settings have been restored to defaults.',
            color=0x57f287, timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f'VO AntiNuke • {interaction.guild.name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(SuspiciousSetup(bot))