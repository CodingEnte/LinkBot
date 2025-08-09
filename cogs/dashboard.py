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

    @slash_command(name="dashboard", description="Open the server settings dashboard")
    @commands.guild_only()
    @discord.default_permissions(administrator=True)
    async def dashboard(self, ctx):
        check = await preChecks(ctx)
        if check is True:
            return
        
        """Opens the server settings dashboard for adminis"""
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
        """Opens the channel picker when clicked"""
        await interaction.response.send_message(
            "Select a channel for ban alerts:",
            view=AlertChannelView(self.bot, self.guild_id, self.preferences),
            ephemeral=True
        )

    @discord.ui.button(label="Change Ping Role", style=discord.ButtonStyle.primary, emoji="🔔", row=1)
    async def change_ping_role(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Shows the role selector dropdown"""
        await interaction.response.send_message(
            "Select a role to ping for ban alerts:",
            view=PingRoleView(self.bot, self.guild_id, self.preferences),
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


class AlertChannelView(discord.ui.View):
    """Container for the channel dropdown menu"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        super().__init__(timeout=60)  # Only give them a minute to pick
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Add the channel dropdown
        self.add_item(AlertChannelSelect(self.bot, self.guild_id, self.preferences))


class AlertChannelSelect(discord.ui.Select):
    """Dropdown for picking which channel gets ban alerts"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Get all the server's channels
        guild = self.bot.get_guild(guild_id)

        # Build the dropdown options from text channels
        options = [
            discord.SelectOption(
                label=f"#{channel.name}",
                value=str(channel.id),
                description=f"Set {channel.name} as the alert channel"
            )
            for channel in guild.text_channels[:25]  # Discord only allows 25 options max
        ]

        super().__init__(
            placeholder="Select a channel for ban alerts",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        """When they pick a channel, save it and confirm"""
        # Convert the selected value to an int
        channel_id = int(self.values[0])

        # Remember their choice
        self.preferences["alert_channel_id"] = channel_id

        # Save to database
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "UPDATE servers SET preferences = ? WHERE server_id = ?",
                (json.dumps(self.preferences), self.guild_id)
            )
            await db.commit()

        # Let them know it worked
        await interaction.response.edit_message(
            content=f"Alert channel updated to <#{channel_id}>",
            view=None
        )


class PingRoleView(discord.ui.View):
    """Wrapper for the role picker dropdown"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        super().__init__(timeout=60)  # Close after a minute if they don't pick
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Add the role dropdown
        self.add_item(PingRoleSelect(self.bot, self.guild_id, self.preferences))


class PingRoleSelect(discord.ui.Select):
    """Dropdown to pick which role gets pinged for ban alerts"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Grab all the server's roles
        guild = self.bot.get_guild(guild_id)

        # Make an option for each role (except @everyone and bot roles)
        options = [
            discord.SelectOption(
                label=f"@{role.name}",
                value=str(role.id),
                description=f"Ping {role.name} for ban alerts"
            )
            for role in guild.roles
            if not role.is_default() and not role.is_bot_managed()
        ][:25]  # Keep under Discord's 25 option limit

        # Also add an option to turn off pings
        options.append(
            discord.SelectOption(
                label="None",
                value="0",
                description="Don't ping any role"
            )
        )

        super().__init__(
            placeholder="Select a role to ping for ban alerts",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        """Handles role selection and saves the choice"""
        # Get what they picked
        role_id = self.values[0]

        if role_id == "0":
            # They chose "None" - remove any existing ping role
            if "ping_role_id" in self.preferences:
                del self.preferences["ping_role_id"]

            # Save to DB
            async with aiosqlite.connect("database.db") as db:
                await db.execute(
                    "UPDATE servers SET preferences = ? WHERE server_id = ?",
                    (json.dumps(self.preferences), self.guild_id)
                )
                await db.commit()

            # Let them know it worked
            await interaction.response.edit_message(
                content="Ping role removed - no role will be pinged for alerts",
                view=None
            )
        else:
            # They picked a role - save it
            self.preferences["ping_role_id"] = int(role_id)

            # Update the database
            async with aiosqlite.connect("database.db") as db:
                await db.execute(
                    "UPDATE servers SET preferences = ? WHERE server_id = ?",
                    (json.dumps(self.preferences), self.guild_id)
                )
                await db.commit()

            # Confirm their choice
            await interaction.response.edit_message(
                content=f"Ping role updated to <@&{role_id}>",
                view=None
            )


def setup(bot):
    # Hook up our dashboard cog to the bot
    bot.add_cog(Dashboard(bot))
