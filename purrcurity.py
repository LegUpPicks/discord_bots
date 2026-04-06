# purrcurity.py — PurrCurity Discord Spam Moderation Bot

import os
import re
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()
TOKEN = os.getenv('PURRCURITY_TOKEN') or os.getenv('DISCORD_TOKEN')
BOT_OWNER_ID = 425766060008931338

# ─── Spam Detection Patterns ──────────────────────────────────────────────────

DISCORD_INVITE_PATTERN = re.compile(
    r'(discord\.gg/|discord\.com/invite/|discordapp\.com/invite/)\S+',
    re.IGNORECASE
)

TELEGRAM_PATTERN = re.compile(
    r'(t\.me/|telegram\.me/|telegram\.org|@\w{3,}\s*(on|via|at)?\s*telegram)',
    re.IGNORECASE
)

# Common spam/promo patterns in sports betting communities
_PROMO_PHRASES = [
    r'\bdm\s*(me\s*)?(for|my)\s*(free\s*)?(picks?|tips?|plays?|locks?)\b',
    r'\bfree\s*(picks?|tips?|plays?|locks?)\b',
    r'\bguaranteed\s*(wins?|profits?|returns?|money)\b',
    r'\bjoin\s*my\s*(telegram|discord|server|channel|group)\b',
    r'\b(100|99|95)%\s*(guaranteed|win\s*rate|accuracy)\b',
    r'\bsell(ing)?\s*(picks?|tips?|plays?)\b',
    r'\b(buy|purchase)\s*(picks?|tips?|plays?)\b',
    r'\bpremium\s*(picks?|tips?|plays?|channel|group)\b',
    r'\bcapper\s*(group|channel|discord|telegram|server)\b',
    r'\bfollow\s*me\s*(for|on)\s*(free\s*)?(picks?|tips?)\b',
    r'\bcheck\s*(my|out\s*my)\s*(bio|profile|channel|telegram|discord)\b',
    r'\bi\s*(went|went\s*)\d+-\d+\s*(last\s*)?(week|month|season)\b',
]

PROMO_PATTERN = re.compile('|'.join(_PROMO_PHRASES), re.IGNORECASE)

# ─── Configuration (edit these to customize) ──────────────────────────────────

# Role names (case-insensitive) that are EXEMPT from all filters
EXEMPT_ROLE_NAMES: set[str] = {"admin", "administrator", "moderator", "mod", "staff", "owner"}

# Set to a channel ID integer to enable mod logging, or None to disable
MOD_LOG_CHANNEL_ID: int | None = None

# Toggle individual filters on/off at runtime via /purrfilter
FILTERS: dict[str, bool] = {
    "discord_links":  True,   # Block Discord invite links
    "telegram_links": True,   # Block Telegram links / @user on telegram
    "promo_phrases":  True,   # Block betting promo/spam phrases
    "spam_mentions":  True,   # Block mass @mentions
    "caps_spam":      True,   # Block excessive ALL CAPS
    "repeated_chars": True,   # Block aaaaaaaa / !!!!!!!!! type spam
}

# Thresholds
CAPS_THRESHOLD = 0.70          # 70%+ of letters are caps → flagged
CAPS_MIN_LENGTH = 10           # Only check messages with ≥ this many characters
MAX_MENTIONS = 4               # More than this many @mentions → flagged
REPEATED_CHAR_MIN = 6          # N+ consecutive identical characters → flagged

# ─── Bot Setup ────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    owner_id=BOT_OWNER_ID,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def is_exempt(member: discord.Member) -> bool:
    """Returns True if the member bypasses all filters."""
    if member.guild_permissions.administrator:
        return True
    member_role_names = {r.name.lower() for r in member.roles}
    return bool(member_role_names & EXEMPT_ROLE_NAMES)


def check_message(content: str) -> list[str]:
    """Returns a list of human-readable violation reasons for the message content."""
    violations: list[str] = []

    if FILTERS["discord_links"] and DISCORD_INVITE_PATTERN.search(content):
        violations.append("Discord invite link")

    if FILTERS["telegram_links"] and TELEGRAM_PATTERN.search(content):
        violations.append("Telegram link/reference")

    if FILTERS["promo_phrases"] and PROMO_PATTERN.search(content):
        violations.append("promotional/spam content")

    if FILTERS["spam_mentions"]:
        mention_count = len(re.findall(r'<@!?\d+>|@everyone|@here', content))
        if mention_count > MAX_MENTIONS:
            violations.append(f"mass mentions ({mention_count})")

    if FILTERS["caps_spam"] and len(content) >= CAPS_MIN_LENGTH:
        letters = [c for c in content if c.isalpha()]
        if letters:
            caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if caps_ratio >= CAPS_THRESHOLD:
                violations.append(f"excessive caps ({int(caps_ratio * 100)}%)")

    if FILTERS["repeated_chars"] and re.search(
        r'(.)\1{' + str(REPEATED_CHAR_MIN - 1) + r',}', content
    ):
        violations.append("repeated character spam")

    return violations


