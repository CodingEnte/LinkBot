from discord.ext import commands
import aiosqlite
import json
from discord.ext.bridge import bridge_command
from ezcord import discord
from ezcord.internal.dc import slash_command


async def preChecks(ctx_or_interaction):
    message = "🛠️ The bot is currently under maintenance. Try again later.\n-# More infos can be found in the [Developer News](https://discord.com/channels/1374742971244871732/1375587166419292251)"

    lockState = 1

    is_interaction = isinstance(ctx_or_interaction, discord.Interaction)

    user_id = ctx_or_interaction.user.id if is_interaction else ctx_or_interaction.author.id

    if lockState == 1 and user_id not in [780865480038678528, 833825983895044146, 1287505614443905062]:
        if is_interaction:
            await ctx_or_interaction.response.send_message(
                embed=discord.Embed(description=message, color=discord.Color.yellow()),
                ephemeral=True
            )
            print(f"Locked - {user_id}")
        else:
            await ctx_or_interaction.respond(
                embed=discord.Embed(description=message, color=discord.Color.yellow()),
                ephemeral=True,
                delete_after=5
            )
            print(f"Locked - {user_id}")
        return True

NewSetupPages = {
    "Step1": {
        "embed": discord.Embed(
            title="Welcome to LinkBot!",
            description="Welcome to LinkBot™ - Protecting and connecting multiple servers like never before. "
                        "LinkBot™ delivers advanced raid prevention, cross-banning security, "
                        "and powerful networking tools to keep partnered servers safe and thriving."
        )
        .add_field(
            name="Getting Started",
            value="Before LinkBot can start protecting your server you will need to complete a small setup. Follow the steps to set up LinkBot."
        )
        .set_footer(
            text="LinkBot setup | 1/5"
        ),
        "skippable": False,
        "type": "info"
    },
    "Step2": {
        "embed": discord.Embed(
            title="Command Prefix",
            description="Please select a prefix for bot commands in this server. "
                        "This prefix will be used for text commands (e.g. `{prefix}help`)."
        )
        .set_footer(
            text="LinkBot setup | 2/5"
        ),
        "skippable": False,
        "type": "prefix_select"
    },
    "Step3": {
        "embed": discord.Embed(
            title="Alert Channel",
            description="Please select a channel where ban alerts from other servers will be sent. "
                        "This should be a channel that your moderators can access."
        )
        .set_footer(
            text="LinkBot setup | 3/5"
        ),
        "skippable": False,
        "type": "channel_select"
    },
    "Step4": {
        "embed": discord.Embed(
            title="Ping Role",
            description="Optionally, select a role to ping when ban alerts are received. "
                        "This can help ensure your moderation team is notified promptly."
        )
        .set_footer(
            text="LinkBot setup | 4/5"
        ),
        "skippable": True,
        "type": "role_select"
    },
    "Step5": {
        "embed": discord.Embed(
            title="Auto-Ban Setting",
            description="Would you like to enable auto-ban for servers with integrity score ≥ 50? "
                        "If enabled, users banned from high-integrity servers will be automatically banned here."
        )
        .set_footer(
            text="LinkBot setup | 5/5"
        ),
        "skippable": False,
        "type": "toggle"
    },
}

