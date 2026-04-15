import discord
from discord import app_commands
from discord.ext import commands


class HelpView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], author_id: int):
        super().__init__(timeout=120)
        self.pages = pages
        self.current = 0
        self.author_id = author_id
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current == len(self.pages) - 1
        self.page_btn.label = f"{self.current + 1} / {len(self.pages)}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await interaction.response.defer()
        if interaction.user.id != self.author_id:
            await interaction.followup.send(
                "❌ Only the command user can navigate this help menu.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.current -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.primary, disabled=True)
    async def page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        pass

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.current += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _footer(self, guild):
        return {"text": "VO AntiNuke • Help", "icon_url": guild.me.display_avatar.url if guild else None}

    @app_commands.command(name="help", description="📖 View all commands and usage")
    async def help(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild = interaction.guild
        footer = self._footer(guild)

        # Page 1: Overview
        page1 = discord.Embed(
            title="🛡️ VO AntiNuke — Help",
            description=(
                "A powerful anti-nuke and moderation bot. Use **◀ ▶** to navigate.\n\n"
                "**Pages:**\n"
                "```\n"
                "📖 Page 1  — Overview\n"
                "🛡️ Page 2  — Anti-Nuke Config\n"
                "🔨 Page 3  — Moderation (Ban/Kick/Mute/Softban)\n"
                "🔨 Page 4  — Moderation (Mass/Unban/Slowmode/History)\n"
                "🔒 Page 5  — Lockdown Commands\n"
                "⚠️ Page 6  — Warning System\n"
                "🔒 Page 7  — Jail System\n"
                "📋 Page 8  — Information Commands\n"
                "⚙️ Page 9  — Bot Configuration\n"
                "```"
            ),
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        page1.add_field(
            name="ℹ️ Quick Info",
            value=(
                "• All commands are **slash commands** (`/command`)\n"
                "• `[optional]` = optional  •  `<required>` = required\n"
                "• All moderation actions are logged to your configured log channel"
            ),
            inline=False
        )
        page1.set_footer(**footer)

        # Page 2: Anti-Nuke
        page2 = discord.Embed(
            title="🛡️ Anti-Nuke Configuration",
            description="Configure the anti-nuke protection system.",
            color=0xff4444,
            timestamp=discord.utils.utcnow()
        )
        for name, desc in [
            ("</setlimit:0>", "`/setlimit <action> <limit>` — Max times an action can occur before punishment"),
            ("</settime:0>", "`/settime <action> <timeframe>` — Timeframe window for action tracking"),
            ("</setpunishment:0>", "`/setpunishment <action> <punishment>` — Punishment for exceeding a limit"),
            ("</whitelist:0>", "`/whitelist <user>` — Exempt a user globally from anti-nuke checks"),
            ("</whitelistaction:0>", "`/whitelistaction <user> <action>` — Exempt a user for one specific action"),
            ("</tempwhitelist:0>", "`/tempwhitelist <user> <duration>` — Temp whitelist that auto-expires"),
            ("</whitelistrole:0>", "`/whitelistrole <role>` — Whitelist all members of a role"),
            ("</unwhitelist:0>", "`/unwhitelist <user>` — Remove a user from the whitelist"),
            ("</addadmin:0>", "`/addadmin <user>` — Grant bot admin privileges"),
            ("</saveserversettings:0>", "`/saveserversettings` — Save full server backup"),
            ("</loadfromsave:0>", "`/loadfromsave` — Restore server from last saved backup"),
        ]:
            page2.add_field(name=name, value=desc, inline=False)
        page2.set_footer(**footer)

        # Page 3: Moderation A
        page3 = discord.Embed(
            title="🔨 Moderation Commands (1/2)",
            description="Standard moderation commands.",
            color=0xff6600,
            timestamp=discord.utils.utcnow()
        )
        for name, desc in [
            ("</ban:0> — Ban a member", "`/ban <user> [reason] [delete_messages]`\n**Requires:** Ban Members\nBans a user and DMs them full details before banning."),
            ("</kick:0> — Kick a member", "`/kick <user> [reason]`\n**Requires:** Kick Members\nKicks a user and DMs them the reason."),
            ("</mute:0> — Timeout a member", "`/mute <user> <duration> [reason]`\n**Requires:** Moderate Members\nApplies a Discord timeout. Duration: `10m`, `1h`, `1d` etc. (max 28d). DMs the user."),
            ("</unmute:0> — Remove timeout", "`/unmute <user> [reason]`\n**Requires:** Moderate Members\nRemoves an active timeout from a member. DMs the user."),
            ("</softban:0> — Softban a member", "`/softban <user> [reason] [delete_days]`\n**Requires:** Ban Members\nBans then immediately unbans — purges messages without permanently banning. User may rejoin."),
            ("</nuke:0> — Nuke a channel", "`/nuke [channel]`\n**Requires:** Manage Channels\nClones and deletes the channel, wiping all messages. Requires confirmation."),
        ]:
            page3.add_field(name=name, value=desc, inline=False)
        page3.set_footer(**footer)

        # Page 4: Moderation B
        page4 = discord.Embed(
            title="🔨 Moderation Commands (2/2)",
            description="Advanced moderation commands.",
            color=0xff6600,
            timestamp=discord.utils.utcnow()
        )
        for name, desc in [
            ("</massban:0> — Mass ban by IDs", "`/massban <user_ids> [reason] [delete_days]`\n**Requires:** Ban Members\nBan multiple users by ID (space-separated). Shows confirmation with count before executing."),
            ("</unban:0> — Unban a user", "`/unban <user_id> [reason]`\n**Requires:** Ban Members\nUnbans a user by their ID. Attempts to DM them. Shows original ban reason."),
            ("</slowmode:0> — Set slowmode", "`/slowmode <seconds> [channel] [reason]`\n**Requires:** Manage Channels\nSet channel slowmode (0 to disable). Max 21600s (6h)."),
            ("</history:0> — Moderation history", "`/history <user>`\n**Requires:** Manage Messages\nShows full moderation history: warnings, jail status, mute status, and account info in one embed."),
        ]:
            page4.add_field(name=name, value=desc, inline=False)
        page4.set_footer(**footer)

        # Page 5: Lockdown
        page5 = discord.Embed(
            title="🔒 Lockdown Commands",
            description="Lock/unlock channels individually or all at once.",
            color=0xff4444,
            timestamp=discord.utils.utcnow()
        )
        for name, desc in [
            ("</lockdown:0> — Lock one channel", "`/lockdown [channel] [reason]`\n**Requires:** Manage Channels\nDenies `@everyone` from sending messages in the specified channel (or current if not specified). Posts a notice in the channel."),
            ("</unlockdown:0> — Unlock one channel", "`/unlockdown [channel] [reason]`\n**Requires:** Manage Channels\nRestores `@everyone` send permissions in the specified channel. Posts a notice."),
            ("</masslockdown:0> — Lock ALL channels", "`/masslockdown [reason]`\n**Requires:** Administrator\n⚠️ Locks **all** text channels. Shows a confirmation button before executing. Backs up current permissions."),
            ("</massunlockdown:0> — Unlock ALL channels", "`/massunlockdown [reason]`\n**Requires:** Administrator\n⚠️ Unlocks all text channels and **restores their original permissions** from the lockdown backup. Shows confirmation."),
        ]:
            page5.add_field(name=name, value=desc, inline=False)
        page5.set_footer(**footer)

        # Page 6: Warnings
        page6 = discord.Embed(
            title="⚠️ Warning System",
            description="Manage member warnings. All actions are logged to the mod log channel.",
            color=0xffcc00,
            timestamp=discord.utils.utcnow()
        )
        for name, desc in [
            ("</warn:0>", "`/warn <user> [reason]`\n**Requires:** Manage Messages\nIssues a warning with a unique ID. DMs the user with a warning level indicator."),
            ("</warnings:0>", "`/warnings <user>`\n**Requires:** Manage Messages\nShows all warnings on record for a user (up to 10)."),
            ("</removewarn:0>", "`/removewarn <warn_id>`\n**Requires:** Manage Messages\nRemoves a specific warning by ID. Logged to mod log."),
            ("</clearwarns:0>", "`/clearwarns <user>`\n**Requires:** Manage Messages\nClears every warning for a user. Logged to mod log."),
        ]:
            page6.add_field(name=name, value=desc, inline=False)
        page6.set_footer(**footer)

        # Page 7: Jail
        page7 = discord.Embed(
            title="🔒 Jail System",
            description="Full jail system with role management and auto-expiry.",
            color=0xff6600,
            timestamp=discord.utils.utcnow()
        )
        for name, desc in [
            ("</setjailchannel:0> — Setup jail", "`/setjailchannel [channel]`\n**Requires:** Administrator\nSets up the jail channel. Auto-creates the Jailed role and locks all other channels from jailed users."),
            ("</jail:0> — Jail a member", "`/jail <user> [reason] [duration]`\n**Requires:** Manage Roles\nJails a user — removes all roles, adds Jailed role. Duration optional (e.g. `1h`). Roles saved to DB for restoration."),
            ("</unjail:0> — Unjail a member", "`/unjail <user> [reason]`\n**Requires:** Manage Roles\nUnjails a user and restores ALL their previous roles automatically."),
            ("</jaillist:0> — View jailed members", "`/jaillist`\n**Requires:** Manage Roles\nShows all currently jailed members with reason, moderator, duration and expiry."),
        ]:
            page7.add_field(name=name, value=desc, inline=False)
        page7.set_footer(**footer)

        # Page 8: Information
        page8 = discord.Embed(
            title="📋 Information Commands",
            description="Lookup tools for users, server, roles, and whitelist.",
            color=0x57f287,
            timestamp=discord.utils.utcnow()
        )
        for name, desc in [
            ("</userinfo:0>", "`/userinfo [user]`\nShows detailed info about a member: join date, account age, roles, warnings, jail/mute status, whitelist status, and boost info."),
            ("</serverinfo:0>", "`/serverinfo`\nShows server stats: member count, channel counts, boost level, verification, features, and **server banner** if set."),
            ("</roleinfo:0>", "`/roleinfo <role>`\nShows role info: creation date, member count, color, position, flags (hoistable, mentionable, managed), and key permissions breakdown."),
            ("</whitelistinfo:0>", "`/whitelistinfo`\n**Requires:** Administrator or Bot Admin\nShows all whitelist entries: global, temporary (with expiry times), and role-based."),
            ("</history:0>", "`/history <user>`\n**Requires:** Manage Messages\nFull moderation history embed for a user including warnings, bans, jails, and mutes."),
        ]:
            page8.add_field(name=name, value=desc, inline=False)
        page8.set_footer(**footer)

        # Page 9: Config
        page9 = discord.Embed(
            title="⚙️ Bot Configuration",
            description="Configure the bot for your server.",
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        for name, desc in [
            ("</changeprefix:0>", "`/changeprefix <prefix>`\n**Requires:** Server Owner\nChanges the bot's prefix (e.g. `!`, `?`, `.`). Slash commands are unaffected."),
            ("</moderationlog:0>", "`/moderationlog <channel>`\n**Requires:** Administrator or Bot Admin\nSets the channel for all moderation and anti-nuke action logs."),
            ("</dmalerts:0>", "`/dmalerts <on/off>`\n**Requires:** Server Owner\nToggle DM alerts to the server owner for anti-nuke detections."),
            ("</antinukesettings:0>", "`/antinukesettings`\nView the current anti-nuke configuration for all 18 protected actions."),
            ("</invite:0>", "`/invite`\nGenerates the bot's invite link."),
            ("</help:0>", "`/help`\nShows this paginated help menu."),
        ]:
            page9.add_field(name=name, value=desc, inline=False)
        page9.set_footer(**footer)

        pages = [page1, page2, page3, page4, page5, page6, page7, page8, page9]
        view = HelpView(pages, interaction.user.id)
        await interaction.followup.send(embed=pages[0], view=view)


async def setup(bot):
    await bot.add_cog(Help(bot))