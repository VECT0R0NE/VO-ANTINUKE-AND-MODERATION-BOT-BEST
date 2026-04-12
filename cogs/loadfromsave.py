import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
from utils.checks import is_owner_or_admin


class LoadFromSave(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending_loads: dict = {}  # user_id -> (guild_id, backup_id, expire_task)

    @app_commands.command(name='loadfromsave', description='Load server from a backup by ID (WARNING: destructive)')
    @app_commands.describe(backup_id='Backup ID from /listbackups (leave empty for latest)')
    @is_owner_or_admin()
    async def loadfromsave(self, interaction: discord.Interaction, backup_id: int = None):
        guild = interaction.guild
        backup_result = await self.bot.db.get_server_backup(guild.id, backup_id)

        if not backup_result:
            msg = (f"No backup with ID **#{backup_id}** found." if backup_id
                   else "No backups exist for this server. Use `/saveserversettings` first.")
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ No Backup Found", description=msg, color=0xff0000), ephemeral=True)
            return

        actual_id = backup_result[0]

        # Confirmation gate — require running the command twice within 60s
        pending_key = (interaction.user.id, guild.id)
        if pending_key in self.pending_loads and self.pending_loads[pending_key] == actual_id:
            await self.perform_load(interaction, backup_result)
            return

        self.pending_loads[pending_key] = actual_id

        backup_data = json.loads(backup_result[1])
        timestamp = backup_result[2]
        label = backup_result[3] or 'Untitled'

        embed = discord.Embed(
            title="⚠️ WARNING: Server Restore",
            description="**This will delete ALL current channels and restore from backup!**",
            color=0xff0000
        )
        embed.add_field(
            name="⚠️ DANGER",
            value="This action will:\n• Delete all current channels\n• Delete all current roles (except @everyone)\n• Recreate everything from backup",
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
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Auto-expire the confirmation
        await asyncio.sleep(60)
        if self.pending_loads.get(pending_key) == actual_id:
            del self.pending_loads[pending_key]

    async def perform_load(self, interaction: discord.Interaction, backup_result):
        guild = interaction.guild
        pending_key = (interaction.user.id, guild.id)
        self.pending_loads.pop(pending_key, None)

        await interaction.response.defer()

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

        status_embed = discord.Embed(
            title="🔄 Restoring Server...",
            description="Please wait while the server is restored from backup.",
            color=0xffaa00
        )
        status_msg = await interaction.followup.send(embed=status_embed)

        deleted_channels = 0
        for channel in guild.channels:
            try:
                await channel.delete(reason="Anti-Nuke: Preparing for server restore")
                deleted_channels += 1
            except Exception:
                pass

        status_embed.add_field(name="Step 1", value=f"✅ Deleted {deleted_channels} channels", inline=False)
        await status_msg.edit(embed=status_embed)

        deleted_roles = 0
        for role in guild.roles:
            if role != guild.default_role and role.name != guild.me.name and role < guild.me.top_role:
                try:
                    await role.delete(reason="Anti-Nuke: Preparing for server restore")
                    deleted_roles += 1
                except Exception:
                    pass

        status_embed.add_field(name="Step 2", value=f"✅ Deleted {deleted_roles} roles", inline=False)
        await status_msg.edit(embed=status_embed)

        try:
            if backup_data['guild_name'] != guild.name:
                await guild.edit(name=backup_data['guild_name'], reason="Anti-Nuke: Restoring server name")
            if backup_data.get('vanity_url') and backup_data['vanity_url'] != guild.vanity_url_code:
                await guild.edit(vanity_code=backup_data['vanity_url'], reason="Anti-Nuke: Restoring vanity URL")
        except Exception:
            pass

        status_embed.add_field(name="Step 3", value="✅ Restored server settings", inline=False)
        await status_msg.edit(embed=status_embed)

        role_mapping = {}
        for role_data in sorted(backup_data['roles'], key=lambda r: r['position']):
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
            except Exception as e:
                print(f"[AntiNuke] Failed to create role: {e}")

        status_embed.add_field(name="Step 4", value=f"✅ Created {len(role_mapping)} roles", inline=False)
        await status_msg.edit(embed=status_embed)

        def build_overwrites(ow_data):
            ows = {}
            for key, perms in ow_data.items():
                if key.startswith('role_'):
                    role_id = int(key.split('_')[1])
                    obj = role_mapping.get(role_id)
                elif key.startswith('member_'):
                    obj = guild.get_member(int(key.split('_')[1]))
                else:
                    continue
                if obj:
                    ows[obj] = discord.PermissionOverwrite.from_pair(
                        discord.Permissions(perms['allow']),
                        discord.Permissions(perms['deny'])
                    )
            return ows

        category_mapping = {}
        for cat_data in sorted([c for c in backup_data['channels'] if 'category' in c['type']],
                                key=lambda c: c['position']):
            try:
                new_cat = await guild.create_category(
                    name=cat_data['name'], position=cat_data['position'],
                    overwrites=build_overwrites(cat_data['overwrites']),
                    reason="Anti-Nuke: Restoring from backup"
                )
                category_mapping[cat_data['id']] = new_cat
            except Exception as e:
                print(f"[AntiNuke] Failed to create category: {e}")

        status_embed.add_field(name="Step 5", value=f"✅ Created {len(category_mapping)} categories", inline=False)
        await status_msg.edit(embed=status_embed)

        created_channels = 0
        for ch_data in sorted([c for c in backup_data['channels'] if 'category' not in c['type']],
                               key=lambda c: c['position']):
            try:
                category = category_mapping.get(ch_data.get('category_id'))
                ows = build_overwrites(ch_data['overwrites'])
                if 'text' in ch_data['type']:
                    await guild.create_text_channel(
                        name=ch_data['name'], category=category, position=ch_data['position'],
                        topic=ch_data.get('topic'), slowmode_delay=ch_data.get('slowmode_delay', 0),
                        nsfw=ch_data.get('nsfw', False), overwrites=ows,
                        reason="Anti-Nuke: Restoring from backup")
                elif 'voice' in ch_data['type']:
                    await guild.create_voice_channel(
                        name=ch_data['name'], category=category, position=ch_data['position'],
                        bitrate=ch_data.get('bitrate', 64000), user_limit=ch_data.get('user_limit', 0),
                        overwrites=ows, reason="Anti-Nuke: Restoring from backup")
                created_channels += 1
            except Exception as e:
                print(f"[AntiNuke] Failed to create channel: {e}")

        status_embed.add_field(name="Step 6", value=f"✅ Created {created_channels} channels", inline=False)
        await status_msg.edit(embed=status_embed)

        final_embed = discord.Embed(
            title="✅ Server Restored Successfully",
            description=f"Server restored from backup **#{backup_result[0]} — {label}**",
            color=0x00ff00
        )
        final_embed.add_field(name="Channels", value=str(created_channels + len(category_mapping)), inline=True)
        final_embed.add_field(name="Roles", value=str(len(role_mapping)), inline=True)
        final_embed.add_field(name="Backup Date", value=f"<t:{timestamp}:F>", inline=False)
        final_embed.set_footer(text=f"Restored by {interaction.user}")
        await status_msg.edit(embed=final_embed)


async def setup(bot):
    await bot.add_cog(LoadFromSave(bot))
