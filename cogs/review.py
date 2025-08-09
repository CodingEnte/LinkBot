import json
from datetime import datetime

import aiosqlite
import discord
from discord.ext import commands

from cogs.systems import preChecks

class ReviewView(discord.ui.View):
    def __init__(self, flag_id: int, user_id: int, origin_server_id: int, reason: str, cog):
        super().__init__(timeout=None)  # No timeout for review buttons
        self.flag_id = flag_id
        self.user_id = user_id
        self.origin_server_id = origin_server_id
        self.reason = reason
        self.cog = cog

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green, emoji="✅", custom_id="accept_flag")
    async def accept_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Only the bot owner can use this button
        if interaction.user.id != 780865480038678528:  # LinkBot owner ID
            await interaction.response.send_message("Only the LinkBot owner can use this button.", ephemeral=True)
            return

        # Update the flag status
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "UPDATE bans SET status = ? WHERE id = ?",
                ("Accepted", self.flag_id)
            )
            await db.commit()

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        # Update the message
        embed = interaction.message.embeds[0]
        embed.add_field(name="Status", value="✅ Accepted", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send("Flag accepted.", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, emoji="❌", custom_id="reject_flag")
    async def reject_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Defer the response to prevent timeouts
        await interaction.response.defer(ephemeral=True)

        # Check if we're in maintenance mode
        check = await preChecks(interaction)
        if check is True:
            return

        # Only the bot owner can use this button
        if interaction.user.id != 780865480038678528:  # LinkBot owner ID
            await interaction.response.send_message("Only the LinkBot owner can use this button.", ephemeral=True)
            return

        # Update the flag status
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "UPDATE bans SET status = ? WHERE id = ?",
                ("Rejected", self.flag_id)
            )
            await db.commit()

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        # Update the message
        embed = interaction.message.embeds[0]
        embed.add_field(name="Status", value="❌ Rejected", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send("Flag rejected.", ephemeral=True)

class Review(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name="review", description="Review flagged users")
    async def review(self, ctx):
        # Check if we're in maintenance mode
        check = await preChecks(ctx)
        if check is True:
            return

        # Only the bot owner can use this command
        if ctx.author.id != 780865480038678528:  # LinkBot owner ID
            await ctx.respond("Only the LinkBot owner can use this command.", ephemeral=True)
            return

        # Query the database for pending flags
        async with aiosqlite.connect("database.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT b.*, s.integrity 
                FROM bans b
                JOIN servers s ON b.origin_server_id = s.server_id
                WHERE b.status = 'Review'
                ORDER BY b.flagged_at DESC
                """
            ) as cursor:
                flags = await cursor.fetchall()

        if not flags:
            await ctx.respond("No pending flags to review.", ephemeral=True)
            return

        # Send a message for each flag
        for flag in flags:
            # Get server and user info if possible
            server = self.bot.get_guild(flag["origin_server_id"])
            server_name = server.name if server else f"Unknown Server ({flag['origin_server_id']})"

            user = await self.bot.fetch_user(flag["user_id"])
            user_name = user.name if user else f"Unknown User ({flag['user_id']})"

            flagger = await self.bot.fetch_user(flag["flagged_by"])
            flagger_name = flagger.mention if flagger else f"Unknown User ({flag['flagged_by']})"

            # Format the flag date
            flag_date = datetime.fromtimestamp(flag["flagged_at"]).strftime("%Y-%m-%d %H:%M:%S")

            # Create embed for the flag
            embed = discord.Embed(
                title=f"Flag Review: {user_name}",
                description=f"User <@{flag['user_id']}> was flagged for review.",
                color=discord.Color.gold(),
                timestamp=datetime.now()
            )

            embed.add_field(name="Origin Server", value=f"{server_name} (Integrity: {flag['integrity']})", inline=False)
            embed.add_field(name="Flagged By", value=flagger_name, inline=False)
            embed.add_field(name="Reason", value=flag["ban_reason"], inline=False)
            embed.add_field(name="Date", value=flag_date, inline=False)

            # Create view with Accept and Reject buttons
            view = ReviewView(flag["id"], flag["user_id"], flag["origin_server_id"], flag["ban_reason"], self)

            await ctx.respond(embed=embed, view=view, ephemeral=True)

    @commands.slash_command(name="strike", description="Strike a server (blacklist it)")
    async def strike(self, ctx, server_id: str):
        # Check if we're in maintenance mode
        check = await preChecks(ctx)
        if check is True:
            return

        # Only the bot owner can use this command
        if ctx.author.id != 780865480038678528:  # LinkBot owner ID
            await ctx.respond("Only the LinkBot owner can use this command.", ephemeral=True)
            return

        try:
            server_id = int(server_id)
        except ValueError:
            await ctx.respond("Invalid server ID. Please provide a valid integer ID.", ephemeral=True)
            return

        # Check if the server exists in the database
        async with aiosqlite.connect("database.db") as db:
            async with db.execute(
                "SELECT blacklisted FROM servers WHERE server_id = ?",
                (server_id,)
            ) as cursor:
                server_data = await cursor.fetchone()

            if not server_data:
                # If server doesn't exist in DB, add it with blacklisted=True
                await db.execute(
                    "INSERT INTO servers (server_id, blacklisted) VALUES (?, ?)",
                    (server_id, True)
                )
                await db.commit()
            else:
                # Update existing server to blacklisted=True
                await db.execute(
                    "UPDATE servers SET blacklisted = ? WHERE server_id = ?",
                    (True, server_id)
                )
                await db.commit()

        # Try to get the server name
        server = self.bot.get_guild(server_id)
        server_name = server.name if server else f"Unknown Server ({server_id})"

        await ctx.respond(f"Server {server_name} has been struck and blacklisted.", ephemeral=True)

def setup(bot):
    bot.add_cog(Review(bot))
