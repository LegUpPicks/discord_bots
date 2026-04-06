# purrcurity.py — PurrCurity Discord Spam Moderation Bot

import os
import re
import csv
import io
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta, time
from zoneinfo import ZoneInfo

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

URL_PATTERN = re.compile(
    r'https?://\S+|www\.\S+',
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

EMOJI_PATTERN = re.compile(
    u'[\U0001F300-\U0001FFFF]|[\u2600-\u27BF]',
    re.UNICODE
)

# ─── Configuration ────────────────────────────────────────────────────────────

# Role names (case-insensitive) that are EXEMPT from all filters
EXEMPT_ROLE_NAMES: set[str] = {"admin", "administrator", "moderator", "mod", "staff", "owner", "verified member"}

# Role name that gets stricter filtering (all links blocked, not just invite links)
SOCIAL_ROLE_NAME = "social"

# Channel name to post mod logs (matched case-insensitively)
MOD_LOG_CHANNEL_NAME = "security-management"

# Toggle individual filters on/off at runtime via /purrfilter
FILTERS: dict[str, bool] = {
    "discord_links":      True,   # Block Discord invite links (all members)
    "telegram_links":     True,   # Block Telegram links (all members)
    "promo_phrases":      True,   # Block betting promo/spam phrases (all members)
    "spam_mentions":      True,   # Block mass @mentions (all members)
    "caps_spam":          True,   # Block excessive ALL CAPS (all members)
    "repeated_chars":     True,   # Block aaaaaaa / !!!!! spam (all members)
    "all_links_social":   True,   # Block ALL URLs for Social role members
    "emoji_spam":         True,   # Block excessive emojis (all members)
    "strike_system":      True,   # Auto-timeout after MAX_STRIKES violations
}

# Thresholds
CAPS_THRESHOLD = 0.70
CAPS_MIN_LENGTH = 10
MAX_MENTIONS = 4
REPEATED_CHAR_MIN = 6
EMOJI_MAX = 8
NEW_ACCOUNT_DAYS = 7    # Accounts newer than this are flagged in logs
MAX_STRIKES = 3         # Violations before auto-timeout
TIMEOUT_MINUTES = 60    # How long the auto-timeout lasts

# ─── Scan Configuration ───────────────────────────────────────────────────────

ET = ZoneInfo("America/New_York")

# Times to auto-post the Social member scan report (Eastern Time)
SCAN_TIMES = [
    time(hour=8, minute=0, tzinfo=ET),
]

# Suspicious indicator thresholds for /purrscan
SCAN_ACCOUNT_AGE_DAYS = 14   # Flag accounts newer than this
SCAN_JOIN_AGE_DAYS    = 7    # Flag members who joined the server within this many days
SCAN_SUSPICIOUS_KEYWORDS = {
    "picks", "capper", "cappers", "tips", "tipster", "free", "crypto",
    "nft", "invest", "profit", "winner", "money", "cash", "promo",
}

# Impersonation patterns — matches variations of the server owner's name
IMPERSONATION_PATTERN = re.compile(
    r'romano|chee+z(up)?|chee+zup',
    re.IGNORECASE
)

# ─── Strike Tracking (in-memory, resets on bot restart) ───────────────────────
strikes: dict[int, int] = {}

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
    if member.guild_permissions.administrator:
        return True
    member_role_names = {r.name.lower() for r in member.roles}
    return bool(member_role_names & {r.lower() for r in EXEMPT_ROLE_NAMES})


def has_social_role(member: discord.Member) -> bool:
    return any(r.name.lower() == SOCIAL_ROLE_NAME.lower() for r in member.roles)


def check_message(content: str, member: discord.Member | None = None) -> list[str]:
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

    if FILTERS["emoji_spam"]:
        emoji_count = len(EMOJI_PATTERN.findall(content))
        if emoji_count > EMOJI_MAX:
            violations.append(f"emoji spam ({emoji_count} emojis)")

    # Stricter: block ALL links for Social role members
    if (
        FILTERS["all_links_social"]
        and member is not None
        and has_social_role(member)
        and URL_PATTERN.search(content)
        and not violations  # Only add if not already caught by a stricter rule
    ):
        violations.append("links are not permitted for Social members")

    return violations


def get_mod_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if channel.name.lower() == MOD_LOG_CHANNEL_NAME.lower():
            return channel
    return None


async def post_mod_log(
    guild: discord.Guild,
    member: discord.Member,
    channel: discord.TextChannel,
    content: str,
    reasons: list[str],
    timed_out: bool = False,
) -> None:
    log_channel = get_mod_log_channel(guild)
    if not log_channel:
        return

    account_age = (datetime.now(timezone.utc) - member.created_at).days
    is_new_account = account_age < NEW_ACCOUNT_DAYS
    strike_count = strikes.get(member.id, 0)

    embed = discord.Embed(
        title="PurrCurity — Message Removed" + (" 🔇 Member Timed Out" if timed_out else ""),
        color=discord.Color.red() if timed_out else discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="User", value=f"{member.mention} (`{member}`)", inline=True)
    embed.add_field(name="Channel", value=channel.mention, inline=True)
    embed.add_field(name="Strikes", value=f"{strike_count}/{MAX_STRIKES}", inline=True)
    embed.add_field(
        name="Violations",
        value="\n".join(f"• {r}" for r in reasons),
        inline=False,
    )
    preview = content[:300] + ("…" if len(content) > 300 else "")
    embed.add_field(
        name="Message Preview",
        value=f"```{discord.utils.escape_markdown(preview)}```",
        inline=False,
    )
    if is_new_account:
        embed.add_field(name="⚠️ New Account", value=f"Account is only {account_age} day(s) old", inline=False)
    if timed_out:
        embed.add_field(name="Action", value=f"Timed out for {TIMEOUT_MINUTES} minutes after {MAX_STRIKES} violations", inline=False)
    embed.set_footer(text=f"User ID: {member.id}")
    await log_channel.send(embed=embed)

# ─── Scan Logic ───────────────────────────────────────────────────────────────

def get_suspicion_flags(member: discord.Member) -> list[str]:
    """Returns a list of suspicious indicators for a Social role member."""
    flags = []
    now = datetime.now(timezone.utc)

    account_age = (now - member.created_at).days
    if account_age < SCAN_ACCOUNT_AGE_DAYS:
        flags.append(f"🆕 New account ({account_age}d old)")

    if member.joined_at:
        join_age = (now - member.joined_at).days
        if join_age < SCAN_JOIN_AGE_DAYS:
            flags.append(f"🚪 Joined recently ({join_age}d ago)")

    name_lower = member.name.lower()
    matched_kw = [kw for kw in SCAN_SUSPICIOUS_KEYWORDS if kw in name_lower]
    if matched_kw:
        flags.append(f"🔤 Suspicious username keywords: {', '.join(matched_kw)}")

    full_name = f"{member.name} {member.display_name}"
    if IMPERSONATION_PATTERN.search(full_name):
        flags.append(f"🚨 Possible impersonation (name resembles server owner)")

    return flags


KICK_DM_MESSAGE = (
    "Your account does not meet the criteria to join this server either for suspicious activity or account age. "
    "Please try to join once your discord account is of a more mature status, as always you can join premium "
    "where there are no restrictions via Whop: https://whop.com/c/leguppicks/discord"
)


async def run_scan(guild: discord.Guild, triggered_by: str = "Scheduled", kick: bool = False) -> None:
    """Scans all Social role members and posts a report to #security-management."""
    log_channel = get_mod_log_channel(guild)
    if not log_channel:
        return

    if not guild.chunked:
        await guild.chunk()

    social_role = discord.utils.find(lambda r: r.name.lower() == SOCIAL_ROLE_NAME.lower(), guild.roles)
    if not social_role:
        await log_channel.send(f"⚠️ PurrCurity scan: Could not find a role named `{SOCIAL_ROLE_NAME}`.")
        return

    verified_role = discord.utils.find(lambda r: r.name.lower() == "verified member", guild.roles)
    social_members = [
        m for m in guild.members
        if social_role in m.roles
        and not m.bot
        and (verified_role is None or verified_role not in m.roles)
    ]
    suspicious = [(m, get_suspicion_flags(m)) for m in social_members]
    suspicious = [
        (m, flags) for m, flags in suspicious
        if (
            (any("New account" in f for f in flags) and any("Joined recently" in f for f in flags))
            or any("impersonation" in f for f in flags)
        )
    ]

    now_et = datetime.now(ET).strftime("%b %d, %Y %I:%M %p ET")

    header = discord.Embed(
        title=f"PurrCurity — Social Member Scan 🐾",
        description=(
            f"**Triggered by:** {triggered_by}\n"
            f"**Time:** {now_et}\n\n"
            f"**Total Social members:** {len(social_members)}\n"
            f"**Flagged as suspicious:** {len(suspicious)}"
        ),
        color=discord.Color.yellow() if suspicious else discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    await log_channel.send(embed=header)

    if not suspicious:
        await log_channel.send("✅ No suspicious Social members found.")
        return

    # Build CSV in memory
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Username", "Display Name", "User ID", "Account Created", "Joined Server", "Flags"])
    for member, flags in suspicious:
        writer.writerow([
            str(member),
            member.display_name,
            member.id,
            member.created_at.strftime("%Y-%m-%d"),
            member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "Unknown",
            " | ".join(flags),
        ])

    buf.seek(0)
    filename = f"purrcurity_scan_{datetime.now(ET).strftime('%Y%m%d_%H%M')}.csv"
    csv_file = discord.File(fp=io.BytesIO(buf.getvalue().encode()), filename=filename)
    await log_channel.send(f"📎 **{len(suspicious)} flagged member(s)** — full report attached:", file=csv_file)

    if kick:
        kicked, failed = 0, 0
        for member, _ in suspicious:
            try:
                await member.send(KICK_DM_MESSAGE)
            except (discord.Forbidden, discord.HTTPException):
                pass  # DMs disabled — still kick
            try:
                await member.kick(reason="PurrCurity: suspicious activity or account age")
                kicked += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
        summary = f"✅ Kicked **{kicked}** member(s)."
        if failed:
            summary += f" ❌ Failed to kick **{failed}** (check bot role hierarchy)."
        await log_channel.send(summary)


# ─── Scheduled Scan Task ──────────────────────────────────────────────────────

@tasks.loop(time=SCAN_TIMES)
async def scheduled_scan():
    for guild in bot.guilds:
        await run_scan(guild, triggered_by="Scheduled auto-scan")


# ─── Events ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"PurrCurity is online as {bot.user} 🐾")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="for spam 🐾")
    )
    if not scheduled_scan.is_running():
        scheduled_scan.start()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not isinstance(message.author, discord.Member):
        return

    if is_exempt(message.author):
        await bot.process_commands(message)
        return

    violations = check_message(message.content, message.author)

    if violations:
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        # Update strike count
        timed_out = False
        if FILTERS["strike_system"]:
            strikes[message.author.id] = strikes.get(message.author.id, 0) + 1
            current_strikes = strikes[message.author.id]

            if current_strikes >= MAX_STRIKES:
                try:
                    await message.author.timeout(
                        timedelta(minutes=TIMEOUT_MINUTES),
                        reason=f"PurrCurity: {MAX_STRIKES} violations"
                    )
                    timed_out = True
                    strikes[message.author.id] = 0  # Reset after timeout
                except discord.Forbidden:
                    pass

        reason_str = ", ".join(violations)
        warning = (
            f"{message.author.mention} You have been timed out for {TIMEOUT_MINUTES} minutes after repeated violations. 🐾"
            if timed_out else
            f"{message.author.mention} Your message was removed by PurrCurity for: **{reason_str}**. "
            f"({strikes.get(message.author.id, 0)}/{MAX_STRIKES} strikes) 🐾"
        )
        try:
            await message.channel.send(warning, delete_after=12)
        except discord.Forbidden:
            pass

        await post_mod_log(message.guild, message.author, message.channel, message.content, violations, timed_out)
        return

    await bot.process_commands(message)

# ─── Owner Command: Sync Slash Commands ───────────────────────────────────────

@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx: commands.Context):
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
    log_channel = get_mod_log_channel(interaction.guild)
    log_val = log_channel.mention if log_channel else f"*#{MOD_LOG_CHANNEL_NAME} not found*"
    exempt_val = ", ".join(f"`{r}`" for r in sorted(EXEMPT_ROLE_NAMES))

    embed = discord.Embed(
        title="PurrCurity — Filter Status 🐾",
        description="\n".join(lines),
        color=discord.Color.purple(),
    )
    embed.add_field(name="Mod Log Channel", value=log_val, inline=False)
    embed.add_field(name="Exempt Roles", value=exempt_val, inline=False)
    embed.add_field(name="Social Role (strict)", value=f"`{SOCIAL_ROLE_NAME}`", inline=True)
    embed.add_field(name="Strike Limit", value=f"`{MAX_STRIKES}` → {TIMEOUT_MINUTES}min timeout", inline=True)
    embed.set_footer(text="Use /purrfilter to toggle filters")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="purrfilter", description="Enable or disable a PurrCurity filter.")
