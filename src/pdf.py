"""Quiz Bowl match & player report PDF generator.

Design reference: Match Report No. 0428 (Westbrook vs. Hartfield).
Uses reportlab for layout + matplotlib for embedded charts.
"""
from io import BytesIO
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, Flowable,
)
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
import matplotlib.pyplot as plt
import matplotlib
import sqlite3
import json
import datetime
matplotlib.use("Agg")
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ---------- palette (matches design) ----------
INK        = colors.HexColor("#111111")
MUTED      = colors.HexColor("#6B6B6B")
RULE       = colors.HexColor("#D9D9D9")
PAPER      = colors.HexColor("#FAFAF7")
POWER      = colors.HexColor("#257D2F")   # +15 dark green
GET        = colors.HexColor("#23BE2B")   # +10 green
NEG        = colors.HexColor("#C62828")   # -5 red
NEUTRAL    = colors.HexColor("#9E9E9E")   # no buzz
BONUS_HI   = colors.HexColor("#2E7D32")
BONUS_MID  = colors.HexColor("#9E9E9E")
BONUS_LO   = colors.HexColor("#C62828")

PAGE_MARGIN = 0.6 * inch


def get_names():
    conn = sqlite3.connect("players.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username, first_name, last_name FROM players")
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] + " " + row[2] for row in rows}


# ---------- paragraph styles ----------
def _styles():
    s = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=s["Normal"],
                          fontName="Helvetica", fontSize=9,
                          textColor=INK, leading=12)
    return {
        "base": base,
        "muted": ParagraphStyle("muted", parent=base, textColor=MUTED, fontSize=8),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold",
                             fontSize=22, leading=26, textColor=INK),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold",
                             fontSize=11, textColor=INK, spaceBefore=6, spaceAfter=4),
        "eyebrow": ParagraphStyle("eb", parent=base, fontName="Helvetica-Bold",
                                  fontSize=7, textColor=MUTED, leading=9),
        "stat": ParagraphStyle("stat", parent=base, fontName="Helvetica-Bold",
                               fontSize=18, leading=20, textColor=INK),
        "rightnum": ParagraphStyle("rn", parent=base, alignment=TA_RIGHT,
                                   fontName="Helvetica-Bold"),
    }


# ---------- small flowables ----------
class HLine(Flowable):
    def __init__(self, width, color=RULE, thickness=0.5):
        Flowable.__init__(self); self.w, self.c, self.t = width, color, thickness
    def wrap(self, *a): return (self.w, self.t)
    def draw(self):
        self.canv.setStrokeColor(self.c); self.canv.setLineWidth(self.t)
        self.canv.line(0, 0, self.w, 0)


class StackedBar(Flowable):
    """Player line: filled segments proportional to tossup outcome counts."""
    def __init__(self, width, height, segments):
        # segments: list of (count, color)
        Flowable.__init__(self)
        self.w, self.h = width, height
        total = sum(c for c, _ in segments) or 1
        self.segs = [(c / total, col) for c, col in segments if c]
    def wrap(self, *a): return (self.w, self.h)
    def draw(self):
        x = 0
        for frac, col in self.segs:
            w = frac * self.w
            self.canv.setFillColor(col); self.canv.setStrokeColor(col)
            self.canv.rect(x, 0, w, self.h, stroke=0, fill=1)
            x += w


class Slider(Flowable):
    """Horizontal percentage bar with color coding."""
    def __init__(self, width, height, pct, color):
        Flowable.__init__(self)
        self.w, self.h, self.pct, self.c = width, height, max(0, min(100, pct)), color
    def wrap(self, *a): return (self.w, self.h)
    def draw(self):
        self.canv.setFillColor(colors.HexColor("#EFEFEA"))
        self.canv.setStrokeColor(RULE); self.canv.setLineWidth(0.3)
        self.canv.roundRect(0, 0, self.w, self.h, self.h / 2, stroke=1, fill=1)
        fw = self.w * self.pct / 100
        if fw > 0:
            self.canv.setFillColor(self.c); self.canv.setStrokeColor(self.c)
            self.canv.roundRect(0, 0, max(fw, self.h), self.h, self.h / 2,
                                stroke=0, fill=1)


# ---------- chart helpers (matplotlib) ----------
def _fig_to_image(fig, width):
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight",
                facecolor="white")
    plt.close(fig); buf.seek(0)
    w, h = fig.get_size_inches()
    return Image(buf, width=width, height=width * h / w)


