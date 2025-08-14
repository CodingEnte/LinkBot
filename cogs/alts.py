import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

import aiosqlite
import discord
from discord.ext import commands, tasks
from ezcord.internal.dc import slash_command

from cogs.systems import preChecks

class AltDetectionView(discord.ui.View):
    """UI with Kick/Ban/Dismiss buttons for alt account alerts"""

    def __init__(self, user_id: int, heat_score: int, triggered_rules: Dict[str, int], cog):
        super().__init__(timeout=86400)  # Buttons expire after 24 hours
        self.user_id = user_id  # The user who joined
        self.heat_score = heat_score  # Total heat score
        self.triggered_rules = triggered_rules  # Rules that were triggered and their heat values
        self.cog = cog
        self.expiry_time = datetime.now(timezone.utc) + timedelta(hours=24)

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.primary, emoji="👢", custom_id="kick_user")
    async def kick_button(self, button: discord.ui.Button, interaction: discord.Interaction):
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

        # Kick the user from this server
        try:
            member = interaction.guild.get_member(self.user_id)
            if member:
                await member.kick(reason=f"LinkBot: Possible alt account (Heat Score: {self.heat_score})")
                success_msg = f"User <@{self.user_id}> has been kicked from the server."
            else:
                success_msg = "User is no longer in the server."
        except discord.Forbidden:
            success_msg = "I don't have permission to kick this user."
        except discord.HTTPException as e:
            success_msg = f"Failed to kick the user: {str(e)}"

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        # Update the message
        embed = interaction.message.embeds[0]
        embed.add_field(name="Status", value=f"👢 Kicked by {interaction.user.mention}", inline=False)

        await interaction.edit_original_response(embed=embed, view=self)
        await interaction.followup.send(success_msg, ephemeral=True)

        # Log the action in the database
        await self.cog.log_alt_action(interaction.guild.id, self.user_id, "kicked", interaction.user.id)

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger, emoji="🔨", custom_id="ban_user")
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

        # Ban the user from this server
        try:
            await interaction.guild.ban(
                discord.Object(id=self.user_id),
                reason=f"LinkBot: Possible alt account (Heat Score: {self.heat_score})"
            )
            success_msg = f"User <@{self.user_id}> has been banned from the server."
        except discord.Forbidden:
            success_msg = "I don't have permission to ban this user."
        except discord.HTTPException as e:
            success_msg = f"Failed to ban the user: {str(e)}"

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        # Update the message
        embed = interaction.message.embeds[0]
        embed.add_field(name="Status", value=f"🔨 Banned by {interaction.user.mention}", inline=False)

        await interaction.edit_original_response(embed=embed, view=self)
        await interaction.followup.send(success_msg, ephemeral=True)

        # Log the action in the database
        await self.cog.log_alt_action(interaction.guild.id, self.user_id, "banned", interaction.user.id)

    @discord.ui.button(label="Dismiss", style=discord.ButtonStyle.success, emoji="✓", custom_id="dismiss_alt_alert")
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

        # Log the action in the database
        await self.cog.log_alt_action(interaction.guild.id, self.user_id, "dismissed", interaction.user.id)

    async def on_timeout(self):
        # Disable all buttons when the view times out (after 24 hours)
        for item in self.children:
            item.disabled = True

        # We can't update the message here since we don't have a reference to it
        # This will be handled by a background task that checks for expired views