class Systems(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_data = {}  # Store temporary setup data

    @commands.Cog.listener()
    async def on_ready(self):
        async with aiosqlite.connect("database.db") as db:
            # Create the table if it doesn't exist
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS servers (
                    server_id INTEGER PRIMARY KEY,
                    preferences TEXT DEFAULT '{}',
                    integrity INTEGER DEFAULT 100,
                    blacklisted BOOLEAN DEFAULT 0
                )
                """
            )

            # Check if preferences column exists, add it if it doesn't
            async with db.execute("PRAGMA table_info(servers)") as cursor:
                columns = await cursor.fetchall()
                column_names = [column[1] for column in columns]

                if "preferences" not in column_names:
                    # Use empty JSON object as default value
                    await db.execute("ALTER TABLE servers ADD COLUMN preferences TEXT DEFAULT '{}'")
                    await db.commit()
                    print("Added missing 'preferences' column to servers table")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        # Initialize the server in the database when the bot joins
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "INSERT OR IGNORE INTO servers (server_id) VALUES (?)",
                (guild.id,)
            )
            await db.commit()

    @bridge_command(name="help", description="Shows help menu with features and commands")
    @commands.guild_only()
    async def help(self, ctx):
        check = await preChecks(ctx)
        if check is True:
            return

        embed = discord.Embed(
            title="LinkBot Help",
            description="LinkBot connects multiple Discord servers to share ban alerts and maintain server integrity.",
            color=discord.Color.blue()
        )

        # Commands section
        embed.add_field(
            name="📋 Commands",
            value=(
                "• `/help` - Shows this help menu\n"
                "• `/setup` - Configure LinkBot for your server\n"
                "• `/ping` - Check bot latency\n"
                "• `/prefix` - View or set custom prefix\n"
                "• `/search <user>` - View ban history for a user\n"
                "• `/flag <user> [reason] [proof_url]` - Flag a user for review"
            ),
            inline=False
        )

        # Features section
        embed.add_field(
            name="🔒 Features",
            value=(
                "• **Ban Alerts** - Get notified when users are banned in other servers\n"
                "• **Integrity System** - Servers gain or lose integrity based on ban acceptance\n"
                "• **Auto-Ban** - Automatically ban users from high-integrity servers\n"
                "• **Ban History** - Search for a user's ban history across all servers"
            ),
            inline=False
        )

        embed.set_footer(text="For more help, contact the bot owner")

        await ctx.respond(embed=embed, ephemeral=True)

    @bridge_command(name="ping", description="Shows bot latency")
    async def ping(self, ctx):
        check = await preChecks(ctx)
        if check is True:
            return

        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Bot latency: **{latency}ms**",
            color=discord.Color.green()
        )

        await ctx.respond(embed=embed, ephemeral=True)

    @bridge_command(name="prefix", description="Shows or sets custom prefix")
    @commands.guild_only()
    async def prefix(self, ctx, new_prefix: str = None):
        check = await preChecks(ctx)
        if check is True:
            return

        # If no new prefix is provided, show the current prefix
        if new_prefix is None:
            async with aiosqlite.connect("database.db") as db:
                async with db.execute(
                    "SELECT preferences FROM servers WHERE server_id = ?",
                    (ctx.guild.id,)
                ) as cursor:
                    data = await cursor.fetchone()

                if not data:
                    # If server doesn't exist in DB, add it with default values
                    await db.execute(
                        "INSERT INTO servers (server_id) VALUES (?)",
                        (ctx.guild.id,)
                    )
                    await db.commit()
                    preferences = {}
                else:
                    try:
                        preferences = json.loads(data[0])
                    except json.JSONDecodeError:
                        preferences = {}

            current_prefix = preferences.get("prefix", "-")

            embed = discord.Embed(
                title="Prefix Settings",
                description=f"Current prefix: `{current_prefix}`\n\nUse `/prefix <new_prefix>` to change it.",
                color=discord.Color.blue()
            )

            await ctx.respond(embed=embed, ephemeral=True)
            return

        # Check if user has admin permissions to set prefix
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond("You need administrator permissions to change the prefix.", ephemeral=True)
            return

        # Update the prefix in the database
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT preferences FROM servers WHERE server_id = ?",
                (ctx.guild.id,)
            ) as cursor:
                data = await cursor.fetchone()

            if not data:
                # If server doesn't exist in DB, add it with the new prefix
                preferences = {"prefix": new_prefix}
                await db.execute(
                    "INSERT INTO servers (server_id, preferences) VALUES (?, ?)",
                    (ctx.guild.id, json.dumps(preferences))
                )
            else:
                # Update existing preferences with the new prefix
                try:
                    preferences = json.loads(data[0])
                except json.JSONDecodeError:
                    preferences = {}

                preferences["prefix"] = new_prefix

                await db.execute(
                    "UPDATE servers SET preferences = ? WHERE server_id = ?",
                    (json.dumps(preferences), ctx.guild.id)
                )

            await db.commit()

        embed = discord.Embed(
            title="Prefix Updated",
            description=f"Prefix has been updated to: `{new_prefix}`",
            color=discord.Color.green()
        )

        await ctx.respond(embed=embed, ephemeral=True)

    @slash_command(name="setup", description="Configure LinkBot for your server")
    @commands.guild_only()
    @discord.default_permissions(administrator=True)
    async def setup(self, ctx):
        check = await preChecks(ctx)
        if check is True:
            return

        # Check if server is already set up
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT preferences FROM servers WHERE server_id = ?",
                (ctx.guild.id,)
            ) as cursor:
                data = await cursor.fetchone()

                if data:
                    # Server already exists in database
                    try:
                        preferences = json.loads(data[0])
                        if preferences.get("alert_channel_id"):
                            # Server is already set up, redirect to dashboard
                            embed = discord.Embed(
                                title="Server Already Set Up",
                                description="This server has already been set up. Use the dashboard to update your settings.",
                                color=discord.Color.blue()
                            )

                            # Create a button to open the dashboard
                            view = discord.ui.View()
                            dashboard_button = discord.ui.Button(
                                label="Open Dashboard",
                                style=discord.ButtonStyle.primary,
                                emoji="⚙️"
                            )

                            async def dashboard_callback(interaction):
                                # Get dashboard cog
                                dashboard_cog = self.bot.get_cog("Dashboard")
                                if dashboard_cog:
                                    await dashboard_cog.dashboard(interaction)
                                else:
                                    await interaction.response.send_message(
                                        "Dashboard is not available. Please try again later.",
                                        ephemeral=True
                                    )

                            dashboard_button.callback = dashboard_callback
                            view.add_item(dashboard_button)

                            await ctx.respond(embed=embed, view=view, ephemeral=True)
                            return
                    except (json.JSONDecodeError, TypeError):
                        pass  # Continue with setup if preferences are invalid

        # Initialize setup data for this guild
        self.setup_data[ctx.guild.id] = {
            "alert_channel_id": None,
            "ping_role_id": None,
            "auto_ban": False,
            "preferences": {}
        }

        # Start with Step 1
        step = NewSetupPages["Step1"]
        embed = step["embed"]
        skippable = step["skippable"]

        await ctx.respond(
            embed=embed, 
            view=NewSetupView(self.bot, step=1, skipable=skippable, message=None, cog=self, guild_id=ctx.guild.id), 
            ephemeral=True
        )


def setup(bot):
    bot.add_cog(Systems(bot))

class NewSetupView(discord.ui.View):
    def __init__(self, bot, step: int, skipable: bool, message, cog, guild_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.step = step
        self.skipable = skipable
        self.message = message
        self.cog = cog
        self.guild_id = guild_id

        # Add appropriate components based on step type
        step_data = NewSetupPages[f"Step{step}"]
        step_type = step_data.get("type", "info")

        # Remove the continue button for steps that need other inputs
        if step_type != "info":
            self.remove_item(self.children[0])  # Remove continue button

        # Add appropriate components based on step type
        if step_type == "prefix_select":
            self.add_item(PrefixSelect(self.cog, self.guild_id))
        elif step_type == "channel_select":
            self.add_item(ChannelSelect(self.cog, self.guild_id))
        elif step_type == "role_select":
            self.add_item(RoleSelect(self.cog, self.guild_id))
            if skipable:
                self.add_item(SkipButton(self.cog, self.guild_id, self.step))
        elif step_type == "toggle":
            self.add_item(EnableButton(self.cog, self.guild_id))
            self.add_item(DisableButton(self.cog, self.guild_id))

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.green, emoji="✅", custom_id="continue")
    async def continue_button(self, button, interaction):
        check = await preChecks(interaction)
        if check is True:
            return

        await self.advance_step(interaction)

    async def advance_step(self, interaction):
        new_step = self.step + 1

        # Check if we've reached the end of setup
        if f"Step{new_step}" not in NewSetupPages:
            # Save all preferences to database
            await self.save_preferences(interaction)
            return

        # Get next step data
        step = NewSetupPages[f"Step{new_step}"]
        embed = step["embed"]
        skippable = step["skippable"]

        # Create new view for next step
        new_view = NewSetupView(
            self.bot, 
            step=new_step, 
            skipable=skippable, 
            message=interaction.message if interaction.message else None,
            cog=self.cog,
            guild_id=self.guild_id
        )

        # Send or edit message
        if interaction.response.is_done():
            await interaction.message.edit(embed=embed, view=new_view)
        else:
            await interaction.response.edit_message(embed=embed, view=new_view)

    async def save_preferences(self, interaction):
        # Get setup data for this guild
        setup_data = self.cog.setup_data.get(self.guild_id, {})

        # Get preferences from setup data if they exist
        setup_preferences = setup_data.get("preferences", {})

        # Create preferences JSON
        preferences = {
            "alert_channel_id": setup_data.get("alert_channel_id"),
            "ping_role_id": setup_data.get("ping_role_id"),
            "auto_ban": setup_data.get("auto_ban", False),
            "blocked_servers": [],  # Initialize empty list for blocked servers
            "prefix": setup_preferences.get("prefix", "-")  # Get prefix from setup preferences or use default
        }

        # Save to database
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "INSERT OR REPLACE INTO servers (server_id, preferences, integrity, blacklisted) VALUES (?, ?, 100, 0)",
                (self.guild_id, json.dumps(preferences))
            )
            await db.commit()

        # Show completion message
        embed = discord.Embed(
            title="Setup Complete!",
            description="LinkBot has been successfully configured for your server.",
            color=discord.Color.green()
        )

        embed.add_field(
            name="Alert Channel", 
            value=f"<#{preferences['alert_channel_id']}>" if preferences['alert_channel_id'] else "Not set",
            inline=False
        )

        embed.add_field(
            name="Ping Role", 
            value=f"<@&{preferences['ping_role_id']}>" if preferences['ping_role_id'] else "Not set",
            inline=False
        )

        embed.add_field(
            name="Auto-Ban", 
            value="Enabled" if preferences['auto_ban'] else "Disabled",
            inline=False
        )

        embed.add_field(
            name="Prefix", 
            value=f"`{preferences['prefix']}`",
            inline=False
        )

        embed.set_footer(text="Use /dashboard to update your settings in the future.")

        # Clear setup data
        if self.guild_id in self.cog.setup_data:
            del self.cog.setup_data[self.guild_id]

        # Create a button to open the dashboard
        view = discord.ui.View()
        dashboard_button = discord.ui.Button(
            label="Open Dashboard",
            style=discord.ButtonStyle.primary,
            emoji="⚙️"
        )

        async def dashboard_callback(button_interaction):
            # Get dashboard cog
            dashboard_cog = self.bot.get_cog("Dashboard")
            if dashboard_cog:
                await dashboard_cog.dashboard(button_interaction)
            else:
                await button_interaction.response.send_message(
                    "Dashboard is not available. Please try again later.",
                    ephemeral=True
                )

        dashboard_button.callback = dashboard_callback
        view.add_item(dashboard_button)

        if interaction.response.is_done():
            await interaction.message.edit(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)

class ChannelSelect(discord.ui.Select):
    def __init__(self, cog, guild_id: int):
        self.cog = cog
        self.guild_id = guild_id

        options = [
            discord.SelectOption(
                label=f"#{channel.name}",
                value=str(channel.id),
                description=f"Set {channel.name} as the alert channel"
            )
            for channel in self.cog.bot.get_guild(guild_id).text_channels[:25]  # Limit to 25 channels
        ]

        super().__init__(
            placeholder="Select a channel for ban alerts",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="channel_select"
        )

    async def callback(self, interaction: discord.Interaction):
        # Save selected channel
        channel_id = int(self.values[0])
        self.cog.setup_data[self.guild_id]["alert_channel_id"] = channel_id

        # Get parent view and advance to next step
        parent_view = self.view
        await parent_view.advance_step(interaction)

class RoleSelect(discord.ui.Select):
    def __init__(self, cog, guild_id: int):
        self.cog = cog
        self.guild_id = guild_id

        options = [
            discord.SelectOption(
                label=f"@{role.name}",
                value=str(role.id),
                description=f"Ping {role.name} for ban alerts"
            )
            for role in self.cog.bot.get_guild(guild_id).roles
            if not role.is_default() and not role.is_bot_managed()
        ][:25]  # Limit to 25 roles

        super().__init__(
            placeholder="Select a role to ping for ban alerts",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="role_select"
        )

    async def callback(self, interaction: discord.Interaction):
        # Save selected role
        role_id = int(self.values[0])
        self.cog.setup_data[self.guild_id]["ping_role_id"] = role_id

        # Get parent view and advance to next step
        parent_view = self.view
        await parent_view.advance_step(interaction)

class SkipButton(discord.ui.Button):
    def __init__(self, cog, guild_id: int, step: int):
        self.cog = cog
        self.guild_id = guild_id
        self.step = step

        super().__init__(
            label="Skip",
            style=discord.ButtonStyle.secondary,
            custom_id=f"skip_step_{step}"
        )

    async def callback(self, interaction: discord.Interaction):
        # Get parent view and advance to next step
        parent_view = self.view
        await parent_view.advance_step(interaction)

class EnableButton(discord.ui.Button):
    def __init__(self, cog, guild_id: int):
        self.cog = cog
        self.guild_id = guild_id

        super().__init__(
            label="Enable Auto-Ban",
            style=discord.ButtonStyle.success,
            custom_id="enable_auto_ban"
        )

    async def callback(self, interaction: discord.Interaction):
        # Save auto-ban setting
        self.cog.setup_data[self.guild_id]["auto_ban"] = True

        # Get parent view and advance to next step
        parent_view = self.view
        await parent_view.advance_step(interaction)

class DisableButton(discord.ui.Button):
    def __init__(self, cog, guild_id: int):
        self.cog = cog
        self.guild_id = guild_id

        super().__init__(
            label="Disable Auto-Ban",
            style=discord.ButtonStyle.danger,
            custom_id="disable_auto_ban"
        )

    async def callback(self, interaction: discord.Interaction):
        # Save auto-ban setting
        self.cog.setup_data[self.guild_id]["auto_ban"] = False

        # Get parent view and advance to next step
        parent_view = self.view
        await parent_view.advance_step(interaction)


class PrefixSelect(discord.ui.Select):
    """Select menu for choosing a prefix during setup"""

    def __init__(self, cog, guild_id: int):
        self.cog = cog
        self.guild_id = guild_id

        # Available prefixes
        prefixes = ["!", ":", ".", ",", "-", "?", ";", "*"]

        # Create options for all available prefixes
        options = [
            discord.SelectOption(
                label=prefix,
                value=prefix,
                description=f"Set {prefix} as the command prefix",
                default=(prefix == "-")  # Default to "-"
            )
            for prefix in prefixes
        ]

        super().__init__(
            placeholder="Select a command prefix",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="prefix_select"
        )

    async def callback(self, interaction: discord.Interaction):
        # Save selected prefix
        selected_prefix = self.values[0]

        # Initialize preferences if not already in setup_data
        if "preferences" not in self.cog.setup_data[self.guild_id]:
            self.cog.setup_data[self.guild_id]["preferences"] = {}

        # Save prefix to setup data
        self.cog.setup_data[self.guild_id]["preferences"]["prefix"] = selected_prefix

        # Get parent view and advance to next step
        parent_view = self.view
        await parent_view.advance_step(interaction)