@app_commands.describe(filter_name="Which filter to change", enabled="True to enable, False to disable")
@app_commands.choices(filter_name=[app_commands.Choice(name=k, value=k) for k in FILTERS])
@app_commands.default_permissions(administrator=True)
async def purrfilter(interaction: discord.Interaction, filter_name: str, enabled: bool):
    if filter_name not in FILTERS:
        await interaction.response.send_message(f"Unknown filter: `{filter_name}`", ephemeral=True)
        return
    FILTERS[filter_name] = enabled
    state = "**enabled** ✅" if enabled else "**disabled** ❌"
    await interaction.response.send_message(
        f"PurrCurity: `{filter_name}` is now {state}. 🐾", ephemeral=True
    )


@bot.tree.command(name="purrcheck", description="Test whether a message would be caught by PurrCurity.")
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


@bot.tree.command(name="purrstrikes", description="Check how many strikes a member has.")
@app_commands.describe(member="The member to check")
@app_commands.default_permissions(manage_messages=True)
async def purrstrikes(interaction: discord.Interaction, member: discord.Member):
    count = strikes.get(member.id, 0)
    await interaction.response.send_message(
        f"{member.mention} has **{count}/{MAX_STRIKES}** strikes. 🐾", ephemeral=True
    )


@bot.tree.command(name="purrclearstrikes", description="Clear all strikes for a member.")
@app_commands.describe(member="The member to clear strikes for")
@app_commands.default_permissions(administrator=True)
async def purrclearstrikes(interaction: discord.Interaction, member: discord.Member):
    strikes.pop(member.id, None)
    await interaction.response.send_message(
        f"PurrCurity: Strikes cleared for {member.mention}. 🐾", ephemeral=True
    )

@bot.tree.command(name="purrscan", description="Scan Social role members for suspicious activity and post report to security-management.")
@app_commands.describe(kick="Kick all flagged members after generating the report (default: False)")
@app_commands.default_permissions(administrator=True)
async def purrscan(interaction: discord.Interaction, kick: bool = False):
    action = "Scanning and kicking" if kick else "Scanning"
    await interaction.response.send_message(f"PurrCurity: {action} Social members... report will appear in #security-management. 🐾", ephemeral=True)
    await run_scan(interaction.guild, triggered_by=f"Manual scan by {interaction.user}", kick=kick)

# ─── Run ──────────────────────────────────────────────────────────────────────

if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: PURRCURITY_TOKEN (or DISCORD_TOKEN) not found in .env file.")