def _running_score_chart(rounds, teamA, teamB, width, split_x=None):
    """Line chart: running totals for both teams across rounds.

    If split_x is given, a dashed vertical divider is drawn there to separate
    the tossup and lightning phases (used by the full-game chart).
    """
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    xs = [r for r in rounds]
    a = [rounds[r]["a"] for r in rounds]
    b = [rounds[r]["b"] for r in rounds]
    ax.vlines(xs, [min(ai, bi) for ai, bi in zip(a, b)],
              [max(ai, bi) for ai, bi in zip(a, b)],
              color="#9E9E9E", lw=0.6, alpha=0.6, zorder=1)
    ax.plot(xs, a, color="#1F6FEB", lw=2, label=teamA, zorder=2)
    ax.plot(xs, b, color="#C62828", lw=2, label=teamB, zorder=2)
    ax.fill_between(xs, a, b, where=[ai >= bi for ai, bi in zip(a, b)],
                    color="#1F6FEB", alpha=0.06, interpolate=True)
    ax.fill_between(xs, a, b, where=[ai < bi for ai, bi in zip(a, b)],
                    color="#C62828", alpha=0.06, interpolate=True)
    ax.set_xlabel("Question", fontsize=8, color="#6B6B6B")
    ax.set_ylabel("Running Score", fontsize=8, color="#6B6B6B")
    ticks = list(range(0, max(xs) + 1))
    ax.set_xticks(ticks)
    ax.set_xlim(0, max(xs))  # align x=0 with the y-axis (no left padding)
    if split_x is not None:
        # restart the question count at 1 for the lightning phase past the divider
        boundary = int(split_x)
        ax.set_xticklabels([str(t if t <= boundary else t - boundary) for t in ticks])
    ax.grid(True, axis="y", lw=0.4, color="#E5E5E5")
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    ax.spines["left"].set_color("#D9D9D9"); ax.spines["bottom"].set_color("#D9D9D9")
    ax.tick_params(colors="#6B6B6B", labelsize=8)
    if split_x is not None:
        ax.axvline(split_x, color="#6B6B6B", lw=0.9, ls=(0, (4, 3)), alpha=0.8, zorder=3)
        ymax = ax.get_ylim()[1]
        ax.text(split_x - 0.2, ymax, "Tossups", ha="right", va="top",
                fontsize=7, color="#6B6B6B")
        ax.text(split_x + 0.2, ymax, "Lightning", ha="left", va="top",
                fontsize=7, color="#6B6B6B")
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    return _fig_to_image(fig, width)


# ---------- header / masthead ----------
def _header_block(packet, date, styles, width):
    eb = Paragraph(f"M A T C H &nbsp; R E P O R T &nbsp;",
                   styles["eyebrow"])
    title = Paragraph(f"{datetime.datetime.strptime(date, '%b %d, %Y, %I:%M:%S.%f %p').strftime('%B %d, %Y')}",
                      styles["h1"])
    return [eb, Spacer(1, 2), title, Spacer(1, 2), Spacer(1, 6),
            HLine(width, INK, 1.2)]


# ---------- player line table ----------
def _player_table(team, styles, width, seats = 1, team_name = None):
    rows = [["PLAYER", "PTS", "TOSSUP OUTCOME DISTRIBUTION"]]
    players = {}
    for data in team:
        if data[0] in players.keys():
            players[data[0]].append([data[1], data[2]])
        else:
            players[data[0]] = [[data[1], data[2]]]
    categories = ["lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash"]
    max_tuh = 0
    distrs = {}
    for p in players:
        tuh = sum([players[p][index][1][3] if players[p][index][0] in categories else 0 for index in range(len(players[p]))])
        # A combined-score team shares one username across every seat, so its
        # per-seat tossup-heard markers all land on this single entry. Collapse
        # them back so each question is counted once.
        if not p.isalpha():
            tuh = round(tuh / seats)
        point_distr = {
            "powers": sum([players[p][index][1][0] if players[p][index][0] in categories else 0 for index in range(len(players[p]))]),
            "tens": sum([players[p][index][1][1] if players[p][index][0] in categories else 0 for index in range(len(players[p]))]),
            "negs": sum([players[p][index][1][2] if players[p][index][0] in categories else 0 for index in range(len(players[p]))]),
            "tuh": tuh
        }
        distrs[p] = point_distr
        if point_distr["tuh"] > max_tuh:
            max_tuh = point_distr["tuh"]

    names = get_names()
    for p in players:
        point_distr = distrs[p]
        segs = [(point_distr["powers"], POWER), (point_distr["tens"], GET),
                (point_distr["negs"], NEG), (max(0, max_tuh - (point_distr["powers"] + point_distr["tens"] + point_distr["negs"])), NEUTRAL)]
        name = Paragraph(
            f"<b>{names[p] if p.isalpha() else 'Combined Score'}</b><br/>",
            styles["base"])
        rows.append([name, str(point_distr["powers"] * 15 + point_distr["tens"] * 10 + point_distr["negs"] * -5),
                     StackedBar(width * 0.4, 10, segs)])
    cw = [0.22, 0.08, 0.45, 0.25]
    t = Table(rows, colWidths=[c * width for c in cw])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
        ("FONT", (1, 1), (1, -1), "Helvetica-Bold", 11),
    ]))
    return t