class AltSettings(discord.ui.View):
    """View for configuring alt detection settings"""

    def __init__(self, bot, guild_id: int, settings: dict):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.guild_id = guild_id
        self.settings = settings

        # Ensure enabled field exists
        if "enabled" not in self.settings:
            self.settings["enabled"] = True

        # Add threshold select menu on row 0
        threshold_select = ThresholdSelect(self.bot, self.guild_id, self.settings)
        threshold_select.row = 0
        self.add_item(threshold_select)

        # Set up button states/styles before adding them
        self._init_button_states()

    def _init_button_states(self):
        system_enabled = self.settings.get("enabled", True)
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.label == "Toggle Alt System":
                    child.style = discord.ButtonStyle.blurple if system_enabled else discord.ButtonStyle.danger
                    child.disabled = False
                else:
                    if not system_enabled:
                        child.style = discord.ButtonStyle.secondary
                        child.disabled = True
                    else:
                        child.disabled = False
                        if child.label == "Toggle New Account Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("new_account", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle No Avatar Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("no_avatar", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Alt Name Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("alt_name", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Default Name Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("default_name", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Previous Ban Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("previous_ban", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Quick Join Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("quick_join", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Auto-Kick":
                            child.style = discord.ButtonStyle.success if self.settings.get("auto_kick", False) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Auto-Ban":
                            child.style = discord.ButtonStyle.success if self.settings.get("auto_ban", False) else discord.ButtonStyle.danger

    @discord.ui.button(label="Toggle Alt System", style=discord.ButtonStyle.primary, row=1)
    async def toggle_alt_system(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Toggle the enabled setting
        current_setting = self.settings.get("enabled", True)
        self.settings["enabled"] = not current_setting

        # Save to DB
        await self.save_settings(interaction)

    @discord.ui.button(label="Toggle New Account Rule", style=discord.ButtonStyle.primary, row=2)
    async def toggle_new_account(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Toggle the rule
        current_setting = self.settings.get("rules", {}).get("new_account", True)
        if "rules" not in self.settings:
            self.settings["rules"] = {}
        self.settings["rules"]["new_account"] = not current_setting

        # Save to DB
        await self.save_settings(interaction)

    @discord.ui.button(label="Toggle No Avatar Rule", style=discord.ButtonStyle.primary, row=2)
    async def toggle_no_avatar(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Toggle the rule
        current_setting = self.settings.get("rules", {}).get("no_avatar", True)
        if "rules" not in self.settings:
            self.settings["rules"] = {}
        self.settings["rules"]["no_avatar"] = not current_setting

        # Save to DB
        await self.save_settings(interaction)

    @discord.ui.button(label="Toggle Alt Name Rule", style=discord.ButtonStyle.primary, row=2)
    async def toggle_alt_name(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Toggle the rule
        current_setting = self.settings.get("rules", {}).get("alt_name", True)
        if "rules" not in self.settings:
            self.settings["rules"] = {}
        self.settings["rules"]["alt_name"] = not current_setting

        # Save to DB
        await self.save_settings(interaction)

    @discord.ui.button(label="Toggle Default Name Rule", style=discord.ButtonStyle.primary, row=3)
    async def toggle_default_name(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Toggle the rule
        current_setting = self.settings.get("rules", {}).get("default_name", True)
        if "rules" not in self.settings:
            self.settings["rules"] = {}
        self.settings["rules"]["default_name"] = not current_setting

        # Save to DB
        await self.save_settings(interaction)

    @discord.ui.button(label="Toggle Previous Ban Rule", style=discord.ButtonStyle.primary, row=3)
    async def toggle_previous_ban(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Toggle the rule
        current_setting = self.settings.get("rules", {}).get("previous_ban", True)
        if "rules" not in self.settings:
            self.settings["rules"] = {}
        self.settings["rules"]["previous_ban"] = not current_setting

        # Save to DB
        await self.save_settings(interaction)

    @discord.ui.button(label="Toggle Quick Join Rule", style=discord.ButtonStyle.primary, row=3)
    async def toggle_quick_join(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Toggle the rule
        current_setting = self.settings.get("rules", {}).get("quick_join", True)
        if "rules" not in self.settings:
            self.settings["rules"] = {}
        self.settings["rules"]["quick_join"] = not current_setting

        # Save to DB
        await self.save_settings(interaction)

    @discord.ui.button(label="Toggle Auto-Kick", style=discord.ButtonStyle.primary, row=4)
    async def toggle_auto_kick(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Toggle the setting
        current_setting = self.settings.get("auto_kick", False)
        self.settings["auto_kick"] = not current_setting

        # If enabling auto-kick, disable auto-ban
        if self.settings["auto_kick"]:
            self.settings["auto_ban"] = False

        # Save to DB
        await self.save_settings(interaction)

    @discord.ui.button(label="Toggle Auto-Ban", style=discord.ButtonStyle.primary, row=4)
    async def toggle_auto_ban(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Toggle the setting
        current_setting = self.settings.get("auto_ban", False)
        self.settings["auto_ban"] = not current_setting

        # If enabling auto-ban, disable auto-kick
        if self.settings["auto_ban"]:
            self.settings["auto_kick"] = False

        # Save to DB
        await self.save_settings(interaction)

    async def save_settings(self, interaction):
        # Save settings to database
        async with aiosqlite.connect("database.db") as db:
            # Check if settings already exist
            async with db.execute(
                "SELECT settings FROM alt_settings WHERE server_id = ?",
                (self.guild_id,)
            ) as cursor:
                existing = await cursor.fetchone()

            if existing:
                # Update existing settings
                await db.execute(
                    "UPDATE alt_settings SET settings = ? WHERE server_id = ?",
                    (json.dumps(self.settings), self.guild_id)
                )
            else:
                # Insert new settings
                await db.execute(
                    "INSERT INTO alt_settings (server_id, settings) VALUES (?, ?)",
                    (self.guild_id, json.dumps(self.settings))
                )

            await db.commit()

        # Update the view with current settings
        await self.update_view(interaction)

    async def update_view(self, interaction):
        # Check if the system is enabled
        system_enabled = self.settings.get("enabled", True)

        # Update button styles and disable state based on current settings
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                # Set the Toggle Alt System button style
                if child.label == "Toggle Alt System":
                    child.style = discord.ButtonStyle.success if system_enabled else discord.ButtonStyle.danger
                    child.disabled = False
                else:
                    # If system is disabled, set all other buttons to gray and disable them
                    if not system_enabled:
                        child.style = discord.ButtonStyle.secondary
                        child.disabled = True
                    else:
                        child.disabled = False
                        # Otherwise, set button styles based on their settings
                        if child.label == "Toggle New Account Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("new_account", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle No Avatar Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("no_avatar", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Alt Name Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("alt_name", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Default Name Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("default_name", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Previous Ban Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("previous_ban", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Quick Join Rule":
                            child.style = discord.ButtonStyle.success if self.settings.get("rules", {}).get("quick_join", True) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Auto-Kick":
                            child.style = discord.ButtonStyle.success if self.settings.get("auto_kick", False) else discord.ButtonStyle.danger
                        elif child.label == "Toggle Auto-Ban":
                            child.style = discord.ButtonStyle.success if self.settings.get("auto_ban", False) else discord.ButtonStyle.danger

        # Create settings embed
        embed = discord.Embed(
            title="Alt Detection Settings",
            description="Configure the alt detection system for your server.",
            color=discord.Color.blue()
        )

        # Add system status field
        system_enabled = self.settings.get("enabled", True)
        embed.add_field(
            name="System Status",
            value=f"{'✅ Enabled' if system_enabled else '❌ Disabled'}",
            inline=False
        )

        # Add threshold field
        embed.add_field(
            name="Heat Threshold",
            value=f"{self.settings.get('threshold', 100)}",
            inline=False
        )

        # Add rules field
        rules_status = []
        rules = self.settings.get("rules", {})
        rules_status.append(f"New Account (< 7 days): {'✅' if rules.get('new_account', True) else '❌'} (+50 heat)")
        rules_status.append(f"No Avatar: {'✅' if rules.get('no_avatar', True) else '❌'} (+30 heat)")
        rules_status.append(f"Alt in Name: {'✅' if rules.get('alt_name', True) else '❌'} (+30 heat)")
        rules_status.append(f"Default Username: {'✅' if rules.get('default_name', True) else '❌'} (+20 heat)")
        rules_status.append(f"Previous Ban: {'✅' if rules.get('previous_ban', True) else '❌'} (+40 heat)")
        rules_status.append(f"Quick Join: {'✅' if rules.get('quick_join', True) else '❌'} (+25 heat)")

        embed.add_field(
            name="Enabled Rules",
            value="\n".join(rules_status),
            inline=False
        )

        # Add auto-actions field
        auto_actions = []
        auto_actions.append(f"Auto-Kick: {'✅' if self.settings.get('auto_kick', False) else '❌'}")
        auto_actions.append(f"Auto-Ban: {'✅' if self.settings.get('auto_ban', False) else '❌'}")

        embed.add_field(
            name="Auto Actions",
            value="\n".join(auto_actions),
            inline=False
        )

        # Update the message
        await interaction.edit_original_response(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only check permissions or other logic here, do not update the view/message
        return True

class ThresholdSelect(discord.ui.Select):
    """Select menu for choosing the heat threshold"""

    def __init__(self, bot, guild_id: int, settings: dict):
        self.bot = bot
        self.guild_id = guild_id
        self.settings = settings

        # Create options for different thresholds
        options = [
            discord.SelectOption(
                label=f"{threshold}",
                value=f"{threshold}",
                description=f"Set heat threshold to {threshold}",
                default=(threshold == settings.get("threshold", 100))
            )
            for threshold in [50, 75, 100, 125, 150, 175, 200]
        ]

        super().__init__(
            placeholder="Select heat threshold",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Update threshold setting
        self.settings["threshold"] = int(self.values[0])

        # Update select menu
        for option in self.options:
            option.default = (option.value == self.values[0])

        # Save settings and update view
        await self.view.save_settings(interaction)

class Alts(commands.Cog):
    """Alt account detection system"""

    def __init__(self, bot):
        self.bot = bot
        self.recent_joins = {}  # guild_id -> list of (user_id, timestamp) tuples
        self.check_expired_joins.start()

    def cog_unload(self):
        self.check_expired_joins.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        """Create necessary database tables on startup"""
        async with aiosqlite.connect("database.db") as db:
            # Create alt_settings table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS alt_settings (
                    server_id INTEGER PRIMARY KEY,
                    settings TEXT
                )
                """
            )

            # Create alt_actions table for logging actions
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS alt_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    by_user_id INTEGER NOT NULL,
                    timestamp REAL NOT NULL
                )
                """
            )

            # Create alt_dismissed table for tracking dismissed users
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS alt_dismissed (
                    server_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    PRIMARY KEY (server_id, user_id)
                )
                """
            )

            await db.commit()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Check if a joining user is a possible alt account"""
        # Skip bots
        if member.bot:
            return

        # Get server settings
        settings = await self.get_server_settings(member.guild.id)

        # If no settings found or threshold is 0, use defaults
        if not settings:
            settings = {
                "enabled": True,
                "threshold": 100,
                "rules": {
                    "new_account": True,
                    "no_avatar": True,
                    "alt_name": True,
                    "default_name": True,
                    "previous_ban": True,
                    "quick_join": True
                },
                "auto_kick": False,
                "auto_ban": False
            }

        # Check if the system is enabled
        if not settings.get("enabled", True):
            return

        # Check if user was previously dismissed
        if await self.is_user_dismissed(member.guild.id, member.id):
            return

        # Calculate heat score
        heat_score = 0
        triggered_rules = {}
        rules = settings.get("rules", {})

        # Rule 1: Account age < 7 days
        if rules.get("new_account", True):
            account_age = (datetime.now(timezone.utc) - member.created_at).days
            if account_age < 7:
                heat_score += 50
                triggered_rules["new_account"] = 50

        # Rule 2: No avatar
        if rules.get("no_avatar", True):
            if member.avatar is None:
                heat_score += 30
                triggered_rules["no_avatar"] = 30

        # Rule 3: Username or display name contains "alt"
        if rules.get("alt_name", True):
            name_lower = member.name.lower()
            display_name_lower = member.display_name.lower()
            if "alt" in name_lower or "alt" in display_name_lower:
                heat_score += 30
                triggered_rules["alt_name"] = 30

        # Rule 4: Username matches Discord default pattern
        if rules.get("default_name", True):
            if re.match(r'^[a-zA-Z]+\d{4}$', member.name):
                heat_score += 20
                triggered_rules["default_name"] = 20

        # Rule 5: User was banned in the past under a different account with the same username
        if rules.get("previous_ban", True):
            if await self.check_previous_ban_with_same_name(member.guild.id, member.id, member.name):
                heat_score += 40
                triggered_rules["previous_ban"] = 40

        # Rule 6: User joins within 2 minutes of another new account
        if rules.get("quick_join", True):
            if await self.check_quick_join(member.guild.id, member.id):
                heat_score += 25
                triggered_rules["quick_join"] = 25

        # Add this join to recent joins
        if member.guild.id not in self.recent_joins:
            self.recent_joins[member.guild.id] = []
        self.recent_joins[member.guild.id].append((member.id, time.time()))

        # If heat score is below threshold, do nothing
        threshold = settings.get("threshold", 100)
        if heat_score < threshold:
            return

        # Get the server's preferences for alert channel
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

        # Check if auto-actions are enabled
        if settings.get("auto_kick", False):
            try:
                await member.kick(reason=f"LinkBot: Possible alt account (Heat Score: {heat_score})")
                # Create embed for the auto-kick notification
                embed = discord.Embed(
                    title="⚠️ Auto-Kick Alert",
                    description=f"User {member.mention} was automatically kicked as a possible alt account.",
                    color=discord.Color.orange(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="Heat Score", value=f"{heat_score}/{threshold}", inline=False)

                # Add triggered rules
                rules_text = "\n".join([f"• {self.get_rule_name(rule)}: +{points}" for rule, points in triggered_rules.items()])
                embed.add_field(name="Triggered Rules", value=rules_text, inline=False)

                # Add user info
                embed.add_field(
                    name="User Info",
                    value=f"**ID:** {member.id}\n**Created:** {member.created_at.strftime('%Y-%m-%d %H:%M:%S')} ({(datetime.now(timezone.utc) - member.created_at).days} days ago)",
                    inline=False
                )

                # Send notification to alert channel
                await alert_channel.send(embed=embed)

                # Log the action
                await self.log_alt_action(member.guild.id, member.id, "auto-kicked", self.bot.user.id)
                return
            except (discord.Forbidden, discord.HTTPException):
                # If auto-kick fails, fall back to sending an alert
                pass
        elif settings.get("auto_ban", False):
            try:
                await member.guild.ban(
                    member,
                    reason=f"LinkBot: Possible alt account (Heat Score: {heat_score})"
                )
                # Create embed for the auto-ban notification
                embed = discord.Embed(
                    title="⚠️ Auto-Ban Alert",
                    description=f"User {member.mention} was automatically banned as a possible alt account.",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="Heat Score", value=f"{heat_score}/{threshold}", inline=False)

                # Add triggered rules
                rules_text = "\n".join([f"• {self.get_rule_name(rule)}: +{points}" for rule, points in triggered_rules.items()])
                embed.add_field(name="Triggered Rules", value=rules_text, inline=False)

                # Add user info
                embed.add_field(
                    name="User Info",
                    value=f"**ID:** {member.id}\n**Created:** {member.created_at.strftime('%Y-%m-%d %H:%M:%S')} ({(datetime.now(timezone.utc) - member.created_at).days} days ago)",
                    inline=False
                )

                # Send notification to alert channel
                await alert_channel.send(embed=embed)

                # Log the action
                await self.log_alt_action(member.guild.id, member.id, "auto-banned", self.bot.user.id)
                return
            except (discord.Forbidden, discord.HTTPException):
                # If auto-ban fails, fall back to sending an alert
                pass

        # Create embed for the alt alert
        embed = discord.Embed(
            title="⚠️ Possible Alt Account Detected",
            description=f"User {member.mention} has been flagged as a possible alt account.",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Heat Score", value=f"{heat_score}/{threshold}", inline=False)

        # Add triggered rules
        rules_text = "\n".join([f"• {self.get_rule_name(rule)}: +{points}" for rule, points in triggered_rules.items()])
        embed.add_field(name="Triggered Rules", value=rules_text, inline=False)

        # Add user info
        embed.add_field(
            name="User Info",
            value=f"**ID:** {member.id}\n**Created:** {member.created_at.strftime('%Y-%m-%d %H:%M:%S')} ({(datetime.now(timezone.utc) - member.created_at).days} days ago)",
            inline=False
        )

        # Create view with Kick, Ban, and Dismiss buttons
        view = AltDetectionView(member.id, heat_score, triggered_rules, self)

        # Send the alert, pinging the role if specified
        ping_role_id = preferences.get("ping_role_id")
        content = f"<@&{ping_role_id}>" if ping_role_id else None
        await alert_channel.send(content=content, embed=embed, view=view)

    @tasks.loop(minutes=10)
    async def check_expired_joins(self):
        """Remove joins older than 10 minutes from the recent_joins dict"""
        current_time = time.time()
        for guild_id in list(self.recent_joins.keys()):
            self.recent_joins[guild_id] = [
                (user_id, timestamp) for user_id, timestamp in self.recent_joins[guild_id]
                if current_time - timestamp < 600  # 10 minutes
            ]
            # If no recent joins left, remove the guild from the dict
            if not self.recent_joins[guild_id]:
                del self.recent_joins[guild_id]

    @check_expired_joins.before_loop
    async def before_check_expired_joins(self):
        """Wait until the bot is ready before starting the task"""
        await self.bot.wait_until_ready()

    async def get_server_settings(self, guild_id: int) -> dict:
        """Get alt detection settings for a server"""
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT settings FROM alt_settings WHERE server_id = ?",
                (guild_id,)
            ) as cursor:
                data = await cursor.fetchone()

            if not data:
                return None

            try:
                return json.loads(data[0])
            except json.JSONDecodeError:
                return None

    async def check_previous_ban_with_same_name(self, guild_id: int, user_id: int, username: str) -> bool:
        """Check if a user with the same username was banned in this server before"""
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                """
                SELECT b.id FROM bans b
                JOIN ban_actions ba ON b.id = ba.ban_id
                WHERE b.origin_server_id = ? AND b.user_id != ? AND ba.action = 'Accepted'
                """,
                (guild_id, user_id)
            ) as cursor:
                ban_records = await cursor.fetchall()

            if not ban_records:
                return False

            # For each ban record, check if the banned user had the same username
            # This would require storing usernames in the bans table, which we don't currently do
            # For now, we'll return False, but this could be implemented in the future
            return False

    async def check_quick_join(self, guild_id: int, user_id: int) -> bool:
        """Check if a user joined within 2 minutes of another new account"""
        if guild_id not in self.recent_joins:
            return False

        current_time = time.time()
        for other_user_id, timestamp in self.recent_joins[guild_id]:
            if other_user_id != user_id and current_time - timestamp < 120:  # 2 minutes
                return True

        return False

    async def is_user_dismissed(self, guild_id: int, user_id: int) -> bool:
        """Check if a user was previously dismissed"""
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT timestamp FROM alt_dismissed WHERE server_id = ? AND user_id = ?",
                (guild_id, user_id)
            ) as cursor:
                data = await cursor.fetchone()

            return data is not None

    async def log_alt_action(self, guild_id: int, user_id: int, action: str, by_user_id: int):
        """Log an action taken on a possible alt account"""
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                """
                INSERT INTO alt_actions (server_id, user_id, action, by_user_id, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, action, by_user_id, time.time())
            )

            # If action is "dismissed", add to dismissed users
            if action == "dismissed":
                await db.execute(
                    """
                    INSERT OR REPLACE INTO alt_dismissed (server_id, user_id, timestamp)
                    VALUES (?, ?, ?)
                    """,
                    (guild_id, user_id, time.time())
                )

            await db.commit()

    def get_rule_name(self, rule_key: str) -> str:
        """Get a human-readable name for a rule key"""
        rule_names = {
            "new_account": "Account age < 7 days",
            "no_avatar": "No avatar",
            "alt_name": "Username/display name contains 'alt'",
            "default_name": "Username matches Discord default pattern",
            "previous_ban": "Previously banned under different account with same username",
            "quick_join": "Joined within 2 minutes of another new account"
        }
        return rule_names.get(rule_key, rule_key)

    async def alt_settings(self, interaction):
        """Show the alt detection settings panel (for dashboard integration)"""
        # Check maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        guild_id = interaction.guild.id
        # Fetch current settings or use defaults
        settings = await self.get_server_settings(guild_id)
        if not settings:
            settings = {
                "enabled": True,
                "threshold": 100,
                "rules": {
                    "new_account": True,
                    "no_avatar": True,
                    "alt_name": True,
                    "default_name": True,
                    "previous_ban": True,
                    "quick_join": True
                },
                "auto_kick": False,
                "auto_ban": False
            }
        view = AltSettings(self.bot, guild_id, settings)
        embed = discord.Embed(
            title="Alt Detection Settings",
            description="Configure the alt detection system for your server.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


def setup(bot):
    bot.add_cog(Alts(bot))
