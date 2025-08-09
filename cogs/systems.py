from discord.ext import commands
import aiosqlite
import json
from discord.ext.bridge import bridge_command
from discord.ext.commands import command
from ezcord import discord
from ezcord.internal.dc import slash_command


async def preChecks(ctx_or_interaction):
    """Quick check if bot is in maintenance mode or if user is allowed to use commands"""
    message = "🛠️ The bot is currently under maintenance. Try again later.\n-# The LinkBot team is aware of the issue in the setup when selecting a channel. We are working on a solution and will deploy it as soon as possible. Please reach out at our [developer's portfolio](<https://entes-portfolio.fly.dev>)"

    # 0 = bot is online, 1 = maintenance mode
    lockState = 1

    # Figure out if this is a slash command or text command
    is_interaction = isinstance(ctx_or_interaction, discord.Interaction)

    # Get the user ID regardless of command type
    user_id = ctx_or_interaction.user.id if is_interaction else ctx_or_interaction.author.id

    # If we're in maintenance mode and user isn't on the whitelist
    if lockState == 1 and user_id not in [780865480038678528,0]:
        if is_interaction:
            # For slash commands
            await ctx_or_interaction.response.send_message(
                embed=discord.Embed(description=message, color=discord.Color.yellow()),
                ephemeral=True
            )
            print(f"Locked - {user_id}")
        else:
            # For text commands
            await ctx_or_interaction.send(
                embed=discord.Embed(description=message, color=discord.Color.yellow()),
                delete_after=5
            )
            print(f"Locked - {user_id}")
        return True  # Block the command from running

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
            description="Please ping the channel where ban alerts from other servers will be sent. "
                        "This should be a channel that your moderators can access.\n\n"
                        "**Example:** #alerts"
        )
        .set_footer(
            text="LinkBot setup | 3/5"
        ),
        "skippable": False,
        "type": "channel_ping"
    },
    "Step4": {
        "embed": discord.Embed(
            title="Ping Role",
            description="Optionally, ping a role to be notified when ban alerts are received. "
                        "This can help ensure your moderation team is notified promptly.\n\n"
                        "**Example:** @Moderators\n\n"
                        "You can skip this step if you don't want to ping any role."
        )
        .set_footer(
            text="LinkBot setup | 4/5"
        ),
        "skippable": True,
        "type": "role_ping"
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
    """Core system commands and setup wizard"""

    def __init__(self, bot):
        self.bot = bot
        self.setup_data = {}  # Temp storage during setup wizard
        self.active_setups = set()  # Track guilds with active setup processes
        self.channel_ping_views = {}  # Track views waiting for channel pings
        self.role_ping_views = {}  # Track views waiting for role pings
        self.setup_owners = {}  # Track which user started the setup for each guild

    @commands.Cog.listener()
    async def on_ready(self):
        """Make sure our database is ready to go when the bot starts"""
        async with aiosqlite.connect("database.db") as db:
            # Create our main servers table if it's not there
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

            # Double-check the preferences column exists (for older installs)
            async with db.execute("PRAGMA table_info(servers)") as cursor:
                columns = await cursor.fetchall()
                column_names = [column[1] for column in columns]

                if "preferences" not in column_names:
                    # Add it if missing - happens with older bot versions
                    await db.execute("ALTER TABLE servers ADD COLUMN preferences TEXT DEFAULT '{}'")
                    await db.commit()
                    print("Added missing 'preferences' column to servers table")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Set up a new server when we join it"""
        # Add the server to our database with default settings
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "INSERT OR IGNORE INTO servers (server_id) VALUES (?)",
                (guild.id,)
            )
            await db.commit()

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for channel and role mentions during setup"""
        # Ignore messages from bots
        if message.author.bot:
            return

        # Check if the bot is mentioned in the message
        if self.bot.user in message.mentions:
            # Save the channel where the bot was mentioned
            channel = message.channel

            # Check if this guild has an active setup
            if message.guild and message.guild.id in self.active_setups:
                # Check if the message is from the user who started the setup
                if message.author.id == self.setup_owners.get(message.guild.id):
                    # Save the channel ID to setup data
                    self.setup_data[message.guild.id]["alert_channel_id"] = channel.id

                    # Get the view and update the embed if it exists
                    if message.guild.id in self.channel_ping_views:
                        view = self.channel_ping_views[message.guild.id]
                        if view and view.message:
                            # Update the embed to show the selected channel
                            embed = view.message.embeds[0]
                            embed.description = f"Please ping the channel where ban alerts from other servers will be sent. " \
                                              f"This should be a channel that your moderators can access.\n\n" \
                                              f"**Example:** #alerts\n\n" \
                                              f"**Selected Channel:** {channel.mention}"

                            # Enable the continue button
                            for child in view.children:
                                if isinstance(child, ChannelPingButton):
                                    child.disabled = False

                            # Update the message with the new embed and enabled button
                            await view.message.edit(embed=embed, view=view)

                    # Send confirmation message
                    await message.reply(f"#{channel.name} was saved. Return to the setup panel to continue or ping the bot in a different channel to update your choice.")
                else:
                    # If not the setup owner, just acknowledge the ping
                    await message.reply("Only the user who started the setup can select a channel.")
            else:
                # If no active setup, just acknowledge the ping
                await message.reply("There is no active setup in this server. Use `/setup` to start the setup process.")

            return

        # Check if this guild has an active setup
        if message.guild and message.guild.id in self.active_setups:
            # Check if the message is from the user who started the setup
            if message.author.id != self.setup_owners.get(message.guild.id):
                return

            # Check for channel mentions
            if message.channel_mentions and message.guild.id in self.channel_ping_views:
                # Get the first mentioned channel
                channel = message.channel_mentions[0]

                # Save the channel ID to setup data
                self.setup_data[message.guild.id]["alert_channel_id"] = channel.id

                # Get the view and update the embed
                view = self.channel_ping_views[message.guild.id]
                if view and view.message:
                    # Update the embed to show the selected channel
                    embed = view.message.embeds[0]
                    embed.description = f"Please ping the channel where ban alerts from other servers will be sent. " \
                                       f"This should be a channel that your moderators can access.\n\n" \
                                       f"**Example:** #alerts\n\n" \
                                       f"**Selected Channel:** {channel.mention}"

                    # Enable the continue button
                    for child in view.children:
                        if isinstance(child, ChannelPingButton):
                            child.disabled = False

                    # Update the message with the new embed and enabled button
                    await view.message.edit(embed=embed, view=view)

                # Acknowledge the channel selection
                await message.reply(f"Channel {channel.mention} has been selected for ban alerts. Click the button to continue.")

            # Check for role mentions
            if message.role_mentions and message.guild.id in self.role_ping_views:
                # Get the first mentioned role
                role = message.role_mentions[0]

                # Save the role ID to setup data
                self.setup_data[message.guild.id]["ping_role_id"] = role.id

                # Get the view and update the embed
                view = self.role_ping_views[message.guild.id]
                if view and view.message:
                    # Update the embed to show the selected role
                    embed = view.message.embeds[0]
                    embed.description = f"Optionally, ping a role to be notified when ban alerts are received. " \
                                       f"This can help ensure your moderation team is notified promptly.\n\n" \
                                       f"**Example:** @Moderators\n\n" \
                                       f"**Selected Role:** {role.mention}\n\n" \
                                       f"You can skip this step if you don't want to ping any role."

                    # Enable the continue button
                    for child in view.children:
                        if isinstance(child, RolePingButton):
                            child.disabled = False

                    # Update the message with the new embed and enabled button
                    await view.message.edit(embed=embed, view=view)

                # Acknowledge the role selection
                await message.reply(f"Role {role.mention} will be pinged for ban alerts. Click the button to continue.")

    @command(name="help", description="Shows help menu with features and commands")
    @commands.guild_only()
    async def help(self, ctx):
        """Show the help menu with all available commands and features"""
        # Check if bot is in maintenance mode
        check = await preChecks(ctx)
        if check is True:
            return

        # Create a nice looking help menu
        embed = discord.Embed(
            title="LinkBot Help",
            description="LinkBot connects multiple Discord servers to share ban alerts and maintain server integrity.",
            color=discord.Color.blue()
        )

        # List all the commands they can use
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

        # Explain what the bot can do
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

        # Show the help menu but delete it after 30 seconds
        await ctx.send(embed=embed, delete_after=30)

    @command(name="ping", description="Shows bot latency")
    async def ping(self, ctx):
        """Check if the bot is responsive and how fast it is"""
        # Make sure we're not in maintenance mode
        check = await preChecks(ctx)
        if check is True:
            return

        # Calculate ping in milliseconds
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Bot latency: **{latency}ms**",
            color=discord.Color.green()
        )

        # Show ping result briefly
        await ctx.send(embed=embed, delete_after=15)

    @command(name="prefix", description="Shows or sets custom prefix")
    @commands.guild_only()
    async def prefix(self, ctx, new_prefix: str = None):
        """View or change the command prefix for this server"""
        # Check maintenance mode
        check = await preChecks(ctx)
        if check is True:
            return

        # Just showing the current prefix
        if new_prefix is None:
            async with aiosqlite.connect("database.db") as db:
                async with db.execute(
                    "SELECT preferences FROM servers WHERE server_id = ?",
                    (ctx.guild.id,)
                ) as cursor:
                    data = await cursor.fetchone()

                if not data:
                    # First time using the bot? Add the server to our DB
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
                        # Bad JSON? Just use empty defaults
                        preferences = {}

            # Get their current prefix (or use - as fallback)
            current_prefix = preferences.get("prefix", "-")

            embed = discord.Embed(
                title="Prefix Settings",
                description=f"Current prefix: `{current_prefix}`\n\nUse `/prefix <new_prefix>` to change it.",
                color=discord.Color.blue()
            )

            await ctx.send(embed=embed, delete_after=30)
            return

        # Changing the prefix - make sure they're an admin
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You need administrator permissions to change the prefix.", delete_after=10)
            return

        # Save the new prefix to the database
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT preferences FROM servers WHERE server_id = ?",
                (ctx.guild.id,)
            ) as cursor:
                data = await cursor.fetchone()

            if not data:
                # Server not in DB yet? Create it with the new prefix
                preferences = {"prefix": new_prefix}
                await db.execute(
                    "INSERT INTO servers (server_id, preferences) VALUES (?, ?)",
                    (ctx.guild.id, json.dumps(preferences))
                )
            else:
                # Update their existing settings with the new prefix
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

        # Let them know it worked
        embed = discord.Embed(
            title="Prefix Updated",
            description=f"Prefix has been updated to: `{new_prefix}`",
            color=discord.Color.green()
        )

        await ctx.send(embed=embed, delete_after=30)

    @slash_command(name="setup", description="Configure LinkBot for your server")
    @commands.guild_only()
    @discord.default_permissions(administrator=True)
    async def setup(self, ctx):
        """Run the initial setup wizard for LinkBot"""
        # Make sure we're not in maintenance mode
        check = await preChecks(ctx)
        if check is True:
            return

        # Check if setup is already in progress for this guild
        if ctx.guild.id in self.active_setups:
            await ctx.respond(
                embed=discord.Embed(
                    title="Setup Already in Progress",
                    description="Someone is already running the setup wizard for this server. Please wait for them to finish or try again later.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # See if they've already run setup before
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT preferences FROM servers WHERE server_id = ?",
                (ctx.guild.id,)
            ) as cursor:
                data = await cursor.fetchone()

                if data:
                    # They're in our database already
                    try:
                        preferences = json.loads(data[0])
                        if preferences.get("alert_channel_id"):
                            # Looks like they already completed setup - send them to dashboard instead
                            embed = discord.Embed(
                                title="Server Already Set Up",
                                description="This server has already been set up. Use the dashboard to update your settings.",
                                color=discord.Color.blue()
                            )

                            # Add a handy button to open the dashboard
                            view = discord.ui.View()
                            dashboard_button = discord.ui.Button(
                                label="Open Dashboard",
                                style=discord.ButtonStyle.primary,
                                emoji="⚙️"
                            )

                            async def dashboard_callback(interaction):
                                # Try to load the dashboard
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
                        # Something's wrong with their settings JSON - let them redo setup
                        pass

        # Mark this guild as having an active setup
        self.active_setups.add(ctx.guild.id)

        # Store the user who started the setup
        self.setup_owners[ctx.guild.id] = ctx.author.id

        # Create a blank slate for the setup wizard
        self.setup_data[ctx.guild.id] = {
            "alert_channel_id": None,
            "ping_role_id": None,
            "auto_ban": False,
            "preferences": {}
        }

        # Start at the beginning of our setup wizard
        step = NewSetupPages["Step1"]
        embed = step["embed"]
        skippable = step["skippable"]

        # Show the first setup screen
        await ctx.respond(
            embed=embed, 
            view=NewSetupView(self.bot, step=1, skipable=skippable, message=None, cog=self, guild_id=ctx.guild.id), 
            ephemeral=True
        )


def setup(bot):
    # Register our systems cog with all the basic commands
    bot.add_cog(Systems(bot))

class NewSetupView(discord.ui.View):
    """The interactive setup wizard with buttons and dropdowns"""

    def __init__(self, bot, step: int, skipable: bool, message, cog, guild_id: int):
        super().__init__(timeout=300)  # 5 minute timeout for each step
        self.bot = bot
        self.step = step
        self.skipable = skipable
        self.message = message
        self.cog = cog
        self.guild_id = guild_id

        # Figure out what kind of UI elements we need for this step
        step_data = NewSetupPages[f"Step{step}"]
        step_type = step_data.get("type", "info")

        # Info steps just need a continue button, others need special inputs
        if step_type != "info":
            self.remove_item(self.children[0])  # Get rid of the continue button

        # Add the right UI elements based on what this step needs
        if step_type == "prefix_select":
            self.add_item(PrefixSelect(self.cog, self.guild_id))
        elif step_type == "channel_select":
            self.add_item(ChannelSelect(self.cog, self.guild_id))
        elif step_type == "channel_ping":
            # For channel ping, we add a continue button that will be used after the user pings a channel
            self.add_item(ChannelPingButton(self.cog, self.guild_id))
            # Register this view for channel mention handling
            self.cog.channel_ping_views[self.guild_id] = self
        elif step_type == "role_select":
            self.add_item(RoleSelect(self.cog, self.guild_id))
            # Some steps can be skipped
            if skipable:
                self.add_item(SkipButton(self.cog, self.guild_id, self.step))
        elif step_type == "role_ping":
            # For role ping, we add a continue button that will be used after the user pings a role
            self.add_item(RolePingButton(self.cog, self.guild_id))
            # Register this view for role mention handling
            self.cog.role_ping_views[self.guild_id] = self
            # Some steps can be skipped
            if skipable:
                self.add_item(SkipButton(self.cog, self.guild_id, self.step))
        elif step_type == "toggle":
            self.add_item(EnableButton(self.cog, self.guild_id))
            self.add_item(DisableButton(self.cog, self.guild_id))

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.green, emoji="✅", custom_id="continue")
    async def continue_button(self, button, interaction):
        """The main 'next' button for the setup wizard"""
        # Make sure we're not in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Check if the interaction is from the user who started the setup
        if interaction.user.id != self.cog.setup_owners.get(self.guild_id):
            await interaction.response.send_message(
                "Only the user who started the setup can continue to the next step.",
                ephemeral=True
            )
            return

        # Store the message reference for timeout handling
        self.message = interaction.message

        # Move to the next step
        await self.advance_step(interaction)

    async def advance_step(self, interaction):
        """Move to the next step in the setup process"""
        # Figure out which step comes next
        new_step = self.step + 1

        # If there's no next step, we're done with setup
        if f"Step{new_step}" not in NewSetupPages:
            # We've reached the end - save everything to the database
            await self.save_preferences(interaction)
            return

        # Get the content for the next step
        step = NewSetupPages[f"Step{new_step}"]
        embed = step["embed"]
        skippable = step["skippable"]

        # Create the UI for the next step
        new_view = NewSetupView(
            self.bot, 
            step=new_step, 
            skipable=skippable, 
            message=interaction.message if interaction.message else None,
            cog=self.cog,
            guild_id=self.guild_id
        )

        # Update the message with the new step
        if interaction.response.is_done():
            await interaction.message.edit(embed=embed, view=new_view)
        else:
            await interaction.response.edit_message(embed=embed, view=new_view)

    async def on_timeout(self):
        """Handle timeout - clean up if the user abandons the setup process"""
        # Clean up temporary data
        if self.guild_id in self.cog.setup_data:
            del self.cog.setup_data[self.guild_id]

        # Mark this guild as no longer having an active setup
        if self.guild_id in self.cog.active_setups:
            self.cog.active_setups.remove(self.guild_id)

        # Remove the setup owner
        if self.guild_id in self.cog.setup_owners:
            del self.cog.setup_owners[self.guild_id]

        # Clean up channel and role ping views
        if self.guild_id in self.cog.channel_ping_views:
            del self.cog.channel_ping_views[self.guild_id]

        if self.guild_id in self.cog.role_ping_views:
            del self.cog.role_ping_views[self.guild_id]

        # Try to update the message to show that setup timed out
        if self.message:
            try:
                embed = discord.Embed(
                    title="Setup Timed Out",
                    description="The setup process has timed out due to inactivity. Please run `/setup` again if you wish to continue.",
                    color=discord.Color.red()
                )
                await self.message.edit(embed=embed, view=None)
            except:
                # If we can't edit the message, that's okay - the cleanup is the important part
                pass

    async def save_preferences(self, interaction):
        """Save all the settings from the setup wizard to the database"""
        # Grab all the settings they chose during setup
        setup_data = self.cog.setup_data.get(self.guild_id, {})

        # Get any prefix they might have set
        setup_preferences = setup_data.get("preferences", {})

        # Bundle everything into one settings object
        preferences = {
            "alert_channel_id": setup_data.get("alert_channel_id"),
            "ping_role_id": setup_data.get("ping_role_id"),
            "auto_ban": setup_data.get("auto_ban", False),
            "blocked_servers": [],  # Start with an empty blocklist
            "prefix": setup_preferences.get("prefix", "-")  # Use their chosen prefix or default to "-"
        }

        # Store everything in the database
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "INSERT OR REPLACE INTO servers (server_id, preferences, integrity, blacklisted) VALUES (?, ?, 100, 0)",
                (self.guild_id, json.dumps(preferences))
            )
            await db.commit()

        # Create a nice completion message
        embed = discord.Embed(
            title="Setup Complete!",
            description="LinkBot has been successfully configured for your server.",
            color=discord.Color.green()
        )

        # Show them a summary of their settings
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

        # Clean up our temporary data
        if self.guild_id in self.cog.setup_data:
            del self.cog.setup_data[self.guild_id]

        # Mark this guild as no longer having an active setup
        if self.guild_id in self.cog.active_setups:
            self.cog.active_setups.remove(self.guild_id)

        # Remove the setup owner
        if self.guild_id in self.cog.setup_owners:
            del self.cog.setup_owners[self.guild_id]

        # Clean up channel and role ping views
        if self.guild_id in self.cog.channel_ping_views:
            del self.cog.channel_ping_views[self.guild_id]

        if self.guild_id in self.cog.role_ping_views:
            del self.cog.role_ping_views[self.guild_id]

        # Add a dashboard button for easy access
        view = discord.ui.View()
        dashboard_button = discord.ui.Button(
            label="Open Dashboard",
            style=discord.ButtonStyle.primary,
            emoji="⚙️"
        )

        async def dashboard_callback(button_interaction):
            # Try to open the dashboard
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

        # Show the completion message
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

        # Store the message reference for timeout handling
        self.view.message = interaction.message

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

        # Store the message reference for timeout handling
        self.view.message = interaction.message

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
        # Check if the interaction is from the user who started the setup
        if interaction.user.id != self.cog.setup_owners.get(self.guild_id):
            await interaction.response.send_message(
                "Only the user who started the setup can skip this step.",
                ephemeral=True
            )
            return

        # Store the message reference for timeout handling
        self.view.message = interaction.message

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
        # Check if the interaction is from the user who started the setup
        if interaction.user.id != self.cog.setup_owners.get(self.guild_id):
            await interaction.response.send_message(
                "Only the user who started the setup can enable auto-ban.",
                ephemeral=True
            )
            return

        # Save auto-ban setting
        self.cog.setup_data[self.guild_id]["auto_ban"] = True

        # Store the message reference for timeout handling
        self.view.message = interaction.message

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
        # Check if the interaction is from the user who started the setup
        if interaction.user.id != self.cog.setup_owners.get(self.guild_id):
            await interaction.response.send_message(
                "Only the user who started the setup can disable auto-ban.",
                ephemeral=True
            )
            return

        # Save auto-ban setting
        self.cog.setup_data[self.guild_id]["auto_ban"] = False

        # Store the message reference for timeout handling
        self.view.message = interaction.message

        # Get parent view and advance to next step
        parent_view = self.view
        await parent_view.advance_step(interaction)


