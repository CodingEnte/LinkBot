import json
from typing import List, Optional

import aiosqlite
import discord
from discord.ext import commands
from discord.ext.bridge import bridge_command
from ezcord.internal.dc import slash_command


class Dashboard(commands.Cog):
    """Cog for server dashboard functionality"""

    def __init__(self, bot):
        self.bot = bot
        # List of available prefixes
        self.available_prefixes = ["!", ":", ".", ",", "-", "?", ";", "*"]

    @slash_command(name="dashboard", description="Open the server settings dashboard")
    @commands.guild_only()
    @discord.default_permissions(administrator=True)
    async def dashboard(self, ctx):
        # Get current server settings
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT preferences FROM servers WHERE server_id = ?",
                (ctx.guild.id,)
            ) as cursor:
                data = await cursor.fetchone()

                if not data:
                    # If server doesn't exist in DB, show error
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
                    preferences = {}

        # Create dashboard embed
        embed = discord.Embed(
            title="Server Dashboard",
            description="Manage your server settings using the buttons below.",
            color=discord.Color.blue()
        )

        # Add current settings to embed
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

        # Send dashboard with view
        await ctx.respond(
            embed=embed,
            view=DashboardView(self.bot, ctx.guild.id, preferences),
            ephemeral=True
        )


class DashboardView(discord.ui.View):
    """View for the server dashboard"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Add prefix select menu
        self.add_item(PrefixSelect(self.bot, self.guild_id, self.preferences))

        # Update the toggle_auto_ban button style based on preferences
        # This needs to be done after the view is initialized with all buttons
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Toggle Auto-Ban":
                child.style = discord.ButtonStyle.danger if preferences.get("auto_ban", False) else discord.ButtonStyle.success

    @discord.ui.button(label="Change Alert Channel", style=discord.ButtonStyle.primary, emoji="📢", row=1)
    async def change_alert_channel(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Button to change the alert channel"""
        await interaction.response.send_message(
            "Select a channel for ban alerts:",
            view=AlertChannelView(self.bot, self.guild_id, self.preferences),
            ephemeral=True
        )

    @discord.ui.button(label="Change Ping Role", style=discord.ButtonStyle.primary, emoji="🔔", row=1)
    async def change_ping_role(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Button to change the ping role"""
        await interaction.response.send_message(
            "Select a role to ping for ban alerts:",
            view=PingRoleView(self.bot, self.guild_id, self.preferences),
            ephemeral=True
        )

    @discord.ui.button(
        label="Toggle Auto-Ban", 
        style=discord.ButtonStyle.primary,  # Default style, will be updated in __init__
        emoji="🔄",
        row=2
    )
    async def toggle_auto_ban(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Button to toggle auto-ban setting"""
        # Toggle auto-ban setting
        current_setting = self.preferences.get("auto_ban", False)
        self.preferences["auto_ban"] = not current_setting

        # Update database
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "UPDATE servers SET preferences = ? WHERE server_id = ?",
                (json.dumps(self.preferences), self.guild_id)
            )
            await db.commit()

        # Update button style
        button.style = discord.ButtonStyle.danger if self.preferences["auto_ban"] else discord.ButtonStyle.success

        # Create updated embed
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

        # Update message
        await interaction.response.edit_message(embed=embed, view=self)


class PrefixSelect(discord.ui.Select):
    """Select menu for choosing a prefix"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Get current prefix
        current_prefix = preferences.get("prefix", "-")

        # Create options for all available prefixes
        options = [
            discord.SelectOption(
                label=prefix,
                value=prefix,
                description=f"Set {prefix} as the command prefix",
                default=(prefix == current_prefix)
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
        """Callback for when a prefix is selected"""
        # Get selected prefix
        selected_prefix = self.values[0]

        # Update preferences
        self.preferences["prefix"] = selected_prefix

        # Update database
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "UPDATE servers SET preferences = ? WHERE server_id = ?",
                (json.dumps(self.preferences), self.guild_id)
            )
            await db.commit()

        # Update select menu
        for option in self.options:
            option.default = (option.value == selected_prefix)

        # Create updated embed
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

        # Update message
        await interaction.response.edit_message(embed=embed, view=self.view)


class AlertChannelView(discord.ui.View):
    """View for selecting an alert channel"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        super().__init__(timeout=60)  # 1 minute timeout
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Add channel select
        self.add_item(AlertChannelSelect(self.bot, self.guild_id, self.preferences))


class AlertChannelSelect(discord.ui.Select):
    """Select menu for choosing an alert channel"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Get guild channels
        guild = self.bot.get_guild(guild_id)

        # Create options for text channels
        options = [
            discord.SelectOption(
                label=f"#{channel.name}",
                value=str(channel.id),
                description=f"Set {channel.name} as the alert channel"
            )
            for channel in guild.text_channels[:25]  # Limit to 25 channels
        ]

        super().__init__(
            placeholder="Select a channel for ban alerts",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        """Callback for when a channel is selected"""
        # Get selected channel
        channel_id = int(self.values[0])

        # Update preferences
        self.preferences["alert_channel_id"] = channel_id

        # Update database
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "UPDATE servers SET preferences = ? WHERE server_id = ?",
                (json.dumps(self.preferences), self.guild_id)
            )
            await db.commit()

        # Send confirmation
        await interaction.response.edit_message(
            content=f"Alert channel updated to <#{channel_id}>",
            view=None
        )


class PingRoleView(discord.ui.View):
    """View for selecting a ping role"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        super().__init__(timeout=60)  # 1 minute timeout
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Add role select
        self.add_item(PingRoleSelect(self.bot, self.guild_id, self.preferences))


class PingRoleSelect(discord.ui.Select):
    """Select menu for choosing a ping role"""

    def __init__(self, bot, guild_id: int, preferences: dict):
        self.bot = bot
        self.guild_id = guild_id
        self.preferences = preferences

        # Get guild roles
        guild = self.bot.get_guild(guild_id)

        # Create options for roles
        options = [
            discord.SelectOption(
                label=f"@{role.name}",
                value=str(role.id),
                description=f"Ping {role.name} for ban alerts"
            )
            for role in guild.roles
            if not role.is_default() and not role.is_bot_managed()
        ][:25]  # Limit to 25 roles

        # Add option to remove ping role
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
        """Callback for when a role is selected"""
        # Get selected role
        role_id = self.values[0]

        if role_id == "0":
            # Remove ping role
            if "ping_role_id" in self.preferences:
                del self.preferences["ping_role_id"]

            # Update database
            async with aiosqlite.connect("database.db") as db:
                await db.execute(
                    "UPDATE servers SET preferences = ? WHERE server_id = ?",
                    (json.dumps(self.preferences), self.guild_id)
                )
                await db.commit()

            # Send confirmation
            await interaction.response.edit_message(
                content="Ping role removed",
                view=None
            )
        else:
            # Update preferences
            self.preferences["ping_role_id"] = int(role_id)

            # Update database
            async with aiosqlite.connect("database.db") as db:
                await db.execute(
                    "UPDATE servers SET preferences = ? WHERE server_id = ?",
                    (json.dumps(self.preferences), self.guild_id)
                )
                await db.commit()

            # Send confirmation
            await interaction.response.edit_message(
                content=f"Ping role updated to <@&{role_id}>",
                view=None
            )


def setup(bot):
    bot.add_cog(Dashboard(bot))
