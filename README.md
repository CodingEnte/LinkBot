# LinkBot

![LinkBot Banner](img/Banner.png)

LinkBot is a Discord bot that links multiple Discord servers to share ban alerts, allowing servers to accept or dismiss bans and maintain an integrity score for each server. Built with Python and Pycord, LinkBot helps server administrators maintain safer communities through collaborative moderation.

## Features

- **Cross-Server Ban Alerts**: When a user is banned in one server, all connected servers receive an alert
- **Integrity Scoring System**: Servers build reputation through accepted bans
- **Auto-Ban Option**: Automatically ban users from high-integrity servers
- **Blacklist System**: Exclude problematic servers from the network
- **Ban Rate Limiting**: Prevents spam from any single server
- **Comprehensive Moderation Tools**: Search ban history, flag users, and more

## Setup

Once the bot is running and invited to your server, use the following command to set it up:

```
/setup
```

This interactive command will guide you through:
- Setting an alert channel where ban notifications will be sent
- Setting an optional ping role to notify when bans occur
- Enabling or disabling auto-ban functionality
- Blocklisting specific servers from sending alerts to your server

## Commands

### General Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/help` | Shows the help menu with features and commands | Everyone |
| `/ping` | Shows the bot's latency | Everyone |
| `/prefix [new_prefix]` | Shows or sets a custom prefix | Admin (for setting) |

### Moderation Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/search <user>` | Shows all bans for a specific user | Everyone |
| `/flag <user> [reason] [proof_url]` | Manually flags a user for review | Admin |
| `/review` | Lists pending flags for review | Bot Owner |
| `/strike <server_id>` | Blacklists a server from the system | Bot Owner |

## How It Works

### Ban Detection

When a user is banned in a server:
1. The bot waits for the audit log to contain the ban reason
2. If a reason is provided, the ban is recorded in the database
3. An alert is sent to all other connected servers

### Integrity System

- Every server starts with an integrity score of 100 (range: 0-100)
- When a server accepts a ban from another server, the origin server's integrity increases by 1
- When a server dismisses a ban, the origin server's integrity decreases by 1
- Servers with auto-ban enabled will automatically ban users from servers with integrity ≥ 50

### Ban Alerts

Ban alerts include:
- Origin server's name and integrity score
- Banned user's mention (clickable)
- Ban reason
- Accept and Dismiss buttons (expire after 24 hours)

## Technical Details

### Database Schema

**Table: servers**
- `server_id` (int, primary key)
- `preferences` (JSON: auto-ban, alert_channel_id, ping_role_id, blocked_servers)
- `integrity` (int, default 100)
- `blacklisted` (bool, default false)

**Table: bans**
- `id` (int, primary key, autoincrement)
- `user_id` (int)
- `origin_server_id` (int)
- `flagged_by` (int: ID of the moderator who issued the ban)
- `ban_reason` (text)
- `flagged_at` (timestamp)
- `status` (text: "Pending", "Accepted", "Dismissed", "Rejected")

### Technologies Used

- **Python**: Core programming language
- **Pycord**: Discord API wrapper
- **SQLite (aiosqlite)**: Asynchronous database operations
- **ezcord**: Utility framework for Discord bots

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

Copyright © 2025 CraftEnte — All rights reserved.

This source code is made publicly viewable for reference purposes only.  
You are not permitted to use, copy, modify, compile, distribute, or run this software, in whole or in part, without prior written permission from the author.
## Support

If you need help with the bot, join our [support server](https://discord.gg/lar) or open an issue on GitHub.

---

<p align="center">
  <img src="img/Logo.png" alt="LinkBot Logo" width="100">
  <br>
  <i>Keeping Discord communities safer, together.</i>
</p>