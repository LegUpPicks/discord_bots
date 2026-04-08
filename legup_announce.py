# legup_announce.py — LegUp Announcement Emailer Bot
#
# Watches a single Discord channel. When a non-bot message is posted there,
# it calls the LegUp FastAPI /api/announce endpoint, which emails all active
# subscribers via Resend.
#
# Required env vars:
#   LEGUP_BOT_TOKEN          — Discord bot token (the LegUp bot)
#   LEGUP_ANNOUNCE_CHANNEL_ID — Discord channel ID to watch
#   LEGUP_APP_URL             — Base URL of the Vercel app (no trailing slash)
#   LEGUP_ADMIN_SECRET        — ADMIN_SECRET set in the Vercel app

import os
import asyncio
import httpx
import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN      = os.environ["LEGUP_BOT_TOKEN"]
CHANNEL_ID = int(os.environ["LEGUP_ANNOUNCE_CHANNEL_ID"])
APP_URL    = os.environ["LEGUP_APP_URL"].rstrip("/")
SECRET     = os.environ["LEGUP_ADMIN_SECRET"]

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


ANNOUNCE_AUTHOR = "dennythedonkey"
SUBJECT = "LegUp Plays"


@client.event
async def on_ready():
    print(f"LegUp announce bot ready as {client.user} — watching channel {CHANNEL_ID}")


@client.event
async def on_message(message: discord.Message):
    # Only act on the announcement channel, from the designated author
    if message.channel.id != CHANNEL_ID:
        return
    if message.author.name.lower() != ANNOUNCE_AUTHOR.lower():
        return

    subject = SUBJECT
    body    = message.content

    print(f"Announcement detected from {message.author}: {subject!r}")

    url = f"{APP_URL}/api/announce?secret={SECRET}"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(url, json={"subject": subject, "body": body})
            resp.raise_for_status()
            data = resp.json()
        print(f"Emails sent: {data.get('sent')} ok, {data.get('failed')} failed")
        await message.add_reaction("✅")
    except Exception as e:
        print(f"ERROR calling /api/announce: {e}")
        await message.add_reaction("❌")


client.run(TOKEN)
