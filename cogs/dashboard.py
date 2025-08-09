import json
from typing import List, Optional

import aiosqlite
import discord
from discord.ext import commands
from discord.ext.bridge import bridge_command
from ezcord.internal.dc import slash_command
from cogs.systems import preChecks

class Dashboard(commands.Cog):
    """The server settings dashboard (admin only)"""

    def __init__(self, bot):
        self.bot = bot
        # List of available prefixes
        self.available_prefixes = ["!", ":", ".", ",", "-", "?", ";", "*"]
        # Track views waiting for channel pings
        self.channel_ping_views = {}
        # Track channel selections from pings
        self.channel_selections = {}
        # Track views waiting for role pings
        self.role_ping_views = {}
        # Track role selections from pings
        self.role_selections = {}

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for channel and role mentions during dashboard interactions"""
        # Ignore messages from bots
        if message.author.bot:
            return

        # Check if the bot is mentioned in the message
        if self.bot.user in message.mentions:
            # Save the channel where the bot was mentioned
            channel = message.channel

            # Check if setup is active or if Systems cog has active role ping view
            systems_cog = self.bot.get_cog("Systems")
            if systems_cog and message.guild and (
                message.guild.id in systems_cog.active_setups or
                message.guild.id in systems_cog.role_ping_views or
                message.guild.id in systems_cog.channel_ping_views
            ):
                # Let the Systems cog handle this message
                return

            # Check if this guild has an active channel ping view
            if message.guild and message.guild.id in self.channel_ping_views:
                # Save the channel ID
                self.channel_selections[message.guild.id] = channel.id

                # Send confirmation message
                await message.reply(f"#{channel.name} was saved. Return to the dashboard panel to continue or ping the bot in a different channel to update your choice.")
            # Don't send any message if there's no active channel selection
            # This prevents confusion when users ping the bot for other reasons

            return

        # Check if this guild has an active channel ping view
        if message.guild and message.guild.id in self.channel_ping_views:
            # Check for channel mentions
            if message.channel_mentions:
                # Get the first mentioned channel
                channel = message.channel_mentions[0]

                # Save the channel ID
                self.channel_selections[message.guild.id] = channel.id

                # Acknowledge the channel selection
                await message.reply(f"Channel {channel.mention} has been selected for ban alerts. Click the button to confirm.")

        # Check if this guild has an active role ping view
        if message.guild and message.guild.id in self.role_ping_views:
            # Check for role mentions
            if message.role_mentions:
                # Get the first mentioned role
                role = message.role_mentions[0]

                # Save the role ID
                self.role_selections[message.guild.id] = role.id

                # Acknowledge the role selection
                await message.reply(f"Role {role.mention} will be pinged for ban alerts. Click the button to confirm.")

    @slash_command(name="dashboard", description="Open the server settings dashboard")
    @commands.guild_only()
    @discord.default_permissions(administrator=True)
    async def dashboard(self, ctx):
        check = await preChecks(ctx)
        if check is True:
            return

        """Opens the settings dashboard for server admins"""
        # Grab the server's current settings
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT preferences FROM servers WHERE server_id = ?",
                (ctx.guild.id,)
            ) as cursor:
                data = await cursor.fetchone()

                if not data:
                    # Oops, looks like they haven't run setup yet
                    await ctx.respond(
                        embed=discord.Embed(
                            title="Server Not Set Up",
                            description="This server hasn't been set up yet. Please run `/setup` first.",
                            color=discord.Color.red()
                        ),
                        ephemeral=True
                    )
                    return

                try:
                    preferences = json.loads(data[0])
                except (json.JSONDecodeError, TypeError):
                    # JSON broke? Just use empty settings
                    preferences = {}

        # Build a nice looking dashboard
        embed = discord.Embed(
            title="Server Dashboard",
            description="Manage your server settings using the buttons below.",
            color=discord.Color.blue()
        )

        # Show all their current settings
        embed.add_field(
            name="Alert Channel", 
            value=f"<#{preferences.get('alert_channel_id')}>" if preferences.get('alert_channel_id') else "Not set",
            inline=False
        )

        embed.add_field(
            name="Ping Role", 
            value=f"<@&{preferences.get('ping_role_id')}>" if preferences.get('ping_role_id') else "Not set",
            inline=False
        )

        embed.add_field(
            name="Auto-Ban", 
            value="Enabled" if preferences.get('auto_ban') else "Disabled",
            inline=False
        )

        embed.add_field(
            name="Prefix", 
            value=f"`{preferences.get('prefix', '-')}`",
            inline=False
        )

        # Show the dashboard only to the person who ran the command
        await ctx.respond(
            embed=embed,
            view=DashboardView(self.bot, ctx.guild.id, preferences),
            ephemeral=True
        )


class DashboardView(discord.ui.View):
    """The interactive buttons and menus for the dashboard"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        super().__init__(timeout=300)  # Expire after 5 mins of inactivity
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Add the prefix dropdown at the top
        self.add_item(PrefixSelect(self.bot, self.guild_id, self.preferences))

        # Make the auto-ban button red/green based on current setting
        # (Have to do this after creating all buttons)
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Toggle Auto-Ban":
                child.style = discord.ButtonStyle.danger if preferences.get("auto_ban", False) else discord.ButtonStyle.success

    @discord.ui.button(label="Change Alert Channel", style=discord.ButtonStyle.primary, emoji="📢", row=1)
    async def change_alert_channel(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Opens the channel ping view when clicked"""
        await interaction.response.send_message(
            "Please ping the channel where you want ban alerts to be sent.\n\n**Example:** #alerts",
            view=AlertChannelPingView(self.bot, self.guild_id, self.preferences),
            ephemeral=True
        )

    @discord.ui.button(label="Change Ping Role", style=discord.ButtonStyle.primary, emoji="🔔", row=1)
    async def change_ping_role(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Shows the role ping view"""
        await interaction.response.send_message(
            "Please ping the role you want to be notified for ban alerts.\n\n**Example:** @Moderators\n\nYou can also remove the ping role by clicking the Remove button.",
            view=PingRolePingView(self.bot, self.guild_id, self.preferences),
            ephemeral=True
        )

    @discord.ui.button(
        label="Toggle Auto-Ban", 
        style=discord.ButtonStyle.primary, # placeholder --> Fix in __init__
        emoji="🔄",
        row=2
    )
    async def toggle_auto_ban(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Flips the auto-ban setting on/off and changes button color"""
        # Flip the setting to its opposite
        current_setting = self.preferences.get("auto_ban", False)
        self.preferences["auto_ban"] = not current_setting

        # Save to DB
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "UPDATE servers SET preferences = ? WHERE server_id = ?",
                (json.dumps(self.preferences), self.guild_id)
            )
            await db.commit()

        # Red when enabled, green when disabled
        button.style = discord.ButtonStyle.danger if self.preferences["auto_ban"] else discord.ButtonStyle.success

        # Rebuild the embed with updated settings
        embed = discord.Embed(
            title="Server Dashboard",
            description="Manage your server settings using the buttons below.",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="Alert Channel", 
            value=f"<#{self.preferences.get('alert_channel_id')}>" if self.preferences.get('alert_channel_id') else "Not set",
            inline=False
        )

        embed.add_field(
            name="Ping Role", 
            value=f"<@&{self.preferences.get('ping_role_id')}>" if self.preferences.get('ping_role_id') else "Not set",
            inline=False
        )

        embed.add_field(
            name="Auto-Ban", 
            value="Enabled" if self.preferences.get('auto_ban') else "Disabled",
            inline=False
        )

        embed.add_field(
            name="Prefix", 
            value=f"`{self.preferences.get('prefix', '-')}`",
            inline=False
        )

        # Update the message with our changes
        await interaction.response.edit_message(embed=embed, view=self)


class PrefixSelect(discord.ui.Select):
    """Dropdown menu for picking your command prefix"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Figure out what prefix they're using now
        current_prefix = preferences.get("prefix", "-")

        # Make a dropdown with all our prefix choices
        options = [
            discord.SelectOption(
                label=prefix,
                value=prefix,
                description=f"Set {prefix} as the command prefix",
                default=(prefix == current_prefix)  # Check the one they're currently using
            )
            for prefix in ["!", ":", ".", ",", "-", "?", ";", "*"]
        ]

        super().__init__(
            placeholder="Select a command prefix",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        """Handles when someone picks a new prefix"""
        # Grab what they selected
        selected_prefix = self.values[0]

        # Store their choice
        self.preferences["prefix"] = selected_prefix

        # Save it to the database
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "UPDATE servers SET preferences = ? WHERE server_id = ?",
                (json.dumps(self.preferences), self.guild_id)
            )
            await db.commit()

        # Update the checkmark in the dropdown
        for option in self.options:
            option.default = (option.value == selected_prefix)

        # Refresh the dashboard with the new prefix
        embed = discord.Embed(
            title="Server Dashboard",
            description="Manage your server settings using the buttons below.",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="Alert Channel", 
            value=f"<#{self.preferences.get('alert_channel_id')}>" if self.preferences.get('alert_channel_id') else "Not set",
            inline=False
        )

        embed.add_field(
            name="Ping Role", 
            value=f"<@&{self.preferences.get('ping_role_id')}>" if self.preferences.get('ping_role_id') else "Not set",
            inline=False
        )

        embed.add_field(
            name="Auto-Ban", 
            value="Enabled" if self.preferences.get('auto_ban') else "Disabled",
            inline=False
        )

        embed.add_field(
            name="Prefix", 
            value=f"`{self.preferences.get('prefix', '-')}`",
            inline=False
        )

        # Show the updated dashboard
        await interaction.response.edit_message(embed=embed, view=self.view)


class AlertChannelPingView(discord.ui.View):
    """View that waits for a channel ping"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        super().__init__(timeout=60)  # Only give them a minute to ping
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Register this view for channel mention handling
        self.bot.cog_instances["Dashboard"].channel_ping_views[guild_id] = self

        # Add a button to confirm after pinging
        self.add_item(AlertChannelConfirmButton(self.bot, self.guild_id, self.preferences))

    async def on_timeout(self):
        """Clean up when the view times out"""
        # Remove this view from the tracking dict
        if self.guild_id in self.bot.cog_instances["Dashboard"].channel_ping_views:
            del self.bot.cog_instances["Dashboard"].channel_ping_views[self.guild_id]


class AlertChannelConfirmButton(discord.ui.Button):
    """Button to confirm channel selection after pinging"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        super().__init__(
            label="I've pinged the channel",
            style=discord.ButtonStyle.primary,
            emoji="✅"
        )

    async def callback(self, interaction: discord.Interaction):
        """Check if a channel has been pinged and save it"""
        dashboard_cog = self.bot.cog_instances["Dashboard"]

        # Check if we've received a channel ping for this guild
        if self.guild_id in dashboard_cog.channel_selections:
            # Get the channel ID
            channel_id = dashboard_cog.channel_selections[self.guild_id]

            # Save to preferences
            self.preferences["alert_channel_id"] = channel_id

            # Save to database
            async with aiosqlite.connect("database.db") as db:
                await db.execute(
                    "UPDATE servers SET preferences = ? WHERE server_id = ?",
                    (json.dumps(self.preferences), self.guild_id)
                )
                await db.commit()

            # Clean up
            if self.guild_id in dashboard_cog.channel_ping_views:
                del dashboard_cog.channel_ping_views[self.guild_id]
            if self.guild_id in dashboard_cog.channel_selections:
                del dashboard_cog.channel_selections[self.guild_id]

            # Let them know it worked
            await interaction.response.edit_message(
                content=f"Alert channel updated to <#{channel_id}>",
                view=None
            )
        else:
            # No channel ping received yet
            await interaction.response.send_message(
                "Please ping a channel first by typing `#channel-name` in the chat.",
                ephemeral=True
            )


class PingRolePingView(discord.ui.View):
    """View that waits for a role ping"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        super().__init__(timeout=60)  # Only give them a minute to ping
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Register this view for role mention handling
        self.bot.cog_instances["Dashboard"].role_ping_views[guild_id] = self

        # Add buttons to confirm after pinging or remove the ping role
        self.add_item(PingRoleConfirmButton(self.bot, self.guild_id, self.preferences))
        self.add_item(RemovePingRoleButton(self.bot, self.guild_id, self.preferences))

    async def on_timeout(self):
        """Clean up when the view times out"""
        # Remove this view from the tracking dict
        if self.guild_id in self.bot.cog_instances["Dashboard"].role_ping_views:
            del self.bot.cog_instances["Dashboard"].role_ping_views[self.guild_id]


class PingRoleConfirmButton(discord.ui.Button):
    """Button to confirm role selection after pinging"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        super().__init__(
            label="I've pinged the role",
            style=discord.ButtonStyle.primary,
            emoji="✅"
        )

    async def callback(self, interaction: discord.Interaction):
        """Check if a role has been pinged and save it"""
        dashboard_cog = self.bot.cog_instances["Dashboard"]

        # Check if we've received a role ping for this guild
        if self.guild_id in dashboard_cog.role_selections:
            # Get the role ID
            role_id = dashboard_cog.role_selections[self.guild_id]

            # Save to preferences
            self.preferences["ping_role_id"] = role_id

            # Save to database
            async with aiosqlite.connect("database.db") as db:
                await db.execute(
                    "UPDATE servers SET preferences = ? WHERE server_id = ?",
                    (json.dumps(self.preferences), self.guild_id)
                )
                await db.commit()

            # Clean up
            if self.guild_id in dashboard_cog.role_ping_views:
                del dashboard_cog.role_ping_views[self.guild_id]
            if self.guild_id in dashboard_cog.role_selections:
                del dashboard_cog.role_selections[self.guild_id]

            # Let them know it worked
            await interaction.response.edit_message(
                content=f"Ping role updated to <@&{role_id}>",
                view=None
            )
        else:
            # No role ping received yet
            await interaction.response.send_message(
                "Please ping a role first by typing `@role-name` in the chat.",
                ephemeral=True
            )


class RemovePingRoleButton(discord.ui.Button):
    """Button to remove the ping role"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        super().__init__(
            label="Remove Ping Role",
            style=discord.ButtonStyle.danger,
            emoji="❌"
        )

    async def callback(self, interaction: discord.Interaction):
        """Remove the ping role"""
        dashboard_cog = self.bot.cog_instances["Dashboard"]

        # Remove the ping role from preferences
        if "ping_role_id" in self.preferences:
            del self.preferences["ping_role_id"]

        # Save to database
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "UPDATE servers SET preferences = ? WHERE server_id = ?",
                (json.dumps(self.preferences), self.guild_id)
            )
            await db.commit()

        # Clean up
        if self.guild_id in dashboard_cog.role_ping_views:
            del dashboard_cog.role_ping_views[self.guild_id]
        if self.guild_id in dashboard_cog.role_selections:
            del dashboard_cog.role_selections[self.guild_id]

        # Let them know it worked
        await interaction.response.edit_message(
            content="Ping role removed - no role will be pinged for alerts",
            view=None
        )


def setup(bot):
    # Hook up our dashboard cog to the bot
    bot.add_cog(Dashboard(bot))
