import difflib
import json
import logging
import os
from datetime import datetime

import aiosqlite
import discord
import ezcord
from colorama import Fore, Style
from discord.ext import commands

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

# Map status string to discord.Status
status_map = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}

async def get_prefix(bot, message):
    # Default prefix
    default_prefix = "-"

    # If DM channel, return default prefix
    if message.guild is None:
        return default_prefix

    # Get prefix from database
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
                return default_prefix

bot = ezcord.BridgeBot(
    intents=intents,
    status=discord.Status.streaming,
    activity=discord.CustomActivity(name="Protecting {SERVERS} Servers"),
    command_prefix=get_prefix,
    help_command=None,
    ready_event=None,
    ignored_errors=[commands.CommandOnCooldown, commands.MissingPermissions],
    error_webhook_url=os.getenv("d")
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
async def on_guild_remove(guild):
    """Event handler for when the bot is removed from a guild.
    Removes all data for that guild from the database."""
    async with aiosqlite.connect("database.db") as db:
        # Remove server from servers table
        await db.execute("DELETE FROM servers WHERE server_id = ?", (guild.id,))

        # Remove any bans associated with this server
        await db.execute("DELETE FROM bans WHERE origin_server_id = ?", (guild.id,))

        await db.commit()

    print(f"Bot was removed from {guild.name} (ID: {guild.id}). All data for this server has been removed.")

@bot.event
async def on_ready():
    # Initialize cog_instances dictionary to store references to cog instances
    bot.cog_instances = {}
    for cog_name, cog in bot.cogs.items():
        bot.cog_instances[cog_name] = cog

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
