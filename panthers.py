import discord
import os
from discord.ext import commands
from dotenv import load_dotenv

# Load the token from the .env file
load_dotenv()
TOKEN = os.getenv('PANTHERS_TOKEN') or os.getenv('DISCORD_TOKEN')

# Bot Setup
intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix="!", intents=intents)
# List of negative keywords for Panthers fans
NEGATIVE_KEYWORDS = ["trash", "suck", "sucks", "bad", "garbage", "terrible", "worst", "lose", "loser"]

@bot.event
async def on_ready():
    print(f'Bot is online as {bot.user.name}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    msg_content = message.content.lower()

    # --- PANTHERS LOGIC ---
    if "panthers" in msg_content:
        is_negative = any(word in msg_content for word in NEGATIVE_KEYWORDS)
        if is_negative:
            await message.channel.send("Sir Purr will ban you permanently if you continue to talk about the Panthers like that")
        else:
            await message.channel.send("KEEP POUNDING")

    # --- RAMS LOGIC ---
    elif "rams" in msg_content:
        await message.channel.send("Go fuck yourself")

    elif "bryce young" in msg_content:
        is_negative = any(word in msg_content for word in NEGATIVE_KEYWORDS)
        if is_negative:
            await message.channel.send("Sir Purr will ban you permanently if you continue to talk about the Panthers like that")
        else:
            await message.channel.send("KEEP POUNDING")

    # --- EAGLES / GO BIRDS LOGIC ---
    elif "eagles" in msg_content or "go birds" in msg_content:
        await message.channel.send("Go birds")

    # --- WOLVERINES / MICHIGAN LOGIC ---
    elif "go uconn" in msg_content or "uconn" in msg_content:
        await message.channel.send("Fuck you go Wolverines!")
    elif "michigan sucks" in msg_content or "michigan stinks" in msg_content or "beat michigan" in msg_content or "fuck michigan" in msg_content:
        await message.channel.send("Fuck you go Wolverines!")

    await bot.process_commands(message)

bot.run(TOKEN)