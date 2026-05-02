# reaction_tracker.py — Reaction Tracker Bot
#
# Counts ✅ and ❌ reactions per user across all guild channels.
# Counts survive restarts via reaction_counts.json in the same directory.
#
# Required env vars:
#   REACTION_TOKEN   — Discord bot token (falls back to DISCORD_TOKEN)
#
# Slash commands (require Manage Messages or higher):
#   /reactionreport             — leaderboard of all tracked users
#   /reactionreport [member]    — stats for one member
#   /reactionbackfill           — backfill last 90 days from all channels (admin)
#   /reactionbackfill [channel] — backfill a single channel (admin)
#   /reactionreset [member]     — reset one member or everyone (admin)

import os
import json
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from pathlib import Path

load_dotenv()
TOKEN = os.getenv("REACTION_TOKEN") or os.getenv("DISCORD_TOKEN")
BOT_OWNER_ID = 425766060008931338

CHECK_EMOJI = "white_check_mark"  # ✅
X_EMOJI = "x"                     # ❌

# Unicode chars used when iterating message.reactions during backfill
EMOJI_CHAR_TO_NAME = {"✅": CHECK_EMOJI, "❌": X_EMOJI}

DATA_FILE = Path(__file__).parent / "reaction_counts.json"


def load_data() -> dict:
    if DATA_FILE.exists():
        with DATA_FILE.open() as f:
            return json.load(f)
    return {}


def save_data(data: dict) -> None:
    with DATA_FILE.open("w") as f:
        json.dump(data, f, indent=2)


counts: dict[str, dict] = load_data()


def update_count(user_id: int, username: str, emoji_name: str, delta: int, *, persist: bool = True) -> None:
    key = str(user_id)
    if key not in counts:
        counts[key] = {"check": 0, "x": 0, "username": username}
    counts[key]["username"] = username
    if emoji_name == CHECK_EMOJI:
        counts[key]["check"] = max(0, counts[key].get("check", 0) + delta)
    elif emoji_name == X_EMOJI:
        counts[key]["x"] = max(0, counts[key].get("x", 0) + delta)
    if persist:
        save_data(counts)


intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    owner_id=BOT_OWNER_ID,
)


@bot.event
async def on_ready():
    print(f"Reaction Tracker online as {bot.user}")
    await bot.tree.sync()
    print("Slash commands synced.")


def _resolve_username(payload: discord.RawReactionActionEvent) -> str:
    if payload.guild_id:
        guild = bot.get_guild(payload.guild_id)
        if guild:
            member = guild.get_member(payload.user_id)
            if member:
                return str(member)
    return str(payload.user_id)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id or not payload.guild_id:
        return
    if payload.emoji.name not in (CHECK_EMOJI, X_EMOJI):
        return
    update_count(payload.user_id, _resolve_username(payload), payload.emoji.name, +1)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id or not payload.guild_id:
        return
    if payload.emoji.name not in (CHECK_EMOJI, X_EMOJI):
        return
    update_count(payload.user_id, _resolve_username(payload), payload.emoji.name, -1)


@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx: commands.Context):
    synced = await bot.tree.sync()
    await ctx.send(f"Reaction Tracker: Synced {len(synced)} command(s).")


def x_ratio(checks: int, xs: int) -> float | None:
    """Returns X's as a fraction of total reactions, or None if no reactions."""
    total = checks + xs
    return xs / total if total > 0 else None


def fmt_ratio(checks: int, xs: int) -> str:
    r = x_ratio(checks, xs)
    return f"{r * 100:.0f}%" if r is not None else "—"


SORT_KEYS = {
    "total":   lambda d: d.get("check", 0) + d.get("x", 0),
    "checks":  lambda d: d.get("check", 0),
    "xs":      lambda d: d.get("x", 0),
    "x_ratio": lambda d: x_ratio(d.get("check", 0), d.get("x", 0)) or 0.0,
}

SORT_LABELS = {
    "total":   "Most Reactions",
    "checks":  "Most ✅ Checks",
    "xs":      "Most ❌ X's",
    "x_ratio": "Highest X Rate (min 5 reactions)",
}


