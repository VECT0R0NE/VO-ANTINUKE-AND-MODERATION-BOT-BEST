# VO AntiNuke

A feature-heavy Discord anti-nuke and moderation bot built with discord.py. Designed to protect servers from raiders, nukers, and malicious bots by monitoring audit log activity in real time and punishing anyone who trips the limits you set.

---

## What it does

**Anti-Nuke Protection**  
Watches for destructive actions like mass bans, channel deletions, role deletions, webhook creation, and a bunch of other things. If someone hits the action threshold within your configured timeframe, the bot kicks in and punishes them (ban, kick, or strip roles depending on your settings). Whitelisted users are ignored. Everything is configurable.

Protected actions include:
- Banning / kicking members
- Creating or deleting channels
- Creating or deleting roles
- Editing channels or roles
- Giving out dangerous permissions or admin roles
- Adding bots to the server
- Creating or deleting webhooks
- Updating server settings
- Timing out members
- Mass member pruning
- Authorizing OAuth applications
- Changing nicknames in bulk
- Creating, deleting, or editing threads

**Moderation**  
Full slash command moderation suite — ban, kick, mute/timeout, softban, tempban, mass ban, unban, slowmode, lockdown, warn system with thresholds, jail system with timed release and role restore on rejoin, notes system for staff, and bulk message purge with filters.

**Logging**  
- Moderation log (bans, kicks, warns, etc.)
- Message log (edits, deletes, bulk deletes)
- Join/leave log with invite tracking and welcome messages
- Server audit log that mirrors Discord's audit log to a channel
- Per-event toggles so you only log what you care about

**DM Alerts**  
Sends DM notifications when anti-nuke fires or moderation actions happen. You can configure which events alert which users, or just leave it as default (alerts go to the server owner).

**Suspicious Account Detection**  
Flags new members that look sus — new accounts, no avatar, or default usernames. Configurable thresholds and optional auto-actions (kick/ban/timeout).

**Config Backup & Restore**  
Export your entire bot config to a file and restore it later. Useful if you're moving servers or just want a backup.

**Role Persistence**  
Jailed or muted users who leave and rejoin get their roles reapplied automatically.

---

## Setup

**Requirements:**
- Python 3.10+
- discord.py >= 2.3.2
- aiosqlite >= 0.19.0

```
pip install -r requirements.txt
```

**Config:**

Copy this to `.env` and fill in your values:

```
DISCORD_TOKEN=your_bot_token_here
APPLICATION_ID=your_application_id_here
```

Then just run:

```
python bot.py
```

The bot uses SQLite for storage — no database server needed. Data files are stored in the `data/` folder which gets created automatically.

---

## Permissions

The bot needs these intents enabled in the Discord Developer Portal:
- Server Members Intent
- Message Content Intent
- Presence Intent (optional but recommended)

In terms of role permissions, give it Administrator or at minimum: Ban Members, Kick Members, Manage Roles, Manage Channels, Manage Guild, View Audit Log, Manage Webhooks, Moderate Members, Send Messages, Embed Links.

---

## Commands

All commands are slash commands. Run `/help` in your server to see everything with usage info. The help menu is paginated so it's easy to navigate.

Quick overview of categories:
- `/help` — paginated help menu
- `/setlimit`, `/settime`, `/setpunishment` — tune detection thresholds
- `/whitelist`, `/unwhitelist`, `/addadmin` — manage trusted users
- `/protectiontoggle` — enable/disable specific protections
- `/antinukesettings` — view current anti-nuke config
- `/ban`, `/kick`, `/warn`, `/mute`, `/softban`, `/tempban` — moderation
- `/jail`, `/unjail` — jail system
- `/purge` — bulk message delete with filters
- `/note` — staff notes per user
- `/info`, `/serverinfo`, `/roleinfo` — info commands
- `/moderationlog`, `/msglog`, `/joinlog`, `/serverauditlog` — logging setup
- `/dmalerts` — configure DM alert targets
- `/suspicious` — configure suspicious account detection
- `/saveconfig`, `/loadconfig` — backup and restore
- `/changeprefix` — change the prefix (for legacy prefix commands)
- `/invite` — get the bot invite link

---

## File Structure

```
antinuke-bot/
├── bot.py                  # Entry point
├── requirements.txt
├── .env                    # Your tokens and application id go here
├── cogs/                   # All features live here
│   ├── protection.py       # Core anti-nuke engine
│   ├── moderation.py       # Ban, kick, mute, lockdown, etc.
│   ├── jail.py             # Jail system
│   ├── warn.py             # Warning system
│   ├── purge.py            # Bulk delete
│   ├── notes.py            # Staff notes
│   ├── tempban.py          # Timed bans
│   ├── dmalerts.py         # DM alert routing
│   ├── joinlog.py          # Join/leave logging
│   ├── msglog.py           # Message logging
│   ├── serverauditlog.py   # Audit log mirroring
│   ├── suspicious_setup.py # New account detection
│   ├── role_persistence.py # Rejoin role reapplication
│   ├── thread_protection.py# Thread anti-nuke
│   ├── configexport.py     # Config backup/restore
│   ├── help.py             # Help command
│   └── ...                 # Other config/info cogs
├── utils/
│   ├── database.py         # Main SQLite database layer
│   ├── jail_database.py    # Jail-specific DB
│   ├── warns_database.py   # Warns-specific DB
│   ├── checks.py           # Permission checks
│   └── helpers.py          # Shared utilities
└── data/                   # SQLite DB files (auto-created)
```

---

## Support

DM **coolmannice** on Discord for questions or suggestions.  
Official server: https://discord.gg/rRbTvswDAc

---

create a .env file too with the token in it and application id of your bot in it aswell
## License

MIT — use it, modify it, do whatever you want with it.

Current Problems with the bot that CANNOT be fixxed:
the bot relies on a record of who added the bot, still the bot will be punished but like this is a ongoing issue that cant be fixxed.