def _team_block(team, styles, width, seats = 1):
    return [
        Spacer(1, 4),
        _player_table(team, styles, width, seats),
        Spacer(1, 10),
    ]

def _player_table_lightning(team, styles, width):
    rows = [["PLAYER", "PTS", "LIGHTNING OUTCOME DISTRIBUTION"]]
    players = {}
    for data in team:
        if data[0] in players.keys():
            players[data[0]].append([data[1], data[2]])
        else:
            players[data[0]] = [[data[1], data[2]]]
    max_tuh = 0
    distrs = {}
    for p in players:
        point_distr = {
            "tens": sum([players[p][index][1][0] if players[p][index][0] == "lightning" else 0 for index in range(len(players[p]))]),
            "negs": sum([players[p][index][1][1] if players[p][index][0] == "lightning" else 0 for index in range(len(players[p]))]),
            "tuh": sum([players[p][index][1][2] if players[p][index][0] == "lightning" else 0 for index in range(len(players[p]))])
        }
        distrs[p] = point_distr
        if point_distr["tuh"] > max_tuh:
            max_tuh = point_distr["tuh"]

    names = get_names()
    for p in players:
        point_distr = distrs[p]
        segs = [(point_distr["tens"], GET),
                (point_distr["negs"], NEG), (max(0, max_tuh - (point_distr["tens"] + point_distr["negs"])), NEUTRAL)]
        name = Paragraph(
            f"<b>{names[p] if p.isalpha() else 'Combined Score'}</b><br/>",
            styles["base"])
        rows.append([name, str(point_distr["tens"] * 10 + point_distr["negs"] * -10),
                     StackedBar(width * 0.4, 10, segs)])
    cw = [0.22, 0.08, 0.45, 0.25]
    t = Table(rows, colWidths=[c * width for c in cw])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
        ("FONT", (1, 1), (1, -1), "Helvetica-Bold", 11),
    ]))
    return t


def _team_block_lightning(team, styles, width):
    return [
        Spacer(1, 4),
        _player_table_lightning(team, styles, width),
        Spacer(1, 10),
    ]