class ChannelPingButton(discord.ui.Button):
    """Button that waits for a channel ping"""

    def __init__(self, cog, guild_id: int):
        self.cog = cog
        self.guild_id = guild_id

        super().__init__(
            label="Continue",
            style=discord.ButtonStyle.primary,
            emoji="✅",
            custom_id="channel_ping_button",
            disabled=True  # Button starts disabled until a channel is pinged
        )

    async def callback(self, interaction: discord.Interaction):
        # Check if the interaction is from the user who started the setup
        if interaction.user.id != self.cog.setup_owners.get(self.guild_id):
            await interaction.response.send_message(
                "Only the user who started the setup can continue to the next step.",
                ephemeral=True
            )
            return

        # Check if we've received a channel ping
        if self.guild_id in self.cog.setup_data and "alert_channel_id" in self.cog.setup_data[self.guild_id]:
            # Store the message reference for timeout handling
            self.view.message = interaction.message

            # Get parent view and advance to next step
            parent_view = self.view
            await parent_view.advance_step(interaction)
        else:
            # No channel ping received yet
            await interaction.response.send_message(
                "Please ping a channel first by typing `#channel-name` in the chat.",
                ephemeral=True
            )


class RolePingButton(discord.ui.Button):
    """Button that waits for a role ping"""

    def __init__(self, cog, guild_id: int):
        self.cog = cog
        self.guild_id = guild_id

        super().__init__(
            label="Continue",
            style=discord.ButtonStyle.primary,
            emoji="✅",
            custom_id="role_ping_button",
            disabled=True  # Button starts disabled until a role is pinged
        )

    async def callback(self, interaction: discord.Interaction):
        # Check if the interaction is from the user who started the setup
        if interaction.user.id != self.cog.setup_owners.get(self.guild_id):
            await interaction.response.send_message(
                "Only the user who started the setup can continue to the next step.",
                ephemeral=True
            )
            return

        # Check if we've received a role ping
        if self.guild_id in self.cog.setup_data and "ping_role_id" in self.cog.setup_data[self.guild_id]:
            # Store the message reference for timeout handling
            self.view.message = interaction.message

            # Get parent view and advance to next step
            parent_view = self.view
            await parent_view.advance_step(interaction)
        else:
            # No role ping received yet
            await interaction.response.send_message(
                "Please ping a role first by typing `@role-name` in the chat, or click Skip if you don't want to ping any role.",
                ephemeral=True
            )


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
        # Check if the interaction is from the user who started the setup
        if interaction.user.id != self.cog.setup_owners.get(self.guild_id):
            await interaction.response.send_message(
                "Only the user who started the setup can select a prefix.",
                ephemeral=True
            )
            return

        # Save selected prefix
        selected_prefix = self.values[0]

        # Initialize preferences if not already in setup_data
        if "preferences" not in self.cog.setup_data[self.guild_id]:
            self.cog.setup_data[self.guild_id]["preferences"] = {}

        # Save prefix to setup data
        self.cog.setup_data[self.guild_id]["preferences"]["prefix"] = selected_prefix

        # Store the message reference for timeout handling
        self.view.message = interaction.message

        # Get parent view and advance to next step
        parent_view = self.view
        await parent_view.advance_step(interaction)
