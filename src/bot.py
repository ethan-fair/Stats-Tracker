"""
Discord Stats Bot
=================
Command: /stats
Flow:
  1. User enters their username → validated against ALLOWED_USERS
  2. User picks a report type: All Time | Single Date | Date Range
  3. User selects dates via dropdown menus (where applicable)
  4. Bot generates and sends a PDF report

Requirements:
  pip install discord.py reportlab

Setup:
  1. Create a Discord application at https://discord.com/developers/applications
  2. Add a Bot, copy the token, paste it into BOT_TOKEN below
  3. Under OAuth2 → URL Generator, enable `bot` + `applications.commands` scopes
  4. Invite the bot to your server with that URL
  5. Run:  python stats_bot.py
"""

import discord
from discord import app_commands
from discord.ui import View, Select, Modal, TextInput
import io
import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import sqlite3
import pdf
import json
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ──────────────────────────────────────────────────────────────
# CONFIGURATION  ← edit these
# ──────────────────────────────────────────────────────────────

BOT_TOKEN = "MTQ5MzcyMTA0MDc5MzIzOTc5Mw.GKSaxc.8AgRAvIaoQD-nGWi4zwPeKM-Eit1Me7uuUjjo4"

def get_dates():
    conn = sqlite3.connect("players.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM games")
        result = cursor.fetchall()
    except:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS games (
                date TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        conn.commit()

        cursor.execute("SELECT * FROM games")
        result = cursor.fetchall()

    rows = [dict(row) for row in result]
    cursor.close()
    data = []
    for row in rows:
        data.append(row["date"])
    conn.commit()
    conn.close()
    return data

def get_usernames():
    conn = sqlite3.connect("players.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM players")
    usernames = [row[0] for row in cursor.fetchall()]
    conn.close()
    return usernames

def get_names():
    conn = sqlite3.connect("players.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM players")
    usernames = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT first_name FROM players")
    first_names = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT last_name FROM players")
    last_names = [row[0] for row in cursor.fetchall()]
    conn.close()
    name_list = {}
    for i in range(len(usernames)):
        name_list[usernames[i]] = first_names[i] + " " + last_names[i]
    return name_list

# ──────────────────────────────────────────────────────────────
# DATE PARSING HELPER
# ──────────────────────────────────────────────────────────────

def parse_date(text: str) -> datetime.date:
    """
    Parse a date string in MM-DD-YYYY format.
    Raises ValueError with a user-friendly message on failure.
    """
    text = text.strip()
    try:
        return datetime.datetime.strptime(text, "%m-%d-%Y").date()
    except ValueError:
        raise ValueError(
            f"**{text}** is not a valid date. "
            "Please use the format `MM-DD-YYYY` (e.g. `04-25-2024`)."
        )


# ──────────────────────────────────────────────────────────────
# PDF GENERATION
# ──────────────────────────────────────────────────────────────

def generate_pdf(username: str, report_type: str, date_info: str) -> io.BytesIO:
    """
    Build and return a PDF as an in-memory byte stream.

    ┌─────────────────────────────────────────────────────┐
    │  ADD YOUR CUSTOM REPORT-BUILDING CODE IN THIS       │
    │  FUNCTION. Replace the placeholder paragraphs with  │
    │  your actual data, charts, tables, etc.             │
    └─────────────────────────────────────────────────────┘
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # ── Title ──────────────────────────────────────────────────
    story.append(Paragraph(f"Stats Report for {username}", styles["Title"]))
    story.append(Spacer(1, 12))

    # ── Report metadata ────────────────────────────────────────
    story.append(Paragraph(f"<b>Report Type:</b> {report_type}", styles["Normal"]))
    story.append(Paragraph(f"<b>Period:</b> {date_info}", styles["Normal"]))
    story.append(Paragraph(
        f"<b>Generated:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 24))

    # ══════════════════════════════════════════════════════════
    #  YOUR CODE GOES HERE
    #  Use the `story` list to add content:
    #    story.append(Paragraph("Your text", styles["Normal"]))
    #    story.append(Table([["Col1", "Col2"], [1, 2]]))
    #    story.append(Image("chart.png", width=400, height=200))
    # ══════════════════════════════════════════════════════════
    story.append(Paragraph(
        "[ Placeholder — insert your report content here ]",
        styles["Normal"],
    ))
    # ══════════════════════════════════════════════════════════

    doc.build(story)
    buffer.seek(0)
    return buffer


# ──────────────────────────────────────────────────────────────
# VIEWS  (multi-step interaction)
# ──────────────────────────────────────────────────────────────


# ── Step 3a: Single Date Modal ────────────────────────────────

class SingleDateModal(Modal, title="Enter Date"):
    date_input: TextInput = TextInput(
        label="Date (MM-DD-YYYY)",
        placeholder="e.g. 04-25-2024",
        required=True,
        min_length=10,
        max_length=10,
    )

    def __init__(self, username: str):
        super().__init__()
        self.username = username

    async def on_submit(self, interaction: discord.Interaction):
        try:
            selected_date = parse_date(self.date_input.value)
        except ValueError as e:
            await interaction.response.send_message(f"{e}", ephemeral=True)
            return

        date_info = selected_date.strftime("%B %d, %Y")

        dates_to_use = []
        for date in get_dates():
            date_obj = datetime.datetime.strptime(date, "%b %d, %Y, %I:%M:%S.%f %p").date()
            if date_obj == selected_date:
                dates_to_use.append(date)

        if dates_to_use != []:
            pdf_buffer = pdf.generate_player_report(self.username, dates_to_use)

            await interaction.response.send_message(
                f"Here is your **Single Date** report ({date_info}), {get_names()[self.username]}!",
                file=discord.File(pdf_buffer, filename=self.username + ".pdf"),
                ephemeral=True,
            )
        
        else:
            await interaction.response.send_message(
                f"There were no games on this date.",
                ephemeral=True,
            )


# ── Step 3b: Date Range Modal ─────────────────────────────────

class DateRangeModal(Modal, title="Enter Date Range"):
    start_input: TextInput = TextInput(
        label="Start Date",
        placeholder="MM-DD-YYYY",
        required=True,
        min_length=10,
        max_length=10,
    )
    end_input: TextInput = TextInput(
        label="End Date",
        placeholder="MM-DD-YYYY",
        required=True,
        min_length=10,
        max_length=10,
    )

    def __init__(self, username: str):
        super().__init__()
        self.username = username

    async def on_submit(self, interaction: discord.Interaction):
        try:
            start_date = parse_date(self.start_input.value)
        except ValueError as e:
            await interaction.response.send_message(
                f"Start date — {e}", ephemeral=True
            )
            return

        try:
            end_date = parse_date(self.end_input.value)
        except ValueError as e:
            await interaction.response.send_message(
                f"End date — {e}", ephemeral=True
            )
            return

        if end_date < start_date:
            await interaction.response.send_message(
                "End date must be on or after the start date.", ephemeral=True
            )
            return

        date_info = (
            f"{start_date.strftime('%B %d, %Y')} → {end_date.strftime('%B %d, %Y')}"
        )

        dates_to_use = []
        for date in get_dates():
            date_obj = datetime.datetime.strptime(date, "%b %d, %Y, %I:%M:%S.%f %p").date()
            if date_obj >= start_date and date_obj <= end_date:
                dates_to_use.append(date)

        if dates_to_use != []:
            pdf_buffer = pdf.generate_player_report(self.username, dates_to_use)

            await interaction.response.send_message(
                f"Here is your **Date Range** report ({date_info}), {get_names()[self.username]}!",
                file=discord.File(pdf_buffer, filename=self.username + ".pdf"),
                ephemeral=True,
            )
        
        else:
            await interaction.response.send_message(
                f"There were no games between these two dates.",
                ephemeral=True,
            )


# ── Step 2: Report Type Menu ───────────────────────────────────

class ReportTypeView(View):
    """Three-option menu: All Time | Single Date | Date Range."""

    def __init__(self, username: str):
        super().__init__(timeout=120)
        self.username = username

    @discord.ui.select(
        placeholder="Choose a report type…",
        options=[
            discord.SelectOption(
                label="All Time",
                value="all_time",
                description="Stats across the entire dataset",
                emoji="🕒",
            ),
            discord.SelectOption(
                label="Single Date",
                value="single_date",
                description="Stats for one specific day",
                emoji="📅",
            ),
            discord.SelectOption(
                label="Date Range",
                value="date_range",
                description="Stats between two dates",
                emoji="🗓️",
            ),
        ],
    )
    async def report_type_select(
        self, interaction: discord.Interaction, select: Select
    ):
        choice = select.values[0]

        if choice == "all_time":
            await interaction.response.defer(ephemeral=True)
            if get_dates() != []:
                pdf_buffer = pdf.generate_player_report(self.username, get_dates())

                await interaction.followup.send(
                    f"Here is your **All Time** report, {get_names()[self.username]}!",
                    file=discord.File(pdf_buffer, filename=self.username + ".pdf"),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"There are no games in the database.",
                    ephemeral=True,
                )

        elif choice == "single_date":
            await interaction.response.send_modal(SingleDateModal(self.username))

        elif choice == "date_range":
            await interaction.response.send_modal(DateRangeModal(self.username))

        self.stop()


# ── Step 1: Username Modal ─────────────────────────────────────

class UsernameModal(Modal, title="Username"):
    username_input: TextInput = TextInput(
        label="Username",
        placeholder="Enter username",
        required=True,
        max_length=64,
    )

    async def on_submit(self, interaction: discord.Interaction):
        entered = self.username_input.value.strip().lower()

        if entered.lower() not in [u.lower() for u in get_usernames()]:
            await interaction.response.send_message(
                f"**{entered}** is not an authorised username. "
                "Please check your username and try `/stats` again.",
                ephemeral=True,
            )
            return

        report_view = ReportTypeView(username=entered)
        await interaction.response.send_message(
            f"Welcome, **{get_names()[entered]}**! Please choose a report type:",
            view=report_view,
            ephemeral=True,
        )


# ──────────────────────────────────────────────────────────────
# BOT SETUP
# ──────────────────────────────────────────────────────────────

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@tree.command(name="stats", description="Generate a stats report")
async def stats_command(interaction: discord.Interaction):
    """Entry point — opens the username modal."""
    await interaction.response.send_modal(UsernameModal())
@tree.command(name="games", description="Generate a game report")
async def games_command(interaction: discord.Interaction):
    """Entry point — opens the username modal."""
    await interaction.response.send_modal(UsernameModal())


@client.event
async def on_ready():
    await tree.sync()          # registers slash commands globally (can take ~1 hr to propagate)
    print(f"Logged in as {client.user} — /stats command is live!")


# ──────────────────────────────────────────────────────────────
# RUN
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    client.run(BOT_TOKEN)