import difflib
import json
import logging
import os
from datetime import datetime

import aiosqlite
import discord
import ezcord
from colorama import Fore, Style
from discord.ext import commands, tasks

intents = discord.Intents.all()

ezcord.set_log(
    log_level=logging.DEBUG,
    file=True,
    discord_log_level=logging.DEBUG,
    webhook_url=os.getenv("ERROR_WEBHOOK_URL")
)

embed = discord.Embed(
    title="<:attention:1361369583197487216> An error has occurred",
    description=f"```{ezcord.error}```",
    color=discord.Color.dark_red()
)
embed.set_footer(text=f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
ezcord.set_embed_templates(error_embed=embed, warn_embed=embed)

# Quick lookup for status strings
status_map = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}

async def get_prefix(bot, message):
    # Fallback prefix if all else fails
    default_prefix = "-"

    # DMs just use the default prefix
    if message.guild is None:
        return default_prefix

    # Let's check if this server has a custom prefix
    async with aiosqlite.connect("database.db") as db:
        async with db.execute(
            "SELECT preferences FROM servers WHERE server_id = ?",
            (message.guild.id,)
        ) as cursor:
            data = await cursor.fetchone()

            if not data:
                return default_prefix

            try:
                preferences = json.loads(data[0])
                return preferences.get("prefix", default_prefix)
            except (json.JSONDecodeError, TypeError):
                # Something went wrong with the JSON, just use default
                return default_prefix

# Update the bot's status to show how many servers we're in
async def update_activity(bot_instance):
    server_count = len(bot_instance.guilds)
    activity = discord.Streaming(
        name=f"Protecting {server_count} Servers",
        url="https://www.twitch.tv/discord"  # Twitch URL needed for streaming status to work
    )
    await bot_instance.change_presence(activity=activity)

# Update our server count every half minute
@tasks.loop(seconds=30)
async def update_guild_count():
    await update_activity(bot)

# Don't start the task until the bot is good to go
@update_guild_count.before_loop
async def before_update_guild_count():
    await bot.wait_until_ready()

bot = ezcord.BridgeBot(
    intents=intents,
    status=discord.Status.online,  # Start with online, we'll switch to streaming later
    command_prefix=get_prefix,
    help_command=None,
    ready_event=None,
    ignored_errors=[commands.CommandOnCooldown, commands.MissingPermissions],
    error_webhook_url=os.getenv("d"),
    sync_commands_debug=True
)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        retry_after = round(error.retry_after, 2)
        await ctx.respond(embed=discord.Embed(description=f"<:cooldown:1302653980408680448> You're on cooldown. Try again in **{retry_after}** seconds."), delete_after=5)

    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=discord.Embed(description="You don't have the required permissions to use this command.", color=discord.Color.embed_background()), delete_after=5)

    elif isinstance(error, commands.CommandNotFound):
        invoked_command = ctx.invoked_with.lower()  # Convert to lowercase
        available_commands = [command.name.lower() for command in bot.commands]  # Convert to lowercase

        close_matches = difflib.get_close_matches(invoked_command, available_commands, n=1, cutoff=0.8)
        if close_matches:
            suggestion = close_matches[0]
            original_command_name = next(command.name for command in bot.commands if command.name.lower() == suggestion)
            await ctx.send(f"Command not found. Did you mean: `{original_command_name}`?", delete_after=5)
        else:
            await ctx.send(embed=discord.Embed(description=f"An error occurred: {str(error)}", color=discord.Color.embed_background()), delete_after=5)

    elif isinstance(error, discord.errors.Forbidden):
        await ctx.send(embed=discord.Embed(description="<:cross:1310669944287006730> The bot lacks the necessary permissions to execute this command.", color=discord.Color.embed_background()))

    elif isinstance(error, IndexError):  # Handle `list index out of range` here
        await ctx.send(
            embed=discord.Embed(
                description=f"<:error:1302653980408680448> An error occurred while processing your command. Please try again or contact support.",
                color=discord.Color.red(),
            ),
            delete_after=5,
        )
        print(f"[ERROR] {error} in command: {ctx.command}")

@bot.event
async def on_guild_join(guild):
    """Bot joined a new server! Update our server count and send welcome DM to owner."""
    # Gotta keep that status message up-to-date
    await update_activity(bot)
    print(f"Bot joined {guild.name} (ID: {guild.id}). Updated server count in activity.")

    # Send welcome DM to server owner
    if guild.owner:
        try:
            embeds = [
                discord.Embed(
                    color=16711753,
                )
                .set_image(url="https://i.postimg.cc/jdzHnsPY/Banner.png"),
                discord.Embed(
                    color=16711753,
                    description=f"# Thank You!\n**Hi {guild.owner.mention} for adding <:LinkLogo:1403487277388398683> __LinkBot__ to *{guild.name}***\n—",
                )
                .set_author(
                    name="CrafEnte - LinkBot Developer",
                    url="https://entes-portfolio.fly.dev",
                    icon_url="https://i.postimg.cc/g2zYyDXk/CELP-gif.gif",
                )
                .set_image(url="https://i.postimg.cc/RFKpH1jd/Def-Banner.png")
                .add_field(
                    name="What LinkBot Does",
                    value="LinkBot connects multiple Discord servers to share ban alerts, allowing servers to ban and prevent raids before the raiders can even join the server.",
                    inline=False,
                )
                .add_field(
                    name="How LinkBot Does That",
                    value="LinkBot collects data of bans from all the servers it was added and set up in to detect raiders, ToS breakers, racist people etc. to send alerts to you and all other server, eliminating threats immediatly.",
                    inline=False,
                )
                .add_field(
                    name="Setting Up LinkBot",
                    value="LinkBot Can easely be set up by just using the **/setup** command. Everything else will be explained in the setup tutorial. It's just a few clicks to save and protect your server.",
                    inline=False,
                ),
                discord.Embed(
                    color=16711753,
                    description="## Important Links\n`-` [Support Server](<https://discord.gg/8zrgFgSPfM>)\n`-` [Ente's Portfolio](https://entes-portfolio.fly.dev)\n",
                )
                .set_image(url="https://i.postimg.cc/RFKpH1jd/Def-Banner.png")
                .set_footer(
                    text="Link Bot Systems - Thank You For Adding Me!",
                    icon_url="https://i.postimg.cc/MHgQMLKT/Logo.png",
                ),
            ]

            await guild.owner.send(embeds=embeds, content=guild.owner.mention)
            print(f"Sent welcome DM to {guild.owner.name}#{guild.owner.discriminator} (ID: {guild.owner.id})")
        except discord.Forbidden:
            print(f"Could not send DM to {guild.owner.name}#{guild.owner.discriminator} (ID: {guild.owner.id}) - DMs disabled")
        except Exception as e:
            print(f"Error sending DM to server owner: {e}")