# ---------- bonus conversion (match report) ----------
def _bonus_table(bonus_data, team_a, team_b, styles, width):
    """Bonus conversion line for both teams: answered / heard / conversion / PP3BH.

    bonus_data: {"a": [answered, heard], "b": [answered, heard]}
    """
    rows = [["TEAM", "ANSWERED", "HEARD", "CONVERSION", "PP3BH", "RATE"]]
    for team, label in (("a", team_a), ("b", team_b)):
        ans, heard = bonus_data[team][0], bonus_data[team][1]
        conv = ans / heard * 100 if heard > 0 else 0
        pp3bh = ans / heard * 30 if heard > 0 else 0
        rows.append([
            Paragraph(f"<b>{label}</b>", styles["base"]),
            str(ans), str(heard),
            f"{conv:.1f}%", f"{pp3bh:.1f}",
            Slider(width * 0.22, 10, conv, _bonus_color(conv)),
        ])
    cw = [0.22, 0.13, 0.13, 0.15, 0.12, 0.25]
    t = Table(rows, colWidths=[c * width for c in cw])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-2, -1), "CENTER"),
        ("ALIGN", (-1, 0), (-1, -1), "LEFT"),
        ("FONT", (1, 1), (-2, -1), "Helvetica-Bold", 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


# ---------- lightning conversion (match report) ----------
def _lightning_table(lightning_team_data, styles, width):
    """Lightning conversion line for both teams: correct / incorrect / heard / conversion.

    lightning_team_data: {"a": [correct, incorrect, heard], "b": [correct, incorrect, heard]}
    """
    rows = [["TEAM", "CORRECT", "INCORRECT", "HEARD", "CONVERSION", "RATE"]]
    for team, label in (("a", "Team A"), ("b", "Team B")):
        correct, incorrect, heard = lightning_team_data[team][0], lightning_team_data[team][1], lightning_team_data[team][2]
        conv = correct / heard * 100 if heard > 0 else 0
        rows.append([
            Paragraph(f"<b>{label}</b>", styles["base"]),
            str(correct), str(incorrect), str(heard),
            f"{conv:.1f}%",
            Slider(width * 0.22, 10, conv, _bonus_color(conv)),
        ])
    cw = [0.22, 0.13, 0.13, 0.15, 0.12, 0.25]
    t = Table(rows, colWidths=[c * width for c in cw])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-2, -1), "CENTER"),
        ("ALIGN", (-1, 0), (-1, -1), "LEFT"),
        ("FONT", (1, 1), (-2, -1), "Helvetica-Bold", 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


# ---------- legend ----------
def _legend(styles, width):
    items = [("Power · +15", POWER), ("Get · +10", GET),
             ("No buzz · 0", NEUTRAL), ("Neg · −5", NEG)]
    cells = []
    for label, col in items:
        cells.append(StackedBar(10, 10, [(1, col)]))
        cells.append(Paragraph(f"<font size=7 color='#6B6B6B'>{label}</font>",
                               styles["base"]))
    t = Table([cells], colWidths=[14, 60] * 4)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    return t


# ---------- seat-count helper ----------
def _seat_count(player_data, team, phase, categories):
    """Recover a team's seat count from the stored event log.

    The client queues exactly one "heard" marker per seat on every question
    (a [0, 0, 0, 1] tossup-heard in the question's category, or a [0, 0, 1]
    lightning-heard), so the most such markers seen in any single question
    equals the seat count. This works even for combined (non-individual) teams,
    where every seat shares one username, so distinct-username counting would
    fail. Used to undo the per-seat duplication of team-level bonus/lightning
    events when aggregating them.
    """
    per_q = {}
    for e in player_data:
        if e["team"] != team:
            continue
        field, value = e["question_data"][1], e["question_data"][2]
        if phase == "tossup":
            is_heard = field in categories and value == [0, 0, 0, 1]
        else:
            is_heard = field == "lightning" and value == [0, 0, 1]
        if is_heard:
            per_q[e["question_num"]] = per_q.get(e["question_num"], 0) + 1
    return max(per_q.values(), default=1)


# ---------- public: match report ----------
def generate_match_report(date, out_path = None):
    """data schema:
    {
      match_no, date, venue, moderator,
      team_a: {name, seed, record, nickname, score, captain, players:[...]},
      team_b: {same},
      rounds: [{tu, category, subject, a_buzz, b_buzz, bonus,
                a_total, b_total, margin, a_name, b_name}],
    }
    """

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

    conn.commit()
    conn.close()

    game_data = []
    round_data = {0: {"a": 0, "b": 0}}
    bonus_data = {"a": [0, 0], "b": [0, 0]}
    lightning_team_data = {"a": [0, 0, 0], "b": [0, 0, 0]}
    has_tossup = False
    teamA = []
    teamB = []

    for i in range(len(rows)):
        rows[i]["data"] = json.loads(rows[i]["data"])
        if rows[i]["date"] == date:
            game_data = rows[i]["data"]
            break

    if not game_data:
        return None

    game_data["player_data"].sort(key = lambda x: x["question_num"])

    categories = ["lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash"]

    # Bonus and lightning-heard events are queued once per seat, so team-level
    # aggregates must be divided by the seat count to avoid inflating them by the
    # number of players on the team.
    seats = {t: _seat_count(game_data["player_data"], t, "tossup", categories) for t in ("a", "b")}
    lightning_seats = {t: _seat_count(game_data["player_data"], t, "lightning", categories) for t in ("a", "b")}

    for i in game_data["player_data"]:
        if not i["question_num"] in round_data.keys() and i["question_data"][1] != "lightning":
            round_data[i["question_num"]] = {"a": round_data[i["question_num"] - 1]["a"] if i["question_num"] - 1 in round_data.keys() else 0, "b": round_data[i["question_num"] - 1]["b"] if i["question_num"] - 1 in round_data.keys() else 0}
        team = i["team"]
        if i["question_data"][1] != "lightning":
            has_tossup = True
        if i["question_data"][1] in categories:
            round_data[i["question_num"]][team] += 15 * i["question_data"][2][0]
            round_data[i["question_num"]][team] += 10 * i["question_data"][2][1]
            round_data[i["question_num"]][team] -= 5 * i["question_data"][2][2]
        if i["question_data"][1] == "bonus_ans":
            round_data[i["question_num"]][team] += 10 / seats[team]
            bonus_data[team][0] += 1
        if i["question_data"][1] == "bonus_heard":
            bonus_data[team][1] += 1
    # Undo the per-seat duplication: each correct/heard bonus part was recorded
    # once per seat, so collapse those back to one count (and one 10-pt swing).
    for q in round_data:
        round_data[q]["a"] = round(round_data[q]["a"])
        round_data[q]["b"] = round(round_data[q]["b"])
    for t in ("a", "b"):
        bonus_data[t][0] = round(bonus_data[t][0] / seats[t])
        bonus_data[t][1] = round(bonus_data[t][1] / seats[t])
    max_index = max(round_data.keys())
    lightning_data = {0: {"a": round_data[max_index]["a"], "b": round_data[max_index]["b"]}}
    has_lightning = False
    for i in game_data["player_data"]:
        if i["question_data"][1] == "lightning":
            team = i["team"]
            if not i["question_num"] in lightning_data.keys():
                lightning_data[i["question_num"]] = {"a": lightning_data[i["question_num"] - 1]["a"] if i["question_num"] - 1 in lightning_data.keys() else 0, "b": lightning_data[i["question_num"] - 1]["b"] if i["question_num"] - 1 in lightning_data.keys() else 0}
            lightning_data[i["question_num"]][team] += 10 * i["question_data"][2][0]
            lightning_data[i["question_num"]][team] -= 10 * i["question_data"][2][1]
            lightning_team_data[team][0] += i["question_data"][2][0]
            lightning_team_data[team][1] += i["question_data"][2][1]
            lightning_team_data[team][2] += i["question_data"][2][2]
            has_lightning = True

    # "Heard" is logged once per seat each lightning question; correct/incorrect
    # are logged only for the answering seat. Collapse heard back to per-team so
    # the conversion rate (correct / heard) isn't divided by the team size.
    for t in ("a", "b"):
        lightning_team_data[t][2] = round(lightning_team_data[t][2] / lightning_seats[t])

    # full-game running score: tossups, then lightning continued from the tossup
    # final. Lightning is re-indexed to start at 1 right after the last tossup, so
    # its counter is independent of the raw lightning question numbers.
    full_data = {}
    for k in sorted(round_data.keys()):
        full_data[k] = round_data[k]
    lightning_keys = sorted(k for k in lightning_data.keys() if k != 0)
    for offset, k in enumerate(lightning_keys, start=1):
        full_data[max_index + offset] = lightning_data[k]

    for data in game_data["player_data"]:
        if data["team"] == "a":
            teamA.append([data["question_data"][0], data["question_data"][1], data["question_data"][2]])
        elif data["team"] == "b":
            teamB.append([data["question_data"][0], data["question_data"][1], data["question_data"][2]])

    styles = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(out_path or buf, pagesize=LETTER,
                            leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
                            topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN)
    W = LETTER[0] - 2 * PAGE_MARGIN
    story = []
    story += _header_block(game_data["packet"], date, styles, W)

    section = 0

    eyebrow_team_a = ""
    for i in range(len(game_data["a_name"])):
        eyebrow_team_a = eyebrow_team_a + game_data["a_name"][i].upper() + " "
    for i in range(len(eyebrow_team_a)):
        try:
            if eyebrow_team_a[i - 1:i + 2] == "   ":
                eyebrow_team_a = eyebrow_team_a[:i] + "&nbsp;" + eyebrow_team_a[i + 1 :]
        except:
            pass
    eyebrow_team_b = ""
    for i in range(len(game_data["b_name"])):
        eyebrow_team_b = eyebrow_team_b + game_data["b_name"][i].upper() + " "
    for i in range(len(eyebrow_team_b)):
        try:
            if eyebrow_team_b[i - 1:i + 2] == "   ":
                eyebrow_team_b = eyebrow_team_b[:i] + "&nbsp;" + eyebrow_team_b[i + 1 :]
        except:
            pass

    # tossup stats (only if tossup data exists)
    if has_tossup:
        section += 1
        story.append(Paragraph(f"§ {section:02d} &nbsp; Tossup data", styles["h2"]))
        story.append(Spacer(1, 8))
        story.append(Paragraph(eyebrow_team_a, styles["eyebrow"]))
        story.append(Spacer(1, 4))
        story += _team_block(teamA, styles, W, seats["a"])
        #story.append(HLine(W, INK, 1.2))
        story.append(Spacer(1, 8))
        story.append(Paragraph(eyebrow_team_b, styles["eyebrow"]))
        story.append(Spacer(1, 4))
        story += _team_block(teamB, styles, W, seats["b"])
        #story.append(HLine(W, INK, 1.2))
        story.append(Spacer(1, 8))
        story.append(_legend(styles, W))
        story.append(Spacer(1, 8))

        # bonus conversion (both teams)
        story.append(Paragraph("B O N U S &nbsp; C O N V E R S I O N", styles["eyebrow"]))
        story.append(Spacer(1, 4))
        story.append(_bonus_table(bonus_data, game_data["a_name"], game_data["b_name"], styles, W))
        story.append(Spacer(1, 12))
        story.append(Paragraph("T O S S U P &nbsp; C H A R T", styles["eyebrow"]))
        story.append(_running_score_chart(round_data, game_data["a_name"], game_data["b_name"], W))

    # lightning stats (only if lightning data exists)
    if has_lightning:
        if has_tossup:
            story.append(PageBreak())
        section += 1
        story.append(Paragraph(f"§ {section:02d} &nbsp; Lightning data", styles["h2"]))
        story.append(Spacer(1, 8))
        story.append(Paragraph(eyebrow_team_a, styles["eyebrow"]))
        story.append(Spacer(1, 4))
        story += _team_block_lightning(teamA, styles, W)
        #story.append(HLine(W, INK, 1.2))
        story.append(Spacer(1, 8))
        story.append(Paragraph(eyebrow_team_b, styles["eyebrow"]))
        story.append(Spacer(1, 4))
        story += _team_block_lightning(teamB, styles, W)
        #story.append(HLine(W, INK, 1.2))
        story.append(Spacer(1, 8))

        # lightning conversion (both teams)
        story.append(Paragraph("L I G H T N I N G &nbsp; C O N V E R S I O N", styles["eyebrow"]))
        story.append(Spacer(1, 4))
        story.append(_lightning_table(lightning_team_data, styles, W))
        story.append(Spacer(1, 12))
        story.append(Paragraph("L I G H T N I N G &nbsp; C H A R T", styles["eyebrow"]))
        story.append(_running_score_chart(lightning_data, game_data["a_name"], game_data["b_name"], W))

    # full game chart (only when the match has both tossup and lightning phases)
    if has_tossup and has_lightning:
        story.append(PageBreak())
        section += 1
        story.append(Paragraph(f"§ {section:02d} &nbsp; Full game", styles["h2"]))
        story.append(Spacer(1, 4))
        story.append(Paragraph("F U L L &nbsp; G A M E &nbsp; C H A R T", styles["eyebrow"]))
        story.append(_running_score_chart(full_data, game_data["a_name"], game_data["b_name"], W, split_x=max_index))

    doc.build(story)
    buf.seek(0)
    return out_path if out_path else buf


# ---------- player report ----------
def _bonus_color(pct):
    if pct >= 67: return BONUS_HI
    if pct >= 34: return BONUS_MID
    return BONUS_LO


def _category_slider_table(cats, styles, width):
    rows = []
    categories = ["lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash"]
    for c in cats:
        if c in categories:
            if cats[c][3] == 0:
                cats[c][3] = 0.1

            segs = [(cats[c][0], POWER), (cats[c][1], GET),
                ((cats[c][3] - (cats[c][0] + cats[c][1] + cats[c][2])), NEUTRAL), (cats[c][2], NEG)]
            rows.append([
                cats[c][4], f"{(cats[c][0] / cats[c][3] * 100):.1f}" + "%",
                StackedBar(width * 0.32, 10, segs), str(cats[c][3] if cats[c][3] != 0.1 else 0),
                str(cats[c][0]) + "/" + str(cats[c][1]) + "/" + str(cats[c][2]),
                str(cats[c][0] * 15 + cats[c][1] * 10 + cats[c][2] * -5),
            ])
    rows.sort(key = lambda x: int(x[5]), reverse = True)
    rows = [["CATEGORY", "P%", "ACCURACY", "TUH", "DISTRIBUTION", "PTS"]] + rows
    cw = [0.22, 0.06, 0.36, 0.12, 0.12, 0.12]
    t = Table(rows, colWidths=[c * width for c in cw])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("ALIGN", (4, 0), (4, -1), "CENTER"),
        ("ALIGN", (5, 0), (5, -1), "CENTER"),
        ("FONT", (0, 1), (0, -1), "Helvetica-Bold", 9),
        ("FONT", (1, 1), (1, -1), "Helvetica-Bold", 9),
        ("FONT", (3, 1), (3, -1), "Helvetica-Bold", 9),
        ("FONT", (4, 1), (4, -1), "Helvetica-Bold", 9),
        ("FONT", (5, 1), (5, -1), "Helvetica-Bold", 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _stat_tile(label, value, styles, width):
    inner = Table(
        [[Paragraph(value, styles["stat"])],
         [Paragraph(label, styles["eyebrow"])]],
        colWidths=[width])
    inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("BACKGROUND", (0, 0), (-1, -1), PAPER),
    ]))
    return inner