async def post_mod_log(
    guild: discord.Guild,
    member: discord.Member,
    channel: discord.TextChannel,
    content: str,
    reasons: list[str],
) -> None:
    """Posts a violation embed to the mod log channel if configured."""
    if MOD_LOG_CHANNEL_ID is None:
        return
    log_channel = guild.get_channel(MOD_LOG_CHANNEL_ID)
    if not isinstance(log_channel, discord.TextChannel):
        return

    embed = discord.Embed(
        title="PurrCurity — Message Removed",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="User", value=f"{member.mention} (`{member}`)", inline=True)
    embed.add_field(name="Channel", value=channel.mention, inline=True)
    embed.add_field(
        name="Violations",
        value="\n".join(f"• {r}" for r in reasons),
        inline=False,
    )
    # Truncate content preview to 300 chars to avoid embed limits
    preview = content[:300] + ("…" if len(content) > 300 else "")
    embed.add_field(name="Message Preview", value=f"```{discord.utils.escape_markdown(preview)}```", inline=False)
    embed.set_footer(text=f"User ID: {member.id}")
    await log_channel.send(embed=embed)

# ─── Events ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"PurrCurity is online as {bot.user} 🐾")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="for spam 🐾")
    )


@bot.event
async def on_message(message: discord.Message):
    # Ignore DMs and other bots
    if message.author.bot or not isinstance(message.author, discord.Member):
        return

    # Exempt roles/admins pass through
    if is_exempt(message.author):
        await bot.process_commands(message)
        return

    violations = check_message(message.content)

    if violations:
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        reason_str = ", ".join(violations)
        try:
            await message.channel.send(
                f"{message.author.mention} Your message was removed by PurrCurity for: "
                f"**{reason_str}**. Please keep the server spam-free! 🐾",
                delete_after=12,
            )
        except discord.Forbidden:
            pass

        await post_mod_log(message.guild, message.author, message.channel, message.content, violations)
        return  # Don't process commands on deleted spam messages

    await bot.process_commands(message)

# ─── Owner Command: Sync Slash Commands ───────────────────────────────────────

@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx: commands.Context):
    """Syncs slash commands to Discord (owner only). Run once after adding new commands."""
    synced = await bot.tree.sync()
    await ctx.send(f"PurrCurity: Synced {len(synced)} command(s). 🐾")

# ─── Slash Commands ───────────────────────────────────────────────────────────

@bot.tree.command(name="purrstatus", description="Show PurrCurity's current filter settings.")
@app_commands.default_permissions(manage_messages=True)
async def purrstatus(interaction: discord.Interaction):
    lines = [
        f"{'✅' if enabled else '❌'}  `{name}`"
        for name, enabled in FILTERS.items()
    ]
    mod_log_val = f"<#{MOD_LOG_CHANNEL_ID}>" if MOD_LOG_CHANNEL_ID else "*Not configured*"
    exempt_val = ", ".join(f"`{r}`" for r in sorted(EXEMPT_ROLE_NAMES))

    embed = discord.Embed(
        title="PurrCurity — Filter Status 🐾",
        description="\n".join(lines),
        color=discord.Color.purple(),
    )
    embed.add_field(name="Mod Log Channel", value=mod_log_val, inline=False)
    embed.add_field(name="Exempt Role Names", value=exempt_val, inline=False)
    embed.set_footer(text="Use /purrfilter to toggle filters • /purrlog to set mod log channel")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="purrfilter", description="Enable or disable a PurrCurity filter.")
@app_commands.describe(
    filter_name="Which filter to change",
    enabled="True to enable, False to disable",
)
@app_commands.choices(filter_name=[app_commands.Choice(name=k, value=k) for k in FILTERS])
@app_commands.default_permissions(administrator=True)
async def purrfilter(interaction: discord.Interaction, filter_name: str, enabled: bool):
    if filter_name not in FILTERS:
        await interaction.response.send_message(f"Unknown filter: `{filter_name}`", ephemeral=True)
        return
    FILTERS[filter_name] = enabled
    state = "**enabled** ✅" if enabled else "**disabled** ❌"
    await interaction.response.send_message(
        f"PurrCurity: `{filter_name}` is now {state}. 🐾",
        ephemeral=True,
    )


@bot.tree.command(name="purrlog", description="Set or clear the PurrCurity mod log channel.")
@app_commands.describe(channel="Channel to send mod logs to (leave blank to disable)")
@app_commands.default_permissions(administrator=True)
async def purrlog(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    global MOD_LOG_CHANNEL_ID
    if channel is None:
        MOD_LOG_CHANNEL_ID = None
        await interaction.response.send_message(
            "PurrCurity: Mod logging has been **disabled**. 🐾", ephemeral=True
        )
    else:
        MOD_LOG_CHANNEL_ID = channel.id
        await interaction.response.send_message(
            f"PurrCurity: Mod logs will be sent to {channel.mention}. 🐾", ephemeral=True
        )


@bot.tree.command(name="purrcheck", description="Manually test whether a message would be caught by PurrCurity.")
@app_commands.describe(text="The message text to check")
@app_commands.default_permissions(manage_messages=True)
async def purrcheck(interaction: discord.Interaction, text: str):
    violations = check_message(text)
    if violations:
        reasons = "\n".join(f"• {v}" for v in violations)
        await interaction.response.send_message(
            f"🚨 This message **would be removed** for:\n{reasons}", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "✅ This message **passes** all active filters.", ephemeral=True
        )

# ─── Run ──────────────────────────────────────────────────────────────────────

if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: PURRCURITY_TOKEN (or DISCORD_TOKEN) not found in .env file.")
