import discord
from discord import app_commands
from discord.ext import commands

BOT_NAME = "VO AntiNuke"


async def _is_admin(bot, guild_id, user_id):
    return await bot.db.is_admin(guild_id, user_id)


class TrustedRole(commands.Cog):
    """Manage trusted roles (exempt from anti-nuke checks) and the member role for lockdowns."""

    def __init__(self, bot):
        self.bot = bot

    trusted = app_commands.Group(name="trustedrole", description="🛡️ Manage trusted roles (anti-nuke exempt)")

    # ─── /trustedrole add ────────────────────────────────────────────────────

    @trusted.command(name="add", description="🛡️ Add a role to the trusted list (exempt from anti-nuke)")
    @app_commands.describe(role="The role to trust")
    async def trusted_add(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the server owner, administrators, or bot admins can manage trusted roles.",
                color=0xff0000
            ), ephemeral=True)
            return

        if await self.bot.db.is_trusted_role(interaction.guild.id, role.id):
            await interaction.followup.send(embed=discord.Embed(
                description=f"ℹ️ {role.mention} is already a trusted role.",
                color=0x5865f2
            ), ephemeral=True)
            return

        await self.bot.db.add_trusted_role(interaction.guild.id, role.id)

        embed = discord.Embed(
            title="✅ Trusted Role Added",
            description=f"{role.mention} is now a **trusted role**.\nMembers with this role are exempt from anti-nuke checks.",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="🎭 Role", value=f"{role.mention} (`{role.id}`)", inline=True)
        embed.add_field(name="👤 Added By", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"{BOT_NAME} • Trusted Roles")
        await interaction.followup.send(embed=embed)

    # ─── /trustedrole remove ─────────────────────────────────────────────────

    @trusted.command(name="remove", description="❌ Remove a role from the trusted list")
    @app_commands.describe(role="The role to untrust")
    async def trusted_remove(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the server owner, administrators, or bot admins can manage trusted roles.",
                color=0xff0000
            ), ephemeral=True)
            return

        if not await self.bot.db.is_trusted_role(interaction.guild.id, role.id):
            await interaction.followup.send(embed=discord.Embed(
                description=f"ℹ️ {role.mention} is not in the trusted roles list.",
                color=0x5865f2
            ), ephemeral=True)
            return

        await self.bot.db.remove_trusted_role(interaction.guild.id, role.id)

        embed = discord.Embed(
            title="🗑️ Trusted Role Removed",
            description=f"{role.mention} has been removed from trusted roles.\nMembers with this role are **no longer** exempt from anti-nuke checks.",
            color=0xff4444,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="🎭 Role", value=f"{role.mention} (`{role.id}`)", inline=True)
        embed.add_field(name="👤 Removed By", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"{BOT_NAME} • Trusted Roles")
        await interaction.followup.send(embed=embed)

    # ─── /trustedrole list ───────────────────────────────────────────────────

    @trusted.command(name="list", description="📋 List all trusted roles")
    async def trusted_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the server owner, administrators, or bot admins can view trusted roles.",
                color=0xff0000
            ), ephemeral=True)
            return

        role_ids = await self.bot.db.get_trusted_roles(interaction.guild.id)
        member_role_id = await self.bot.db.get_lockdown_member_role(interaction.guild.id)

        embed = discord.Embed(
            title="🛡️ Trusted Roles",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )

        if role_ids:
            lines = []
            for rid in role_ids:
                role = interaction.guild.get_role(rid)
                if role:
                    lines.append(f"• {role.mention} (`{rid}`)")
                else:
                    lines.append(f"• ~~Unknown Role~~ (`{rid}`) — deleted")
            embed.add_field(
                name=f"🛡️ Anti-Nuke Exempt Roles ({len(role_ids)})",
                value="\n".join(lines),
                inline=False
            )
        else:
            embed.add_field(
                name="🛡️ Anti-Nuke Exempt Roles",
                value="*No trusted roles configured.*",
                inline=False
            )

        if member_role_id:
            member_role = interaction.guild.get_role(member_role_id)
            val = member_role.mention if member_role else f"~~Deleted~~ (`{member_role_id}`)"
            embed.add_field(name="🔒 Lockdown Member Role", value=val, inline=False)
        else:
            embed.add_field(name="🔒 Lockdown Member Role", value="*Not set. Use `/setmemberrole` to configure.*", inline=False)

        embed.set_footer(text=f"{BOT_NAME} • Trusted Roles")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── /setmemberrole ──────────────────────────────────────────────────────

    @app_commands.command(
        name="setmemberrole",
        description="⚙️ Set the member/verified role that gets locked during lockdowns"
    )
    @app_commands.describe(role="The verified/member role (leave blank to clear)")
    async def setmemberrole(self, interaction: discord.Interaction, role: discord.Role = None):
        await interaction.response.defer()
        is_admin = await _is_admin(self.bot, interaction.guild.id, interaction.user.id)
        if not (interaction.user.id == interaction.guild.owner_id or
                interaction.user.guild_permissions.administrator or is_admin):
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Only the server owner, administrators, or bot admins can set the member role.",
                color=0xff0000
            ), ephemeral=True)
            return

        if role is None:
            await self.bot.db.set_lockdown_member_role(interaction.guild.id, None)
            await interaction.followup.send(embed=discord.Embed(
                title="✅ Member Role Cleared",
                description="The lockdown member role has been removed. Lockdowns will only deny `@everyone`.",
                color=0x57f287
            ), ephemeral=True)
            return

        await self.bot.db.set_lockdown_member_role(interaction.guild.id, role.id)

        embed = discord.Embed(
            title="✅ Member Role Set",
            description=(
                f"{role.mention} is now the **lockdown member role**.\n\n"
                "During `/lockdown` and `/masslockdown`, `send_messages` will also be denied for this role."
            ),
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="🎭 Role", value=f"{role.mention} (`{role.id}`)", inline=True)
        embed.add_field(name="👤 Set By", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"{BOT_NAME} • Lockdown Settings")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(TrustedRole(bot))