@bot.event
async def on_guild_remove(guild):
    """Oof, we got kicked from a server. Clean up their data and update our count."""
    async with aiosqlite.connect("database.db") as db:
        # Wipe this server from our database
        await db.execute("DELETE FROM servers WHERE server_id = ?", (guild.id,))

        # Also remove any bans they issued
        await db.execute("DELETE FROM bans WHERE origin_server_id = ?", (guild.id,))

        await db.commit()

    # Fix our status with the new server count
    await update_activity(bot)

    print(f"Bot was removed from {guild.name} (ID: {guild.id}). All data for this server has been removed.")

@bot.event
async def on_ready():
    # Initialize cog_instances dictionary to store references to cog instances
    bot.cog_instances = {}
    for cog_name, cog in bot.cogs.items():
        bot.cog_instances[cog_name] = cog

    # Update bot activity with current server count
    await update_activity(bot)

    # Start the task to update guild count every 30 seconds
    if not update_guild_count.is_running():
        update_guild_count.start()

    execute_directory = os.getcwd()
    cogs_directory = os.path.join(execute_directory, 'cogs')

    def get_files_from_directory(directory, file_limit=6):
        try:
            all_files = [file for file in os.listdir(directory) if os.path.isfile(os.path.join(directory, file))]
            return all_files[:file_limit]
        except FileNotFoundError:
            return ["Directory not found"]

    cog_files = get_files_from_directory(cogs_directory)
    main_files = get_files_from_directory(execute_directory)
    file_count = len(cog_files) + len(main_files)

    command_count = len(bot.commands)
    pycord_version = discord.__version__
    latency = bot.latency * 1000  # Convert to milliseconds

    print(Fore.LIGHTWHITE_EX + Style.BRIGHT + f"\n{bot.user} is online and connected to discord!")
    print(Fore.WHITE + Style.BRIGHT + "╭───────────────────────────────────────────────────────────╮" + Style.RESET_ALL)
    print(Fore.WHITE + Style.BRIGHT + "│  " + Fore.RED + Style.BRIGHT + "Bot \t\t\t" + Fore.YELLOW + "Version \t" + Fore.BLUE + "Ping \t\t" + Fore.GREEN + "Commands: \t" + Fore.MAGENTA + "Files: \t" + Style.RESET_ALL + Fore.WHITE + Style.BRIGHT + "│")
    print(Fore.WHITE + Style.BRIGHT + "│  " + Style.RESET_ALL + Fore.RED + f"{bot.user.display_name} \t" + Fore.YELLOW + f"{pycord_version} \t\t" + Fore.BLUE + f"{latency:.2f}ms \t" + Fore.GREEN + f"{command_count} \t\t\t" + Fore.MAGENTA + f"{file_count} \t\t" + Style.RESET_ALL + Fore.WHITE + Style.BRIGHT + "│")
    print(Fore.WHITE + Style.BRIGHT + "╰───────────────────────────────────────────────────────────╯" + Style.RESET_ALL)

def count_lines(base, files, dirs):
    counts = {}
    total_lines = 0
    total_chars = 0
    for path in [os.path.join(base, f) for f in files] + [
        os.path.join(root, file)
        for d in dirs
        for root, _, files in os.walk(os.path.join(base, d))
        for file in files if file.endswith(".py")
    ]:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                line_count = len(lines)
                char_count = sum(len(line) for line in lines)
                counts[path] = {'lines': line_count, 'chars': char_count}
                total_lines += line_count
                total_chars += char_count
        except Exception as e:
            print(f"Error reading {path}: {e}")
    return counts, total_lines, total_chars

@bot.event
async def on_close():
    """Time to shut down - make sure we clean up our tasks first!"""
    if update_guild_count.is_running():
        update_guild_count.cancel()
    print("Bot is shutting down. Tasks have been cancelled.")

if __name__ == "__main__":
    for filename in os.listdir("cogs"):
        if filename.endswith(".py"):
            bot.load_extension(f"cogs.{filename[:-3]}")

    files = ["main.py", "requirements.txt"]
    dirs = ["cogs"]
    counts, total_lines, total_chars = count_lines(".", files, dirs)
    print(f"Total lines: {total_lines}")
    print(f"Total characters: {total_chars}")

bot.run(os.getenv("TOKEN"))