@bot.tree.command(name="reactionreport", description="Show ✅ and ❌ reaction counts.")
@app_commands.describe(
    member="Optional: show stats for one member only",
    sort_by="How to sort the leaderboard (default: total)",
)
@app_commands.choices(sort_by=[app_commands.Choice(name=v, value=k) for k, v in SORT_LABELS.items()])
@app_commands.default_permissions(manage_messages=True)
async def reaction_report(
    interaction: discord.Interaction,
    member: discord.Member | None = None,
    sort_by: str = "total",
):
    if not counts:
        await interaction.response.send_message("No reaction data recorded yet.", ephemeral=True)
        return

    if member:
        entry = counts.get(str(member.id))
        if not entry:
            await interaction.response.send_message(
                f"No reaction data for {member.mention}.", ephemeral=True
            )
            return
        checks = entry.get("check", 0)
        xs = entry.get("x", 0)
        embed = discord.Embed(
            title=f"Reaction Stats — {member.display_name}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="✅ Checks", value=str(checks), inline=True)
        embed.add_field(name="❌ X's", value=str(xs), inline=True)
        embed.add_field(name="Total", value=str(checks + xs), inline=True)
        embed.add_field(name="X Rate", value=fmt_ratio(checks, xs), inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)
        return

    key_fn = SORT_KEYS.get(sort_by, SORT_KEYS["total"])
    entries = list(counts.items())

    # For x_ratio sort, require at least 5 reactions to filter noise
    if sort_by == "x_ratio":
        entries = [e for e in entries if e[1].get("check", 0) + e[1].get("x", 0) >= 5]

    sorted_entries = sorted(entries, key=lambda kv: key_fn(kv[1]), reverse=True)

    lines = []
    for i, (uid, data) in enumerate(sorted_entries[:25], 1):
        name = discord.utils.escape_markdown(data.get("username", uid))
        checks = data.get("check", 0)
        xs = data.get("x", 0)
        ratio = fmt_ratio(checks, xs)
        lines.append(f"`{i:>2}.` **{name}** — ✅ {checks}  ❌ {xs}  `{ratio} X`")

    total_checks = sum(v.get("check", 0) for v in counts.values())
    total_xs = sum(v.get("x", 0) for v in counts.values())

    embed = discord.Embed(
        title=f"Reaction Leaderboard — {SORT_LABELS.get(sort_by, 'Most Reactions')}",
        description="\n".join(lines) if lines else "No data meets the filter criteria.",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(
        text=f"All-time — ✅ {total_checks}  ❌ {total_xs}  •  {len(counts)} users tracked"
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="reactionbackfill",
    description="Backfill ✅ and ❌ counts from the last 90 days of message history.",
)
@app_commands.describe(
    channel="Channel to scan (leave blank to scan all channels)",
    reset_first="Clear existing counts before backfilling (default: True)",
)
@app_commands.default_permissions(administrator=True)
async def reaction_backfill(
    interaction: discord.Interaction,
    channel: discord.TextChannel | None = None,
    reset_first: bool = True,
):
    await interaction.response.defer(ephemeral=True)

    global counts
    if reset_first:
        counts = {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    channels_to_scan = [channel] if channel else interaction.guild.text_channels

    total_messages = 0
    total_reactions = 0
    skipped_channels = 0

    for ch in channels_to_scan:
        try:
            async for message in ch.history(after=cutoff, limit=None, oldest_first=True):
                total_messages += 1
                for reaction in message.reactions:
                    emoji_name = EMOJI_CHAR_TO_NAME.get(str(reaction.emoji))
                    if not emoji_name:
                        continue
                    async for user in reaction.users():
                        if user.bot:
                            continue
                        update_count(user.id, str(user), emoji_name, +1, persist=False)
                        total_reactions += 1
        except discord.Forbidden:
            skipped_channels += 1

    save_data(counts)

    channel_word = "channel" if channel else f"{len(channels_to_scan)} channel(s)"
    summary = (
        f"Backfill complete.\n"
        f"• Scanned **{total_messages:,}** messages across {channel_word}\n"
        f"• Found **{total_reactions:,}** relevant reactions\n"
        f"• Tracking **{len(counts)}** users"
    )
    if skipped_channels:
        summary += f"\n• Skipped **{skipped_channels}** channel(s) (no read permission)"

    await interaction.followup.send(summary, ephemeral=True)


@bot.tree.command(name="reactionreset", description="Reset reaction counts for a member or all members.")
@app_commands.describe(member="Member to reset (omit to reset everyone)")
@app_commands.default_permissions(administrator=True)
async def reaction_reset(interaction: discord.Interaction, member: discord.Member | None = None):
    global counts
    if member:
        key = str(member.id)
        if key in counts:
            del counts[key]
            save_data(counts)
            await interaction.response.send_message(
                f"Reset counts for {member.mention}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"No data found for {member.mention}.", ephemeral=True
            )
    else:
        counts = {}
        save_data(counts)
        await interaction.response.send_message("All reaction counts have been reset.", ephemeral=True)


if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: REACTION_TOKEN (or DISCORD_TOKEN) not found in .env file.")
