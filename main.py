# main.py

import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load the token from the .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Define the intents your bot needs
# The 'Intents.all()' is easiest for testing, but you can be more specific
# Make sure to enable the SERVER MEMBERS INTENT in the Developer Portal (Step 3)
intents = discord.Intents.default()
intents.members = True
intents.message_content = True 

# Initialize the bot with a command prefix
# We'll use the new Discord / (slash) command system which is better
bot = commands.Bot(command_prefix='!', intents=intents)

# 3. SET YOUR USER ID HERE!
BOT_OWNER_ID = 425766060008931338 
bot = commands.Bot(command_prefix='!', intents=intents, owner_id=BOT_OWNER_ID)

# --- Bot Events ---
@bot.command(name='sync')
@commands.is_owner()
async def sync(ctx):
    """Syncs the slash command tree to Discord (Owner only)."""
    # This ensures only the bot owner can run this command for safety
    if ctx.author.id == bot.owner_id:
        try:
            # Syncs all commands globally (can take up to an hour)
            # You can test with ctx.bot.tree.sync(guild=ctx.guild) for a quicker, server-only sync
            synced = await ctx.bot.tree.sync()
            await ctx.send(f"Synced {len(synced)} command(s) globally.")
        except Exception as e:
            await ctx.send(f"Sync failed: {e}")
    else:
        await ctx.send("You must be the bot owner to run this command.")


@bot.event
async def on_ready():
    """Confirms the bot is logged in and ready."""
    print(f'Bot is connected as {bot.user}')

# --- Custom Role Command ---
@bot.hybrid_command(name="noroles", description="Lists all members who only have the @everyone role.")
async def list_no_roles(ctx):
    await ctx.defer() 
    
    try:
        guild = ctx.guild
        
        if not guild.chunked:
            await guild.chunk() 
        
        if not guild.members:
            await ctx.send("Error: Could not retrieve server members. Check Server Members Intent.", ephemeral=True)
            return

        no_role_members = []
        for member in guild.members:
            # Condition check: NOT a bot AND only has 1 role (the @everyone role)
            if not member.bot and len(member.roles) == 1:
                # Using the mention here is better for action, but display_name is cleaner for a list
                no_role_members.append(member.mention) # Use mention so you can click on them!
        
        # --- NEW LOGIC STARTS HERE: Splitting the list ---
        
        total_count = len(no_role_members)

        if total_count == 0:
            await ctx.send("🎉 All members have been assigned at least one role!")
            return

        # Prepare the header message
        await ctx.send(f"**Found {total_count} Member(s) Without Roles. Sending list in chunks...**")

        current_message_content = ""
        # The list is split into chunks here
        for member_mention in no_role_members:
            # Check if adding the next member will exceed the 2000 character limit
            # We use 1900 to leave room for the header and formatting
            if len(current_message_content) + len(member_mention) + 1 >= 1900:
                # Send the current chunk
                await ctx.send(current_message_content)
                # Reset for the next chunk
                current_message_content = "" 
            
            # Add the member to the current message content
            current_message_content += member_mention + '\n'

        # Send any remaining content in the last chunk
        if current_message_content:
            await ctx.send(current_message_content)

    except Exception as e:
        print(f"FATAL ERROR in /noroles: {e}")
        await ctx.send(f"An unexpected error occurred: `{e}`. Check the bot's console for details.", ephemeral=True)

@bot.hybrid_command(name="assignunverified", description="Assigns the 'Unverified' role to all members who have no other roles.")
@commands.is_owner() # Ensures only you can run this powerful command
async def assign_unverified(ctx):
    await ctx.defer()
    
    try:
        guild = ctx.guild

        if not guild.chunked:
            await guild.chunk() 
        
        # 1. Find the 'Unverified' Role
        # Replace 'Unverified' with the exact name of your role if different
        unverified_role = discord.utils.get(guild.roles, name="Unverified")
        
        if not unverified_role:
            await ctx.send("Error: Could not find a role named 'Unverified'. Please create it or check the spelling.", ephemeral=True)
            return

        # 2. Identify Members to be Assigned
        target_members = []
        for member in guild.members:
            # Check if the member is NOT a bot AND only has 1 role (@everyone)
            if not member.bot and len(member.roles) == 1:
                target_members.append(member)
        
        total_count = len(target_members)

        if total_count == 0:
            await ctx.send("🎉 No members found without roles. Assignment complete (or unnecessary)!", ephemeral=True)
            return

        await ctx.send(f"**Starting assignment for {total_count} members...** This may take a moment.")

        # 3. Assign the Role
        assigned_count = 0
        failed_count = 0
        
        for member in target_members:
            try:
                # Add the role to the member
                await member.add_roles(unverified_role)
                assigned_count += 1
            except discord.Forbidden:
                # The bot's role hierarchy is lower than the Unverified role.
                print(f"ERROR: Bot lacks permissions to assign role to {member.name}")
                failed_count += 1
            except Exception as e:
                print(f"ERROR: Failed to assign role to {member.name}: {e}")
                failed_count += 1
            
            # Optional: Add a small delay for large operations to avoid rate limits
            # You can remove this if the operation is too slow
            # await asyncio.sleep(0.5) 
            
        # 4. Final Report
        final_message = f"**Role Assignment Complete!**\n"
        final_message += f"✅ Successfully assigned 'Unverified' to **{assigned_count}** members.\n"
        
        if failed_count > 0:
            final_message += f"❌ Failed to assign role to **{failed_count}** members (Check bot permissions/role hierarchy)."
        
        await ctx.send(final_message)
        
    except Exception as e:
        print(f"FATAL ERROR in /assignunverified: {e}")
        await ctx.send(f"An unexpected error occurred: `{e}`. Check the bot's console for details.", ephemeral=True)

# Run the bot with the token
if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: DISCORD_TOKEN not found in .env file.")