def generate_player_report(player, games, out_path = None):
    """player_data schema:
    {
      match_no, date, venue,
      player: {name, class, team, nickname, captain:bool},
      totals: {points, powers, gets, negs, no_buzz, ppg, buzz_rate_pct},
      categories: [{name, n, pct, points}],
      recent_matches: [{opp, score, pts, powers}],   # optional
    }
    """

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

    conn.commit()
    conn.close()

    player_data = []

    for i in range(len(rows)):
        rows[i]["data"] = json.loads(rows[i]["data"])
        if rows[i]["date"] in games:
            for stat in rows[i]["data"]["player_data"]:
                if stat["question_data"][0] == player:
                    player_data.append([stat["question_data"][1], stat["question_data"][2]])

    if not player_data:
        return None

    styles = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(out_path or buf, pagesize=LETTER,
                            leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
                            topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN)
    W = LETTER[0] - 2 * PAGE_MARGIN
    #p, tot = player_data["player"], player_data["totals"]
    story = []

    conn = sqlite3.connect("players.db")
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM players")
        result = cursor.fetchall()
    except:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS players (
                username TEXT PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL
            )
        """)
        conn.commit()

        cursor.execute("SELECT * FROM players")
        result = cursor.fetchall()

    rows = [dict(row) for row in result]
    conn.close()
    player_flag = False
    name = ""
    for i in rows:
        if i["username"] == player:
            player_flag = True
            name = i["first_name"] + " " + i["last_name"]

    if not player_flag:
        return None
    
    categories = ["lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash"]
    master_data_list = {"lit": [0, 0, 0, 0, "Literature"], "history": [0, 0, 0, 0, "History"], "science": [0, 0, 0, 0, "Science"], "fine_arts": [0, 0, 0, 0, "Fine Arts"], "geography": [0, 0, 0, 0, "Geography"], "current_events": [0, 0, 0, 0, "Current Events"], "rmpss": [0, 0, 0, 0, "RMPSS"], "trash": [0, 0, 0, 0, "Trash"], "lightning": [0, 0, 0], "bonus_ans": 0, "bonus_heard": 0}

    for i in player_data:
        for category in categories:
            if i[0] == category:
                master_data_list[category][0] += i[1][0]
                master_data_list[category][1] += i[1][1]
                master_data_list[category][2] += i[1][2]
                master_data_list[category][3] += i[1][3]
                break
        if i[0] == "bonus_ans":
            master_data_list["bonus_ans"] += i[1]
        elif i[0] == "bonus_heard":
            master_data_list["bonus_heard"] += i[1]
        elif i[0] == "lightning":
                master_data_list["lightning"][0] += i[1][0]
                master_data_list["lightning"][1] += i[1][1]
                master_data_list["lightning"][2] += i[1][2]

    # header
    story.append(Paragraph(
        f"P L A Y E R &nbsp; R E P O R T &nbsp;",
        styles["eyebrow"]))
    story.append(Spacer(1, 2))
    story.append(Paragraph(name, styles["h1"]))
    story.append(Spacer(1, 6))
    story.append(HLine(W, INK, 1.2))
    story.append(Spacer(1, 12))

    point_distr = {
        "powers": sum([(master_data_list[section][0]) if section in categories else 0 for section in master_data_list]),
        "tens": sum([(master_data_list[section][1]) if section in categories else 0 for section in master_data_list]),
        "negs": sum([(master_data_list[section][2]) if section in categories else 0 for section in master_data_list]),
        "tuh": sum([(master_data_list[section][3]) if section in categories else 0 for section in master_data_list])  
    }

    # stat tiles
    tiles = [
        _stat_tile("POWERS", str(point_distr["powers"]), styles, W / 6),
        _stat_tile("TENS", str(point_distr["tens"]), styles, W / 6),
        _stat_tile("NEGS", str(point_distr["negs"]), styles, W / 6),
        _stat_tile("TOSSUPS HEARD", str(point_distr["tuh"]), styles, W / 6),
        _stat_tile("TOTAL POINTS", str(point_distr["powers"] * 15 + point_distr["tens"] * 10 + -5 * point_distr["negs"]), styles, W / 6),
        _stat_tile("PP20TUH", f"{((point_distr['powers'] * 15 + point_distr['tens'] * 10 + -5 * point_distr['negs']) / (point_distr['tuh'] if point_distr['tuh'] > 0 else 1) * 20):.1f}", styles, W / 6),
    ]
    tile_row = Table([tiles], colWidths=[W / 6] * 6)
    tile_row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(tile_row)
    story.append(Spacer(1, 16))

    # buzz distribution
    story.append(Paragraph("§ 01 &nbsp; Question distribution", styles["h2"]))
    segs = [(point_distr["powers"], POWER), (point_distr["tens"], GET),
            (point_distr["tuh"] - (point_distr["powers"] + point_distr["tens"] + point_distr["negs"]), NEUTRAL), (point_distr["negs"], NEG)]
    story.append(StackedBar(W, 14, segs))
    story.append(Spacer(1, 4))
    story.append(_legend(styles, W))
    story.append(Spacer(1, 14))

    # category sliders
    story.append(Paragraph("§ 02 &nbsp; Category accuracy", styles["h2"]))
    """story.append(Paragraph(
        "Accuracy by subject. Green ≥ 67%, gray 34–66%, red < 34%.",
        styles["muted"]))"""
    story.append(Spacer(1, 4))
    story.append(_category_slider_table(master_data_list, styles, W))

    """# optional recent matches
    if player_data.get("recent_matches"):
        story.append(Spacer(1, 14))
        story.append(Paragraph("§ 03 &nbsp; Recent matches", styles["h2"]))
        rows = [["OPPONENT", "SCORE", "PTS", "POWERS"]]
        for m in player_data["recent_matches"]:
            rows.append([m["opp"], m["score"], str(m["pts"]), str(m["powers"])])
        tbl = Table(rows, colWidths=[W * 0.45, W * 0.2, W * 0.15, W * 0.2])
        tbl.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
            ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
            ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(tbl)"""
    
    story.append(Paragraph("§ 03 &nbsp; Bonus Conversion", styles["h2"]))
    tiles = [
        _stat_tile("ANSWERED", str(master_data_list["bonus_ans"]), styles, W / 4),
        _stat_tile("HEARD", str(master_data_list["bonus_heard"]), styles, W / 4),
        _stat_tile("CONVERSION", f"{master_data_list['bonus_ans'] / master_data_list['bonus_heard'] * 100 if master_data_list['bonus_heard'] > 0 else 0:.1f}" + "%", styles, W / 4),
        _stat_tile("PP3BH", f"{master_data_list['bonus_ans'] / master_data_list['bonus_heard'] * 30 if master_data_list['bonus_heard'] > 0 else 0:.1f}", styles, W / 4)
    ]
    tile_row = Table([tiles], colWidths=[W / 4] * 4)
    tile_row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(tile_row)
    story.append(Spacer(1, 16))

    story.append(Paragraph("§ 04 &nbsp; Lightning Conversion", styles["h2"]))
    tiles = [
        _stat_tile("CORRECT", str(master_data_list["lightning"][0]), styles, W / 5),
        _stat_tile("INCORRECT", str(master_data_list["lightning"][1]), styles, W / 5),
        _stat_tile("HEARD", str(master_data_list["lightning"][2]), styles, W / 5),
        _stat_tile("POINTS", str(master_data_list["lightning"][0] * 10 + master_data_list["lightning"][1] * -10), styles, W / 5),
        _stat_tile("CONVERSION", f"{master_data_list['lightning'][0] / master_data_list['lightning'][2] * 100 if master_data_list['lightning'][2] > 0 else 0:.1f}" + "%", styles, W / 5)
    ]
    tile_row = Table([tiles], colWidths=[W / 5] * 5)
    tile_row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(tile_row)
    story.append(Spacer(1, 16))

    doc.build(story)
    buf.seek(0)
    return out_path if out_path else buf

if __name__ == "__main__":
    generate_match_report('Jun 25, 2026, 04:54:26.600221 PM', "match_report.pdf")
    generate_player_report("ethanf", ["May 31, 2026, 04:29:56.047386 PM"], "player_report.pdf")
    print("OK")