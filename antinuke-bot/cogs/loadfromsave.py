import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
import aiohttp
from utils.checks import is_owner_or_admin


class LoadFromSave(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending_loads: dict = {}  # (user_id, guild_id) -> actual_backup_id

    # ──────────────────────────────────────────────────────────────────────────
    # Slash command entry point
    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name='loadfromsave',
        description='Load server from a backup by ID (WARNING: destructive)'
    )
    @app_commands.describe(backup_id='Backup ID from /listbackups (leave empty for latest)')
    @is_owner_or_admin()
    async def loadfromsave(self, interaction: discord.Interaction, backup_id: int = None):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        backup_result = await self.bot.db.get_server_backup(guild.id, backup_id)

        if not backup_result:
            msg = (
                f"No backup with ID **#{backup_id}** found." if backup_id
                else "No backups exist for this server. Use `/saveserversettings` first."
            )
            await interaction.followup.send(embed=discord.Embed(
                title="❌ No Backup Found", description=msg, color=0xff0000), ephemeral=True)
            return

        actual_id = backup_result[0]
        pending_key = (interaction.user.id, guild.id)

        # ── Confirmation gate: run the command twice within 60 s to confirm ──
        if self.pending_loads.get(pending_key) == actual_id:
            self.pending_loads.pop(pending_key, None)
            await self._perform_load(interaction, backup_result)
            return

        self.pending_loads[pending_key] = actual_id

        backup_data = json.loads(backup_result[1])
        timestamp = backup_result[2]
        label = backup_result[3] or 'Untitled'

        embed = discord.Embed(
            title="⚠️ WARNING: Server Restore",
            description="**This will delete ALL current channels and roles, then restore from backup!**",
            color=0xff0000
        )
        embed.add_field(
            name="⚠️ DANGER",
            value=(
                "This action will:\n"
                "• Delete all current channels\n"
                "• Delete all current roles (except @everyone and bot-managed)\n"
                "• Recreate everything from backup **in the correct hierarchy order**"
            ),
            inline=False
        )
        embed.add_field(
            name="Backup Info",
            value=(
                f"**ID:** #{actual_id} — {label}\n"
                f"**Saved:** <t:{timestamp}:F>\n"
                f"**Channels:** {len(backup_data['channels'])}\n"
                f"**Roles:** {len(backup_data['roles'])}\n"
                f"**Emojis:** {len(backup_data['emojis'])}"
            ),
            inline=False
        )
        embed.add_field(
            name="To Confirm",
            value=f"Run `/loadfromsave {actual_id}` again within **60 seconds** to confirm.",
            inline=False
        )
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)

        # Auto-expire the confirmation token
        await asyncio.sleep(60)
        if self.pending_loads.get(pending_key) == actual_id:
            del self.pending_loads[pending_key]

    # ──────────────────────────────────────────────────────────────────────────
    # Core restore logic
    # ──────────────────────────────────────────────────────────────────────────

    async def _perform_load(self, interaction: discord.Interaction, backup_result):
        guild = interaction.guild

        backup_json = backup_result[1]
        timestamp = backup_result[2]
        label = backup_result[3] or 'Untitled'
        backup_data = json.loads(backup_json)

        if backup_data['guild_id'] != guild.id:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Backup Mismatch",
                description="This backup belongs to a different server.",
                color=0xff0000), ephemeral=True)
            return

        # ── Status message (posted to a public channel) ──────────────────────
        # We try to use the first available text channel; fall back to followup.
        status_channel = None
        for ch in guild.text_channels:
            status_channel = ch
            break

        status_embed = discord.Embed(
            title="🔄 Restoring Server…",
            description="Please wait while the server is restored from backup.",
            color=0xffaa00
        )
        if status_channel:
            try:
                status_msg = await status_channel.send(embed=status_embed)
            except Exception:
                status_msg = await interaction.followup.send(embed=status_embed)
        else:
            status_msg = await interaction.followup.send(embed=status_embed)

        async def update(step: str, text: str):
            status_embed.add_field(name=step, value=text, inline=False)
            try:
                await status_msg.edit(embed=status_embed)
            except Exception:
                pass

        # ── Step 1 — Delete all channels ─────────────────────────────────────
        deleted_channels = 0
        for channel in list(guild.channels):
            try:
                await channel.delete(reason="Anti-Nuke: Preparing for server restore")
                deleted_channels += 1
                await asyncio.sleep(0.4)   # stay inside Discord rate limits
            except Exception:
                pass
        await update("Step 1", f"✅ Deleted {deleted_channels} channels")

        # ── Step 2 — Delete all non-essential roles ───────────────────────────
        deleted_roles = 0
        for role in list(guild.roles):
            if (
                role.id == guild.id           # @everyone — can't delete
                or role.managed               # bot/integration-managed — can't delete
                or role >= guild.me.top_role  # above bot — can't delete
            ):
                continue
            try:
                await role.delete(reason="Anti-Nuke: Preparing for server restore")
                deleted_roles += 1
                await asyncio.sleep(0.3)
            except Exception:
                pass
        await update("Step 2", f"✅ Deleted {deleted_roles} roles")

        # ── Step 3 — Restore server-level settings ────────────────────────────
        try:
            edits = {}
            if backup_data['guild_name'] != guild.name:
                edits['name'] = backup_data['guild_name']
            if backup_data.get('description') is not None:
                edits['description'] = backup_data['description']
            if edits:
                await guild.edit(**edits, reason="Anti-Nuke: Restoring server settings")
        except Exception:
            pass
        await update("Step 3", "✅ Restored server settings")

        # ── Step 4 — Restore @everyone permissions ────────────────────────────
        everyone_data = next(
            (r for r in backup_data['roles'] if r.get('is_everyone')), None
        )
        if everyone_data:
            try:
                await guild.default_role.edit(
                    permissions=discord.Permissions(everyone_data['permissions']),
                    reason="Anti-Nuke: Restoring @everyone permissions"
                )
            except Exception:
                pass
        await update("Step 4", "✅ Restored @everyone permissions")

        # ── Step 5 — Recreate roles (bottom → top, skipping @everyone) ────────
        # We create all roles first, then do a single bulk position edit so the
        # hierarchy exactly matches what was saved.
        role_mapping: dict[int, discord.Role] = {}   # old_id -> new Role object
        roles_to_create = sorted(
            [r for r in backup_data['roles'] if not r.get('is_everyone')],
            key=lambda r: r['position']   # low positions first
        )
        for role_data in roles_to_create:
            try:
                new_role = await guild.create_role(
                    name=role_data['name'],
                    permissions=discord.Permissions(role_data['permissions']),
                    color=discord.Color(role_data['color']),
                    hoist=role_data['hoist'],
                    mentionable=role_data['mentionable'],
                    reason="Anti-Nuke: Restoring from backup"
                )
                role_mapping[role_data['id']] = new_role
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"[AntiNuke] Failed to create role '{role_data['name']}': {e}")

        # Bulk reorder roles to match saved positions ─────────────────────────
        # guild.edit_role_positions expects {Role: position} mapping.
        # We build it from the saved position values, but clamp them so they
        # don't exceed the bot's top_role position (Discord would reject them).
        try:
            bot_ceiling = guild.me.top_role.position - 1
            position_map: dict[discord.Role, int] = {}
            for role_data in roles_to_create:
                new_role = role_mapping.get(role_data['id'])
                if new_role:
                    position_map[new_role] = min(role_data['position'], max(bot_ceiling, 1))
            if position_map:
                await guild.edit_role_positions(
                    positions=position_map,
                    reason="Anti-Nuke: Restoring role hierarchy"
                )
        except Exception as e:
            print(f"[AntiNuke] Role reorder failed: {e}")

        await update("Step 5", f"✅ Created & ordered {len(role_mapping)} roles")

        # ── Helper — build permission overwrites from saved data ──────────────
        def build_overwrites(ow_data: dict) -> dict:
            ows: dict = {}
            for key, perms in ow_data.items():
                if key.startswith('role_'):
                    role_id = int(key.split('_', 1)[1])
                    # Try the newly created role first; fall back to existing guild roles
                    obj = role_mapping.get(role_id) or guild.get_role(role_id)
                elif key.startswith('member_'):
                    obj = guild.get_member(int(key.split('_', 1)[1]))
                else:
                    continue
                if obj:
                    ows[obj] = discord.PermissionOverwrite.from_pair(
                        discord.Permissions(perms['allow']),
                        discord.Permissions(perms['deny'])
                    )
            return ows

        # ── Step 6 — Recreate categories ─────────────────────────────────────
        category_mapping: dict[int, discord.CategoryChannel] = {}  # old_id -> new category
        categories = sorted(
            [c for c in backup_data['channels'] if c['type_value'] == discord.ChannelType.category.value],
            key=lambda c: c['position']
        )
        for cat_data in categories:
            try:
                new_cat = await guild.create_category(
                    name=cat_data['name'],
                    overwrites=build_overwrites(cat_data['overwrites']),
                    reason="Anti-Nuke: Restoring from backup"
                )
                category_mapping[cat_data['id']] = new_cat
                await asyncio.sleep(0.4)
            except Exception as e:
                print(f"[AntiNuke] Failed to create category '{cat_data['name']}': {e}")

        await update("Step 6", f"✅ Created {len(category_mapping)} categories")

        # ── Step 7 — Recreate non-category channels in position order ─────────
        NON_CATEGORY_TYPES = {
            discord.ChannelType.category.value,
        }
        non_cat_channels = sorted(
            [c for c in backup_data['channels'] if c['type_value'] not in NON_CATEGORY_TYPES],
            key=lambda c: c['position']
        )

        created_channels = 0
        channel_position_map: list[tuple[discord.abc.GuildChannel, int]] = []

        for ch_data in non_cat_channels:
            try:
                category = category_mapping.get(ch_data.get('category_id'))
                ows = build_overwrites(ch_data['overwrites'])
                new_ch = None
                t = ch_data['type_value']

                # Text / Announcement (news) channels share the same create call
                if t in (
                    discord.ChannelType.text.value,
                    discord.ChannelType.news.value,
                ):
                    new_ch = await guild.create_text_channel(
                        name=ch_data['name'],
                        category=category,
                        topic=ch_data.get('topic'),
                        slowmode_delay=ch_data.get('slowmode_delay', 0),
                        nsfw=ch_data.get('nsfw', False),
                        overwrites=ows,
                        reason="Anti-Nuke: Restoring from backup"
                    )
                    # Convert to announcement if it was one
                    if t == discord.ChannelType.news.value:
                        try:
                            await new_ch.edit(type=discord.ChannelType.news)
                        except Exception:
                            pass

                elif t == discord.ChannelType.voice.value:
                    new_ch = await guild.create_voice_channel(
                        name=ch_data['name'],
                        category=category,
                        bitrate=min(ch_data.get('bitrate', 64000), guild.bitrate_limit),
                        user_limit=ch_data.get('user_limit', 0),
                        overwrites=ows,
                        reason="Anti-Nuke: Restoring from backup"
                    )

                elif t == discord.ChannelType.stage_voice.value:
                    new_ch = await guild.create_stage_channel(
                        name=ch_data['name'],
                        category=category,
                        overwrites=ows,
                        reason="Anti-Nuke: Restoring from backup"
                    )

                elif t == discord.ChannelType.forum.value:
                    new_ch = await guild.create_forum(
                        name=ch_data['name'],
                        category=category,
                        topic=ch_data.get('topic'),
                        slowmode_delay=ch_data.get('slowmode_delay', 0),
                        nsfw=ch_data.get('nsfw', False),
                        overwrites=ows,
                        reason="Anti-Nuke: Restoring from backup"
                    )

                if new_ch:
                    channel_position_map.append((new_ch, ch_data['position']))
                    created_channels += 1
                    await asyncio.sleep(0.4)

            except Exception as e:
                print(f"[AntiNuke] Failed to create channel '{ch_data.get('name')}': {e}")

        await update("Step 7", f"✅ Created {created_channels} channels")

        # ── Step 8 — Fix channel positions within their categories ────────────
        # Discord auto-assigns positions on creation; we do a targeted edit per
        # channel to lock them back to the saved values.
        try:
            # Build a position payload grouped by category (or None for uncategorised).
            # We use move() per-channel rather than a bulk API call because
            # discord.py's guild.edit_channel_positions has stricter requirements.
            for new_ch, saved_pos in sorted(channel_position_map, key=lambda x: x[1]):
                try:
                    await new_ch.edit(position=saved_pos, reason="Anti-Nuke: Restoring channel order")
                    await asyncio.sleep(0.3)
                except Exception:
                    pass
        except Exception as e:
            print(f"[AntiNuke] Channel reorder failed: {e}")

        # Also reorder categories themselves
        try:
            for cat_data in categories:
                cat_obj = category_mapping.get(cat_data['id'])
                if cat_obj:
                    await cat_obj.edit(
                        position=cat_data['position'],
                        reason="Anti-Nuke: Restoring category order"
                    )
                    await asyncio.sleep(0.3)
        except Exception as e:
            print(f"[AntiNuke] Category reorder failed: {e}")

        await update("Step 8", "✅ Restored channel & category order")

        # ── Final summary ─────────────────────────────────────────────────────
        final_embed = discord.Embed(
            title="✅ Server Restored Successfully",
            description=f"Server restored from backup **#{backup_result[0]} — {label}**",
            color=0x00ff00
        )
        final_embed.add_field(
            name="Categories",
            value=str(len(category_mapping)),
            inline=True
        )
        final_embed.add_field(
            name="Channels",
            value=str(created_channels),
            inline=True
        )
        final_embed.add_field(
            name="Roles",
            value=str(len(role_mapping)),
            inline=True
        )
        final_embed.add_field(
            name="Backup Date",
            value=f"<t:{timestamp}:F>",
            inline=False
        )
        final_embed.set_footer(text=f"Restored by {interaction.user}")
        try:
            await status_msg.edit(embed=final_embed)
        except Exception:
            await interaction.followup.send(embed=final_embed)


async def setup(bot):
    await bot.add_cog(LoadFromSave(bot))
