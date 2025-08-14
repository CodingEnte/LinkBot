import json
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import aiosqlite
import discord
from discord.ext import commands, tasks

from cogs.systems import preChecks

class BanRateLimit:
    """Prevents servers from spamming ban alerts"""

    def __init__(self, max_bans: int = 5, time_window: int = 180):
        self.max_bans = max_bans  # Max bans allowed in the time period
        self.time_window = time_window  # Time window in seconds (3 minutes default)
        self.server_bans: Dict[int, List[float]] = {}  # Tracks when each server sent ban alerts

    def can_send_alert(self, server_id: int) -> bool:
        """Checks if a server is rate-limited or can send another ban alert"""
        current_time = time.time()

        # First time seeing this server? Initialize it
        if server_id not in self.server_bans:
            self.server_bans[server_id] = []

        # Clean up old timestamps - only keep recent ones
        self.server_bans[server_id] = [
            ts for ts in self.server_bans[server_id] 
            if current_time - ts < self.time_window
        ]

        # If they haven't hit the limit yet, let them send another
        if len(self.server_bans[server_id]) < self.max_bans:
            self.server_bans[server_id].append(current_time)
            return True

        # Too many bans, they need to wait
        return False

class BanAlertView(discord.ui.View):
    """The UI with Accept/Dismiss buttons for ban alerts"""

    def __init__(self, ban_id: int, user_id: int, origin_server_id: int, ban_reason: str, cog):
        super().__init__(timeout=86400)  # Buttons expire after 24 hours
        self.ban_id = ban_id
        self.user_id = user_id  # The banned user
        self.origin_server_id = origin_server_id  # Server that issued the ban
        self.ban_reason = ban_reason
        self.cog = cog
        self.expiry_time = datetime.now() + timedelta(hours=24)  # For tracking when buttons should disable

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green, emoji="✅", custom_id="accept_ban")
    async def accept_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Check if the user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("You need administrator permissions to use this button.", ephemeral=True)
            return

        # Update the ban status and increase origin server's integrity
        async with aiosqlite.connect("database.db") as db:
            # Update ban status
            await db.execute(
                "UPDATE bans SET status = ? WHERE id = ?",
                ("Accepted", self.ban_id)
            )

            # Increase origin server's integrity (max 100)
            await db.execute(
                """
                UPDATE servers 
                SET integrity = MIN(integrity + 1, 100) 
                WHERE server_id = ?
                """,
                (self.origin_server_id,)
            )

            # Log the action
            await db.execute(
                """
                INSERT INTO ban_actions (ban_id, action, by_user_id, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (self.ban_id, "Accepted", interaction.user.id, datetime.now().timestamp())
            )

            await db.commit()

        # Ban the user in this server
        try:
            await interaction.guild.ban(
                discord.Object(id=self.user_id), 
                reason=f"LinkBot: Ban accepted from server {self.origin_server_id}. Original reason: {self.ban_reason}"
            )
            success_msg = f"User <@{self.user_id}> has been banned in this server."
        except discord.Forbidden:
            success_msg = "I don't have permission to ban this user."
        except discord.HTTPException:
            success_msg = "Failed to ban the user. They may have already left or been banned."

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        # Update the message
        embed = interaction.message.embeds[0]
        embed.add_field(name="Status", value=f"✅ Accepted by {interaction.user.mention}", inline=False)

        await interaction.edit_original_response(embed=embed, view=self)
        await interaction.followup.send(success_msg, ephemeral=True)

    @discord.ui.button(label="Dismiss", style=discord.ButtonStyle.red, emoji="❌", custom_id="dismiss_ban")
    async def dismiss_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Check if the user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("You need administrator permissions to use this button.", ephemeral=True)
            return

        # Update the ban status and decrease origin server's integrity
        async with aiosqlite.connect("database.db") as db:
            # Update ban status
            await db.execute(
                "UPDATE bans SET status = ? WHERE id = ?",
                ("Dismissed", self.ban_id)
            )

            # Decrease origin server's integrity (min 0)
            await db.execute(
                """
                UPDATE servers 
                SET integrity = MAX(integrity - 1, 0) 
                WHERE server_id = ?
                """,
                (self.origin_server_id,)
            )

            # Log the action
            await db.execute(
                """
                INSERT INTO ban_actions (ban_id, action, by_user_id, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (self.ban_id, "Dismissed", interaction.user.id, datetime.now().timestamp())
            )

            await db.commit()

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        # Update the message
        embed = interaction.message.embeds[0]
        embed.add_field(name="Status", value=f"❌ Dismissed by {interaction.user.mention}", inline=False)

        await interaction.edit_original_response(embed=embed, view=self)
        await interaction.followup.send("Ban alert dismissed.", ephemeral=True)

    async def on_timeout(self):
        # Disable all buttons when the view times out (after 24 hours)
        for item in self.children:
            item.disabled = True

        # We can't update the message here since we don't have a reference to it
        # This will be handled by a background task that checks for expired views

class JoinAlertView(discord.ui.View):
    """UI with Ban/Dismiss buttons for when previously banned users join"""

    def __init__(self, user_id: int, ban_records: List[dict], cog):
        super().__init__(timeout=86400)  # Buttons expire after 24 hours
        self.user_id = user_id  # The user who joined
        self.ban_records = ban_records  # List of ban records for this user
        self.cog = cog
        self.expiry_time = datetime.now() + timedelta(hours=24)

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.red, emoji="🔨", custom_id="ban_user")
    async def ban_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Check if the user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("You need administrator permissions to use this button.", ephemeral=True)
            return

        # Ban the user in this server
        try:
            # Get the most recent ban reason from the records
            most_recent_ban = max(self.ban_records, key=lambda x: x["flagged_at"])
            ban_reason = most_recent_ban["ban_reason"]

            await interaction.guild.ban(
                discord.Object(id=self.user_id),
                reason=f"LinkBot: User was previously banned in other servers. Most recent reason: {ban_reason}"
            )
            success_msg = f"User <@{self.user_id}> has been banned in this server."
        except discord.Forbidden:
            success_msg = "I don't have permission to ban this user."
        except discord.HTTPException:
            success_msg = "Failed to ban the user. They may have already left or been banned."

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        # Update the message
        embed = interaction.message.embeds[0]
        embed.add_field(name="Status", value=f"🔨 Banned by {interaction.user.mention}", inline=False)

        await interaction.edit_original_response(embed=embed, view=self)
        await interaction.followup.send(success_msg, ephemeral=True)

    @discord.ui.button(label="Dismiss", style=discord.ButtonStyle.green, emoji="✓", custom_id="dismiss_join_alert")
    async def dismiss_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Check if the user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("You need administrator permissions to use this button.", ephemeral=True)
            return

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        # Update the message
        embed = interaction.message.embeds[0]
        embed.add_field(name="Status", value=f"✓ Dismissed by {interaction.user.mention}", inline=False)

        await interaction.edit_original_response(embed=embed, view=self)
        await interaction.followup.send("Alert dismissed. No action taken against the user.", ephemeral=True)

    async def on_timeout(self):
        # Disable all buttons when the view times out (after 24 hours)
        for item in self.children:
            item.disabled = True

        # We can't update the message here since we don't have a reference to it
        # This will be handled by a background task that checks for expired views

