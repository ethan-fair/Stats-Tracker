import discord
from discord import app_commands
from discord.ui import View, Select, Modal, TextInput
import datetime
import sqlite3
import pdf
import json
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def load_env():
    if not os.path.exists(".env"):
        return

    with open(".env", "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip()

load_env()

BOT_TOKEN = os.getenv("KEY")

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
    cursor.execute("SELECT username, first_name, last_name FROM players")
    rows = cursor.fetchall()
    conn.close()
    name_list = {}
    for username, first_name, last_name in rows:
        name_list[username] = first_name + " " + last_name
    return name_list

def get_name(username):
    """Look up a player's display name, tolerating case differences between the
    entered username and the one stored in the database. Falls back to the
    username itself if no matching player is found."""
    names = get_names()
    if username in names:
        return names[username]
    lowered = {k.lower(): v for k, v in names.items()}
    return lowered.get(username.lower(), username)

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

        await interaction.response.defer(ephemeral=True)

        date_info = selected_date.strftime("%B %d, %Y")

        dates_to_use = []
        for date in get_dates():
            date_obj = datetime.datetime.strptime(date, "%b %d, %Y, %I:%M:%S.%f %p").date()
            if date_obj == selected_date:
                dates_to_use.append(date)

        if dates_to_use != []:
            pdf_buffer = pdf.generate_player_report(self.username, dates_to_use)

            if pdf_buffer is None:
                await interaction.followup.send(
                    f"No stats were recorded for {get_name(self.username)} on this date.",
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                f"Here is your **Single Date** report ({date_info}), {get_name(self.username)}!",
                file=discord.File(pdf_buffer, filename=self.username + ".pdf"),
                ephemeral=True,
            )

        else:
            await interaction.followup.send(
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

        await interaction.response.defer(ephemeral=True)

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

            if pdf_buffer is None:
                await interaction.followup.send(
                    f"No stats were recorded for {get_name(self.username)} between these two dates.",
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                f"Here is your **Date Range** report ({date_info}), {get_name(self.username)}!",
                file=discord.File(pdf_buffer, filename=self.username + ".pdf"),
                ephemeral=True,
            )

        else:
            await interaction.followup.send(
                f"There were no games between these two dates.",
                ephemeral=True,
            )


# ── Step 2: Report Type Menu ───────────────────────────────────

class ReportTypeView(View):

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

                if pdf_buffer is None:
                    await interaction.followup.send(
                        f"No stats were recorded for {get_name(self.username)}.",
                        ephemeral=True,
                    )
                    self.stop()
                    return

                await interaction.followup.send(
                    f"Here is your **All Time** report, {get_name(self.username)}!",
                    file=discord.File(pdf_buffer, filename=self.username + ".pdf"),
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"There are no games in the database.",
                    ephemeral=True,
                )

        elif choice == "single_date":
            await interaction.response.send_modal(SingleDateModal(self.username))

        elif choice == "date_range":
            await interaction.response.send_modal(DateRangeModal(self.username))

        self.stop()

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@tree.command(name="stats", description="Generate a stats report")
async def stats_command(interaction: discord.Interaction, username: str):
    entered = username.strip().lower()
    if entered.lower() not in [u.lower() for u in get_usernames()]:
        await interaction.response.send_message(
            f"**{entered}** is not an authorised username. "
            "Please check your username and try `/stats` again.",
            ephemeral=True,
        )
        return

    report_view = ReportTypeView(username=entered)
    await interaction.response.send_message(
        f"Welcome, **{get_name(entered)}**! Please choose a report type:",
        view=report_view,
        ephemeral=True,
    )

def get_all_games() -> tuple[list[str], dict[str, str]]:
    conn = sqlite3.connect("players.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    #try:
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
    #except Exception:
        #rows = []
        #print("Exception")
    conn.close()

    games = {}
    dates = []
    for row in rows:
        parsed = json.loads(row["data"])
        games[row["date"]] = parsed
        dates.append(row["date"])
    dates = sorted(dates, key=lambda x: datetime.datetime.strptime(x, "%b %d, %Y, %I:%M:%S.%f %p"), reverse=True)
    return_games = {}
    for i in range(len(dates)):
        date = dates[i]
        dates[i] = datetime.datetime.strptime(date, "%b %d, %Y, %I:%M:%S.%f %p").strftime("%a %b %d, %I:%M %p, %Y") + " - " + games[dates[i]]["name"]
        return_games[dates[i]] = date
    #print(return_games)
    return dates, return_games

@tree.command(name="games", description="Generate a report for a specific game")
@app_commands.describe(game="Start typing to search for a game")
async def game_report_command(interaction: discord.Interaction, game: str):
    """Receives the chosen game name and sends back a PDF report."""
    all_games, linked = get_all_games()
    if game not in all_games:
        await interaction.response.send_message(
            f"**{game}** was not found in the database. "
            "Please choose a game from the autocomplete suggestions.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        pdf_buffer = pdf.generate_match_report(linked[game])
    except Exception as e:
        print(f"Failed to build match report for {linked[game]}: {type(e).__name__}: {e}")
        await interaction.followup.send(
            f"Something went wrong while building the report for **{game}**.",
            ephemeral=True,
        )
        return

    if pdf_buffer is None:
        await interaction.followup.send(
            f"No stats were recorded for **{game}**.",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"Here is the report for **{game}**!",
        file=discord.File(pdf_buffer, filename="game_data.pdf"),
        ephemeral=True,
    )


@game_report_command.autocomplete("game")
async def game_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Filter the full games list as the user types."""
    all_games, linked = get_all_games()
    matches = [g for g in all_games if current.lower() in g.lower()]
    return [
        app_commands.Choice(name=g, value=g)
        for g in matches
    ][:25]


@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user}, fully synced.")

if __name__ == "__main__":
    client.run(BOT_TOKEN)