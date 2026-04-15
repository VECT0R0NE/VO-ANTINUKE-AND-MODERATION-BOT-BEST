"""
thread_protection.py — Anti-nuke protection for Discord threads.

Monitors thread create, delete, and edit events. Integrates fully with the
existing check_and_punish pipeline, whitelist, limits, timeframes, and
punishments. Reverting thread deletion is not possible via Discord API
(threads cannot be recreated with their messages), so the bot logs the
loss and punishes the actor.
"""
import discord
from discord.ext import commands
import asyncio

BOT_NAME = "VO AntiNuke"


class ThreadProtection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _get_protection(self):
        """Return the Protection cog to use its check_and_punish and logging."""
        return self.bot.get_cog('Protection')

    # ── Thread create ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        guild = thread.guild
        protection = self._get_protection()
        if not protection:
            return

        await asyncio.sleep(0.5)
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.thread_create):
                if entry.target and entry.target.id == thread.id:
                    await protection.check_and_punish(
                        guild,
                        entry.user,
                        'creating_threads',
                        f'Created thread #{thread.name} in #{getattr(thread.parent, "name", "?")}',
                        {'thread_id': thread.id, 'thread_name': thread.name},
                    )
                    break
        except Exception as e:
            print(f'[ThreadProtection] on_thread_create error: {e}')

    # ── Thread delete ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        guild = thread.guild
        protection = self._get_protection()
        if not protection:
            return

        await asyncio.sleep(0.5)
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.thread_delete):
                if entry.target and entry.target.id == thread.id:
                    was_punished = await protection.check_and_punish(
                        guild,
                        entry.user,
                        'deleting_threads',
                        f'Deleted thread #{thread.name}',
                        {'thread_id': thread.id, 'thread_name': thread.name},
                    )
                    if was_punished:
                        # Threads cannot be restored — log the loss clearly
                        embed = discord.Embed(
                            title='⚠️ Thread Deleted — Cannot Restore',
                            description=(
                                f'Thread **#{thread.name}** was deleted by a nuker. '
                                f'Discord does not allow threads to be recreated with their history. '
                                f'The actor has been punished.'
                            ),
                            color=0xff8800,
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name='Thread', value=f'#{thread.name} (`{thread.id}`)', inline=True)
                        embed.add_field(name='Parent Channel', value=getattr(thread.parent, 'mention', 'Unknown'), inline=True)
                        embed.set_footer(text='VO AntiNuke • Thread Protection')
                        await protection.send_log_embed(guild, embed)
                    break
        except Exception as e:
            print(f'[ThreadProtection] on_thread_delete error: {e}')

    # ── Thread update ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        guild = after.guild
        protection = self._get_protection()
        if not protection:
            return

        # Only flag meaningful edits: name change, archive/lock abuse
        name_changed = before.name != after.name
        newly_locked = not before.locked and after.locked
        newly_archived = not before.archived and after.archived

        if not (name_changed or newly_locked or newly_archived):
            return

        await asyncio.sleep(0.5)
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.thread_update):
                if entry.target and entry.target.id == after.id:
                    changes = []
                    if name_changed:
                        changes.append(f'renamed to #{after.name}')
                    if newly_locked:
                        changes.append('locked')
                    if newly_archived:
                        changes.append('archived')
                    desc = ', '.join(changes)

                    await protection.check_and_punish(
                        guild,
                        entry.user,
                        'editing_threads',
                        f'Thread #{before.name}: {desc}',
                        {'thread_id': after.id, 'thread_name': before.name},
                    )
                    break
        except Exception as e:
            print(f'[ThreadProtection] on_thread_update error: {e}')


async def setup(bot):
    await bot.add_cog(ThreadProtection(bot))