class Bans(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rate_limiter = BanRateLimit()
        self.check_expired_views.start()

    def cog_unload(self):
        self.check_expired_views.cancel()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Check if a joining user was previously banned in other servers"""
        # Skip bots
        if member.bot:
            return

        # Query the database for ban records for this user
        async with aiosqlite.connect("database.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT b.*, s.integrity, s.server_id 
                FROM bans b
                JOIN servers s ON b.origin_server_id = s.server_id
                WHERE b.user_id = ? AND b.status = 'Accepted'
                ORDER BY b.flagged_at DESC
                """,
                (member.id,)
            ) as cursor:
                ban_records = await cursor.fetchall()

        # If no ban records found, do nothing
        if not ban_records:
            return

        # Get the server's preferences
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT preferences FROM servers WHERE server_id = ?",
                (member.guild.id,)
            ) as cursor:
                server_data = await cursor.fetchone()

            if not server_data:
                return

            try:
                preferences = json.loads(server_data[0]) if server_data[0] else {}
            except json.JSONDecodeError:
                preferences = {}

        # Get alert channel
        alert_channel_id = preferences.get("alert_channel_id")
        if not alert_channel_id:
            return

        alert_channel = member.guild.get_channel(alert_channel_id)
        if not alert_channel:
            return

        # Create embed for the join alert
        embed = discord.Embed(
            title="⚠️ Previously Banned User Joined",
            description=f"User {member.mention} has joined this server but has been banned in {len(ban_records)} other server(s).",
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )

        # Add information about the most recent ban
        most_recent_ban = ban_records[0]
        server = self.bot.get_guild(most_recent_ban["origin_server_id"])
        server_name = server.name if server else f"Unknown Server ({most_recent_ban['origin_server_id']})"

        embed.add_field(
            name="Most Recent Ban",
            value=f"**Server:** {server_name} (Integrity: {most_recent_ban['integrity']})\n"
                  f"**Reason:** {most_recent_ban['ban_reason']}\n"
                  f"**Date:** {datetime.fromtimestamp(most_recent_ban['flagged_at']).strftime('%Y-%m-%d %H:%M:%S')}",
            inline=False
        )

        # Add total ban count
        embed.add_field(
            name="Ban History",
            value=f"This user has been banned in {len(ban_records)} server(s). Use `/search {member.mention}` for details.",
            inline=False
        )

        # Create view with Ban and Dismiss buttons
        view = JoinAlertView(member.id, ban_records, self)

        # Send the alert, pinging the role if specified
        ping_role_id = preferences.get("ping_role_id")
        content = f"<@&{ping_role_id}>" if ping_role_id else None
        try:
            await alert_channel.send(content=content, embed=embed, view=view)
        except discord.errors.Forbidden:
            # Bot doesn't have permission to send messages in this channel
            print(f"Missing permissions to send join alert in channel {alert_channel.id} in guild {member.guild.id}")
        except Exception as e:
            # Log any other errors that might occur
            print(f"Error sending join alert: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        async with aiosqlite.connect("database.db") as db:
            # Create bans table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS bans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    origin_server_id INTEGER NOT NULL,
                    flagged_by INTEGER NOT NULL,
                    ban_reason TEXT,
                    flagged_at REAL NOT NULL,
                    status TEXT DEFAULT 'Pending'
                )
                """
            )

            # Create ban_actions table for logging accept/dismiss actions
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS ban_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ban_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    by_user_id INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY (ban_id) REFERENCES bans (id)
                )
                """
            )

            await db.commit()

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        # Check if the guild is blacklisted
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT blacklisted FROM servers WHERE server_id = ?",
                (guild.id,)
            ) as cursor:
                server_data = await cursor.fetchone()

            # If server doesn't exist in DB or is blacklisted, ignore the ban
            if not server_data or server_data[0]:
                return

        # Wait for audit log to contain the ban reason
        ban_reason = None
        moderator_id = None

        # Try to get the ban reason from audit logs
        try:
            await asyncio.sleep(2)  # Wait for audit log to be updated
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    ban_reason = entry.reason
                    moderator_id = entry.user.id
                    break
        except discord.Forbidden:
            # Bot doesn't have permission to view audit logs
            return

        # If no reason is found, ignore this ban
        if not ban_reason:
            return

        # Ignore bans issued by the bot itself
        if moderator_id == self.bot.user.id:
            return

        # Check rate limit
        if not self.rate_limiter.can_send_alert(guild.id):
            return

        # Check if an alert has already been sent for this user from any server recently
        current_time = datetime.now().timestamp()
        time_threshold = current_time - 300  # 5 minutes ago

        async with aiosqlite.connect("database.db") as db:
            # First check if an alert has already been sent for this user from this server recently
            async with db.execute(
                """
                SELECT id FROM bans 
                WHERE user_id = ? AND origin_server_id = ? AND flagged_at > ?
                """,
                (user.id, guild.id, time_threshold)
            ) as cursor:
                existing_ban_from_this_server = await cursor.fetchone()

            # If an alert has already been sent from this server recently, ignore this ban
            if existing_ban_from_this_server:
                return

            # Then check if an alert has already been sent for this user from any server recently
            async with db.execute(
                """
                SELECT id FROM bans 
                WHERE user_id = ? AND flagged_at > ?
                """,
                (user.id, time_threshold)
            ) as cursor:
                existing_ban_from_any_server = await cursor.fetchone()

            # If an alert has already been sent from any server recently, ignore this ban
            if existing_ban_from_any_server:
                return

        # Record the ban in the database
        async with aiosqlite.connect("database.db") as db:
            cursor = await db.execute(
                """
                INSERT INTO bans (user_id, origin_server_id, flagged_by, ban_reason, flagged_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user.id, guild.id, moderator_id, ban_reason, current_time, "Pending")
            )
            ban_id = cursor.lastrowid
            await db.commit()

        # Get the origin server's integrity
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT integrity FROM servers WHERE server_id = ?",
                (guild.id,)
            ) as cursor:
                server_data = await cursor.fetchone()

            if not server_data:
                # If server doesn't exist in DB, add it with default values
                await db.execute(
                    "INSERT INTO servers (server_id, integrity) VALUES (?, ?)",
                    (guild.id, 100)
                )
                await db.commit()
                integrity = 100
            else:
                integrity = server_data[0]

        # Send ban alerts to other servers
        await self.send_ban_alerts(ban_id, user.id, guild.id, guild.name, integrity, ban_reason, moderator_id)

    async def send_ban_alerts(self, ban_id, user_id, origin_server_id, origin_server_name, 
                             integrity, ban_reason, moderator_id):
        # Get all servers where the bot is present
        for guild in self.bot.guilds:
            # Skip the origin server
            if guild.id == origin_server_id:
                continue

            # Check if this server is in the database and not blacklisted
            async with aiosqlite.connect("database.db") as db:
                async with db.execute(
                    "SELECT preferences, blacklisted FROM servers WHERE server_id = ?",
                    (guild.id,)
                ) as cursor:
                    server_data = await cursor.fetchone()

                # If server is not in DB or is blacklisted, skip it
                if not server_data or server_data[1]:
                    continue

                # Parse preferences
                try:
                    preferences = json.loads(server_data[0]) if server_data[0] else {}
                except json.JSONDecodeError:
                    preferences = {}

                # Check if this server has blocked the origin server
                blocked_servers = preferences.get("blocked_servers", [])
                if origin_server_id in blocked_servers:
                    continue

                # Check auto-ban setting
                auto_ban = preferences.get("auto_ban", False)

                # Get alert channel
                alert_channel_id = preferences.get("alert_channel_id")
                if not alert_channel_id:
                    continue

                alert_channel = guild.get_channel(alert_channel_id)
                if not alert_channel:
                    continue

                # Check if we should auto-ban or send alert
                if auto_ban and integrity >= 50:
                    # Auto-ban the user
                    try:
                        await guild.ban(
                            discord.Object(id=user_id), 
                            reason=f"LinkBot: Auto-ban from server {origin_server_name} (ID: {origin_server_id}). Original reason: {ban_reason}"
                        )

                        # Create embed for the auto-ban notification
                        embed = discord.Embed(
                            title="⚠️ Auto-Ban Alert",
                            description=f"User <@{user_id}> was automatically banned based on a ban from another server.",
                            color=discord.Color.red(),
                            timestamp=datetime.now()
                        )
                        embed.add_field(name="Origin Server", value=f"{origin_server_name} (Integrity: {integrity})", inline=False)
                        embed.add_field(name="Ban Reason", value=ban_reason or "No reason provided", inline=False)

                        # Update ban status to Accepted
                        async with aiosqlite.connect("database.db") as db:
                            await db.execute(
                                "UPDATE bans SET status = ? WHERE id = ?",
                                ("Accepted", ban_id)
                            )

                            # Increase origin server's integrity (max 100)
                            await db.execute(
                                """
                                UPDATE servers 
                                SET integrity = MIN(integrity + 1, 100) 
                                WHERE server_id = ?
                                """,
                                (origin_server_id,)
                            )

                            await db.commit()

                        # Send notification to alert channel
                        try:
                            await alert_channel.send(embed=embed)
                        except discord.errors.Forbidden:
                            # Bot doesn't have permission to send messages in this channel
                            print(f"Missing permissions to send auto-ban notification in channel {alert_channel.id} in guild {guild.id}")
                        except Exception as e:
                            # Log any other errors that might occur
                            print(f"Error sending auto-ban notification: {e}")

                    except (discord.Forbidden, discord.HTTPException):
                        # If auto-ban fails, fall back to sending an alert
                        await self.send_ban_alert(alert_channel, ban_id, user_id, origin_server_id, 
                                                origin_server_name, integrity, ban_reason, 
                                                preferences.get("ping_role_id"))
                else:
                    # Send alert with buttons
                    await self.send_ban_alert(alert_channel, ban_id, user_id, origin_server_id, 
                                            origin_server_name, integrity, ban_reason, 
                                            preferences.get("ping_role_id"))

    async def send_ban_alert(self, channel, ban_id, user_id, origin_server_id, origin_server_name, 
                            integrity, ban_reason, ping_role_id=None):
        # Create embed for the ban alert
        embed = discord.Embed(
            title="⚠️ Ban Alert",
            description=f"User <@{user_id}> was banned from another server.",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Origin Server", value=f"{origin_server_name} (Integrity: {integrity})", inline=False)
        embed.add_field(name="Ban Reason", value=ban_reason or "No reason provided", inline=False)

        # Create view with Accept and Dismiss buttons
        view = BanAlertView(ban_id, user_id, origin_server_id, ban_reason, self)

        # Send the alert, pinging the role if specified
        content = f"<@&{ping_role_id}>" if ping_role_id else None
        try:
            await channel.send(content=content, embed=embed, view=view)
        except discord.errors.Forbidden:
            # Bot doesn't have permission to send messages in this channel
            print(f"Missing permissions to send ban alert in channel {channel.id} in guild {channel.guild.id}")
        except Exception as e:
            # Log any other errors that might occur
            print(f"Error sending ban alert: {e}")

    @tasks.loop(minutes=10)
    async def check_expired_views(self):
        """Background task to check for and disable expired ban alert views"""
        # This would require storing message IDs in the database
        # For simplicity, we're relying on the built-in timeout functionality
        pass

    @commands.slash_command(name="search", description="Search for a user's ban history")
    async def search(self, ctx, user: discord.User):
        # Check if we're in maintenance mode
        check = await preChecks(ctx)
        if check is True:
            return

        # Check if the command is used in a guild
        if not ctx.guild:
            await ctx.respond("This command can only be used in a server.", ephemeral=True)
            return

        # Query the database for ban history
        async with aiosqlite.connect("database.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT b.*, s.integrity 
                FROM bans b
                JOIN servers s ON b.origin_server_id = s.server_id
                WHERE b.user_id = ?
                ORDER BY b.flagged_at DESC
                """,
                (user.id,)
            ) as cursor:
                bans = await cursor.fetchall()

        if not bans:
            await ctx.respond(f"No ban records found for {user.mention}.", ephemeral=True)
            return

        # Create embed with ban history
        embed = discord.Embed(
            title=f"Ban History for {user.name}",
            description=f"Found {len(bans)} ban records for {user.mention}.",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        for ban in bans:
            # Get server name if possible
            server = self.bot.get_guild(ban["origin_server_id"])
            server_name = server.name if server else f"Unknown Server ({ban['origin_server_id']})"

            # Format the ban date
            ban_date = datetime.fromtimestamp(ban["flagged_at"]).strftime("%Y-%m-%d %H:%M:%S")

            # Add field for this ban
            embed.add_field(
                name=f"Ban from {server_name} (Integrity: {ban['integrity']})",
                value=f"**Reason:** {ban['ban_reason']}\n"
                      f"**Date:** {ban_date}\n"
                      f"**Status:** {ban['status']}",
                inline=False
            )

        await ctx.respond(embed=embed, ephemeral=True)

    @commands.slash_command(name="flag", description="Flag a user for review by LinkBot owner")
    @commands.has_permissions(administrator=True)
    async def flag(self, ctx, user: discord.User, reason: str, proof_url: str = None):
        # Check if we're in maintenance mode
        check = await preChecks(ctx)
        if check is True:
            return

        # Check if the command is used in a guild
        if not ctx.guild:
            await ctx.respond("This command can only be used in a server.", ephemeral=True)
            return

        # Record the flag in the database
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                """
                INSERT INTO bans (user_id, origin_server_id, flagged_by, ban_reason, flagged_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user.id, ctx.guild.id, ctx.author.id, 
                 f"{reason}{' | Proof: ' + proof_url if proof_url else ''}", 
                 datetime.now().timestamp(), "Review")
            )
            await db.commit()

        await ctx.respond(
            f"User {user.mention} has been flagged for review by the LinkBot owner.\n"
            f"Reason: {reason}",
            ephemeral=True
        )

def setup(bot):
    bot.add_cog(Bans(bot))
