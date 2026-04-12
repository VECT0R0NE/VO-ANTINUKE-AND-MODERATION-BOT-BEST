"""
role_persistence.py — Reapplies mute (timeout) and jail roles when a
persistenced user rejoins the server. Hooks into on_member_join and
integrates with the existing Jail and moderation cogs without breaking them.
"""
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import time

BOT_NAME = "VO AntiNuke"

# Role-type constants — shared with jail.py / moderation.py
ROLE_TYPE_JAIL = "jail"
ROLE_TYPE_MUTE = "mute"


class RolePersistence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _log(self, guild: discord.Guild, embed: discord.Embed):
        log_channel_id = await self.bot.db.get_log_channel(guild.id)
        if log_channel_id:
            ch = guild.get_channel(log_channel_id)
            if ch:
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

    # ── on_member_join: reapply persistent roles ──────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        user_id = member.id
        guild_id = guild.id

        records = await self.bot.db.get_role_persistence(guild_id, user_id)
        if not records:
            return

        await asyncio.sleep(1)  # brief delay so Discord's member cache settles

        for record in records:
            role_type = record['role_type']

            if role_type == ROLE_TYPE_JAIL:
                await self._reapply_jail(guild, member, record)

            elif role_type == ROLE_TYPE_MUTE:
                await self._reapply_mute(guild, member, record)

    async def _reapply_jail(self, guild: discord.Guild, member: discord.Member, record: dict):
        """Re-apply the jail role and strip all other roles."""
        jail_role_id = record.get('role_id')
        if not jail_role_id:
            return

        jail_role = guild.get_role(jail_role_id)
        if not jail_role:
            # Try to find by name as fallback
            jail_role = discord.utils.get(guild.roles, name='Jailed')
            if not jail_role:
                return

        bot_me = guild.get_member(self.bot.user.id)
        if not bot_me:
            return

        try:
            # Remove all current roles (except @everyone and roles above bot)
            removable = [
                r for r in member.roles
                if r != guild.default_role and r < bot_me.top_role and r != jail_role
            ]
            if removable:
                await member.remove_roles(*removable, reason='Role Persistence: re-jailing rejoined member')

            if jail_role not in member.roles and jail_role < bot_me.top_role:
                await member.add_roles(jail_role, reason='Role Persistence: re-jailing rejoined member')

            embed = discord.Embed(
                title='🔒 Role Persistence — Jail Reapplied',
                description=(
                    f'{member.mention} (`{member.id}`) left and rejoined while jailed. '
                    f'The **{jail_role.name}** role has been automatically reapplied.'
                ),
                color=0xff4444,
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name='User', value=f'{member} (`{member.id}`)', inline=True)
            embed.add_field(name='Jail Role', value=jail_role.mention, inline=True)
            embed.set_footer(text=f'VO AntiNuke • Role Persistence')
            await self._log(guild, embed)

            # DM the user
            try:
                dm_embed = discord.Embed(
                    title=f'🔒 You Have Been Re-Jailed in {guild.name}',
                    description=(
                        'You left the server while jailed and have been automatically '
                        're-jailed upon rejoining. Contact a moderator for more information.'
                    ),
                    color=0xff4444,
                    timestamp=discord.utils.utcnow()
                )
                await member.send(embed=dm_embed)
            except Exception:
                pass

        except discord.Forbidden:
            pass
        except Exception as e:
            print(f'[RolePersistence] Jail reapply error: {e}')

    async def _reapply_mute(self, guild: discord.Guild, member: discord.Member, record: dict):
        """Re-apply a Discord timeout (mute persistence)."""
        extra = record.get('extra', {})
        expires_at = extra.get('expires_at')

        if expires_at and expires_at <= time.time():
            # Mute has already expired — clean up and skip
            await self.bot.db.remove_role_persistence(guild.id, member.id, ROLE_TYPE_MUTE)
            return

        try:
            if expires_at:
                import datetime
                until = discord.utils.utcnow() + datetime.timedelta(
                    seconds=int(expires_at - time.time())
                )
                # Cap at Discord's 28-day limit
                max_until = discord.utils.utcnow() + datetime.timedelta(days=28)
                if until > max_until:
                    until = max_until
            else:
                # Permanent mute — use max Discord allows
                import datetime
                until = discord.utils.utcnow() + datetime.timedelta(days=28)

            await member.timeout(until, reason='Role Persistence: re-muting rejoined member')

            embed = discord.Embed(
                title='🔇 Role Persistence — Mute Reapplied',
                description=(
                    f'{member.mention} (`{member.id}`) left and rejoined while muted. '
                    f'Timeout has been automatically reapplied.'
                ),
                color=0xffaa00,
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name='User', value=f'{member} (`{member.id}`)', inline=True)
            embed.add_field(
                name='Muted Until',
                value=f'<t:{int(until.timestamp())}:F>' if expires_at else 'Max (28 days)',
                inline=True
            )
            embed.set_footer(text='VO AntiNuke • Role Persistence')
            await self._log(guild, embed)

            try:
                dm_embed = discord.Embed(
                    title=f'🔇 You Have Been Re-Muted in {guild.name}',
                    description=(
                        'You left the server while muted and have been automatically '
                        're-muted upon rejoining. Contact a moderator for more information.'
                    ),
                    color=0xffaa00,
                    timestamp=discord.utils.utcnow()
                )
                await member.send(embed=dm_embed)
            except Exception:
                pass

        except discord.Forbidden:
            pass
        except Exception as e:
            print(f'[RolePersistence] Mute reapply error: {e}')

    # ── /persistence group ────────────────────────────────────────────────────

    persistence = app_commands.Group(
        name='persistence',
        description='🔒 View and manage role persistence records'
    )

    @persistence.command(name='list', description='📋 List all members with active role persistence')
    async def persistence_list(self, interaction: discord.Interaction):
        is_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.id == interaction.guild.owner_id
            or is_admin
        ):
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Access Denied', color=0xff0000
            ), ephemeral=True)
            return

        # Fetch all from DB (read all role_persistence rows for this guild)
        rows = await self.bot.db._fetchall(
            'SELECT user_id, role_type, role_id, added_at FROM role_persistence WHERE guild_id=? ORDER BY added_at DESC',
            (interaction.guild.id,)
        )

        embed = discord.Embed(
            title='🔒 Active Role Persistence Records',
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )

        if not rows:
            embed.description = 'No role persistence records found.'
        else:
            lines = []
            for row in rows[:20]:
                uid, rtype, role_id, added_at = row
                member = interaction.guild.get_member(uid)
                name = member.mention if member else f'`{uid}` *(not in server)*'
                type_emoji = '🔒' if rtype == ROLE_TYPE_JAIL else '🔇'
                lines.append(f'{type_emoji} {name} — **{rtype}** — <t:{added_at}:R>')
            embed.description = '\n'.join(lines)
            if len(rows) > 20:
                embed.set_footer(text=f'Showing 20 of {len(rows)} records | VO AntiNuke')
            else:
                embed.set_footer(text='VO AntiNuke • Role Persistence')

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @persistence.command(name='remove', description='🗑️ Remove a role persistence record for a user')
    @app_commands.describe(
        user='User to remove persistence for',
        role_type='Which persistence type to remove'
    )
    @app_commands.choices(role_type=[
        app_commands.Choice(name='Jail', value=ROLE_TYPE_JAIL),
        app_commands.Choice(name='Mute', value=ROLE_TYPE_MUTE),
        app_commands.Choice(name='All', value='all'),
    ])
    async def persistence_remove(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        role_type: str = 'all'
    ):
        is_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.id == interaction.guild.owner_id
            or is_admin
        ):
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Access Denied', color=0xff0000
            ), ephemeral=True)
            return

        if role_type == 'all':
            await self.bot.db.remove_all_role_persistence(interaction.guild.id, user.id)
            desc = f'All role persistence records for {user.mention} have been removed.'
        else:
            await self.bot.db.remove_role_persistence(interaction.guild.id, user.id, role_type)
            desc = f'**{role_type}** persistence record for {user.mention} has been removed.'

        embed = discord.Embed(
            title='🗑️ Role Persistence Removed',
            description=desc,
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f'VO AntiNuke • {interaction.guild.name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @persistence.command(name='check', description='🔍 Check role persistence status for a user')
    @app_commands.describe(user='User to check')
    async def persistence_check(self, interaction: discord.Interaction, user: discord.Member):
        is_admin = await self.bot.db.is_admin(interaction.guild.id, interaction.user.id)
        if not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.id == interaction.guild.owner_id
            or is_admin
        ):
            await interaction.response.send_message(embed=discord.Embed(
                title='❌ Access Denied', color=0xff0000
            ), ephemeral=True)
            return

        records = await self.bot.db.get_role_persistence(interaction.guild.id, user.id)

        embed = discord.Embed(
            title=f'🔒 Role Persistence: {user}',
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        if not records:
            embed.description = f'No role persistence records for {user.mention}.'
        else:
            for record in records:
                rtype = record['role_type']
                emoji = '🔒' if rtype == ROLE_TYPE_JAIL else '🔇'
                role = interaction.guild.get_role(record['role_id'])
                role_str = role.mention if role else f'`{record["role_id"]}`'
                extra = record.get('extra', {})
                expires = extra.get('expires_at')
                expiry_str = f'<t:{int(expires)}:F>' if expires else 'Indefinite'
                embed.add_field(
                    name=f'{emoji} {rtype.title()}',
                    value=f'Role: {role_str}\nExpires: {expiry_str}\nAdded: <t:{record["added_at"]}:R>',
                    inline=True
                )

        embed.set_footer(text=f'VO AntiNuke • {interaction.guild.name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(RolePersistence(bot))