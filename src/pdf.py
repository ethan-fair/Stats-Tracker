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


def _running_score_chart(rounds, width):
    """Line chart: running totals for both teams across rounds."""
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    xs = [r for r in rounds]
    a = [rounds[r]["a"] for r in rounds]
    b = [rounds[r]["b"] for r in rounds]
    ax.vlines(xs, [min(ai, bi) for ai, bi in zip(a, b)],
              [max(ai, bi) for ai, bi in zip(a, b)],
              color="#9E9E9E", lw=0.6, alpha=0.6, zorder=1)
    ax.plot(xs, a, color="#1F6FEB", lw=2, label="Team A", zorder=2)
    ax.plot(xs, b, color="#C62828", lw=2, label="Team B", zorder=2)
    ax.fill_between(xs, a, b, where=[ai >= bi for ai, bi in zip(a, b)],
                    color="#1F6FEB", alpha=0.06, interpolate=True)
    ax.fill_between(xs, a, b, where=[ai < bi for ai, bi in zip(a, b)],
                    color="#C62828", alpha=0.06, interpolate=True)
    ax.set_xlabel("Tossup", fontsize=8, color="#6B6B6B")
    ax.set_ylabel("Running Score", fontsize=8, color="#6B6B6B")
    ax.set_xticks(range(0, max(xs) + 1))
    ax.grid(True, axis="y", lw=0.4, color="#E5E5E5")
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    ax.spines["left"].set_color("#D9D9D9"); ax.spines["bottom"].set_color("#D9D9D9")
    ax.tick_params(colors="#6B6B6B", labelsize=8)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    return _fig_to_image(fig, width)


# ---------- tossup outcome helpers ----------
_OUTCOME_COLOR = {15: POWER, 10: GET, -5: NEG, 0: NEUTRAL}

def _outcome_label(v):
    return {15: "+15", 10: "+10", -5: "−5", 0: "—"}.get(v, str(v))


# ---------- header / masthead ----------
def _header_block(packet, date, styles, width):
    eb = Paragraph(f"M A T C H &nbsp; R E P O R T &nbsp;",
                   styles["eyebrow"])
    title = Paragraph(f"{datetime.datetime.strptime(date, "%b %d, %Y, %I:%M:%S.%f %p").strftime("%B %d, %Y")}",
                      styles["h2"])
    title = Paragraph(f"{datetime.datetime.strptime(date, "%b %d, %Y, %I:%M:%S.%f %p").strftime("%B %d, %Y")}",
                      styles["h1"])
    return [eb, Spacer(1, 2), title, Spacer(1, 2), Spacer(1, 6),
            HLine(width, INK, 1.2), Spacer(1, 10)]


# ---------- summary strip ----------
def _summary_strip(data, styles, width):
    a, b = data["team_a"], data["team_b"]
    winner = a if a["score"] >= b["score"] else b
    margin = abs(a["score"] - b["score"])
    left = [
        Paragraph(f"WINNER · #{winner['seed']} SEED", styles["eyebrow"]),
        Paragraph(winner["name"], styles["h1"]),
        Paragraph(f"{winner['record']} · {winner['nickname']}", styles["muted"]),
    ]
    mid = [
        Paragraph("FINAL", styles["eyebrow"]),
        Paragraph(f"{a['score']}–{b['score']}", styles["h1"]),
        Paragraph(f"Margin {margin}", styles["muted"]),
    ]
    loser = b if winner is a else a
    right = [
        Paragraph(f"#{loser['seed']} SEED", styles["eyebrow"]),
        Paragraph(loser["name"], styles["h1"]),
        Paragraph(f"{loser['record']} · {loser['nickname']}", styles["muted"]),
    ]
    t = Table([[left, mid, right]], colWidths=[width * 0.4, width * 0.2, width * 0.4])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [t, Spacer(1, 10), HLine(width), Spacer(1, 10)]


# ---------- round-by-round scorecard ----------
def _round_table(rounds, styles, width):
    header = ["TU", "PLAYER / CATEGORY", "TEAM 1", "TEAM 2", "BONUS", "TEAM A SCORE", "TEAM B SCORE", "MARGIN"]
    rows = [header]
    for r in rounds:
        rows.append([
            f"{r['tu']:02d}",
            Paragraph(f"<b>{r['category']}</b><br/><font color='#6B6B6B' size=7>{r['subject']}</font>",
                      styles["base"]),
            _outcome_label(r["a_buzz"]),
            _outcome_label(r["b_buzz"]),
            r.get("bonus", "—"),
            str(r["a_total"]),
            str(r["b_total"]),
            f"{'+' if r['margin'] >= 0 else ''}{r['margin']}",
        ])
    cw = [0.05, 0.32, 0.09, 0.09, 0.1, 0.1, 0.1, 0.15]
    t = Table(rows, colWidths=[c * width for c in cw], repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
        ("TEXTCOLOR", (0, 1), (0, -1), MUTED),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    # color outcome cells
    for i, r in enumerate(rounds, start=1):
        for col, v in ((2, r["a_buzz"]), (3, r["b_buzz"])):
            style.append(("TEXTCOLOR", (col, i), (col, i), _OUTCOME_COLOR[v]))
            if v in (15, -5):
                style.append(("FONT", (col, i), (col, i), "Helvetica-Bold", 8))
    t.setStyle(TableStyle(style))
    return t


# ---------- player line table ----------
def _player_table(team, styles, width):
    rows = [["PLAYER", "PTS", "TOSSUP OUTCOME DISTRIBUTION"]]
    players = {}
    for data in team:
        if data[0] in players.keys():
            players[data[0]].append([data[1], data[2]])
        else:
            players[data[0]] = [[data[1], data[2]]]
    categories = ["lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash"]
    max_tuh = 0
    for p in players:
        point_distr = {
            "powers": sum([players[p][index][1][0] if players[p][index][0] in categories else 0 for index in range(len(players[p]))]),
            "tens": sum([players[p][index][1][1] if players[p][index][0] in categories else 0 for index in range(len(players[p]))]),
            "negs": sum([players[p][index][1][2] if players[p][index][0] in categories else 0 for index in range(len(players[p]))]),
            "tuh": sum([players[p][index][1][3] if players[p][index][0] in categories else 0 for index in range(len(players[p]))])  
        }
        if point_distr["tuh"] > max_tuh:
            max_tuh = point_distr["tuh"]
    
    for p in players:
        point_distr = {
            "powers": sum([players[p][index][1][0] if players[p][index][0] in categories else 0 for index in range(len(players[p]))]),
            "tens": sum([players[p][index][1][1] if players[p][index][0] in categories else 0 for index in range(len(players[p]))]),
            "negs": sum([players[p][index][1][2] if players[p][index][0] in categories else 0 for index in range(len(players[p]))]),
            "tuh": sum([players[p][index][1][3] if players[p][index][0] in categories else 0 for index in range(len(players[p]))])  
        }
        segs = [(point_distr["powers"], POWER), (point_distr["tens"], GET),
                (point_distr["negs"], NEG), (max_tuh - (point_distr["powers"] + point_distr["tens"] + point_distr["negs"]), NEUTRAL)]
        name = Paragraph(
            f"<b>{get_names()[p]}</b><br/>",
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


def _team_block(team, styles, width):
    return [
        Spacer(1, 4),
        _player_table(team, styles, width),
        Spacer(1, 10),
    ]


# ---------- bonus conversion (match report) ----------
def _bonus_table(bonus_data, styles, width):
    """Bonus conversion line for both teams: answered / heard / conversion / PP3BH.

    bonus_data: {"a": [answered, heard], "b": [answered, heard]}
    """
    rows = [["TEAM", "ANSWERED", "HEARD", "CONVERSION", "PP3BH", "RATE"]]
    for team, label in (("a", "Team A"), ("b", "Team B")):
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
    teamA = []
    teamB = []

    for i in range(len(rows)):
        rows[i]["data"] = json.loads(rows[i]["data"])
        if rows[i]["date"] == date:
            game_data = rows[i]["data"]
            break

    game_data["player_data"].sort(key = lambda x: x["question_num"])

    categories = ["lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash"]

    for i in game_data["player_data"]:
        if not i["question_num"] in round_data.keys():
            round_data[i["question_num"]] = {"a": round_data[i["question_num"] - 1]["a"] if i["question_num"] - 1 in round_data.keys() else 0, "b": round_data[i["question_num"] - 1]["b"] if i["question_num"] - 1 in round_data.keys() else 0}
        team = i["team"]
        if i["question_data"][1] in categories:
            round_data[i["question_num"]][team] += 15 * i["question_data"][2][0]
            round_data[i["question_num"]][team] += 10 * i["question_data"][2][1]
            round_data[i["question_num"]][team] -= 5 * i["question_data"][2][2]
        if i["question_data"][1] == "bonus_ans":
            round_data[i["question_num"]][team] += 10
            bonus_data[team][0] += 1
        if i["question_data"][1] == "lightning":
            round_data[i["question_num"]][team] += 10 * i["question_data"][2][0]
            round_data[i["question_num"]][team] -= 10 * i["question_data"][2][1]
        if i["question_data"][1] == "bonus_heard":
            bonus_data[team][1] += 1

    if not game_data:
        return None

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

    # player stats
    #story.append(Paragraph("§ 01 &nbsp; Player lines", styles["h2"]))
    #story.append(Spacer(1, 8))
    story.append(Paragraph("T E A M &nbsp; A", styles["eyebrow"]))
    story.append(Spacer(1, 4))
    story += _team_block(teamA, styles, W)
    story.append(HLine(W, INK, 1.2))
    story.append(Spacer(1, 8))
    story.append(Paragraph("T E A M &nbsp; B", styles["eyebrow"]))
    story.append(Spacer(1, 4))
    story += _team_block(teamB, styles, W)
    story.append(HLine(W, INK, 1.2))
    story.append(Spacer(1, 8))

    # bonus conversion (both teams)
    story.append(Paragraph("B O N U S &nbsp; C O N V E R S I O N", styles["eyebrow"]))
    story.append(Spacer(1, 4))
    story.append(_bonus_table(bonus_data, styles, W))
    story.append(Spacer(1, 12))

    story.append(_running_score_chart(round_data, W))

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
    rows = [["CATEGORY", "P%", "ACCURACY", "TUH", "DISTRUBITION", "PTS"]] + rows
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
                last_name TEXT NOT NULL,
                tuh INTEGER DEFAULT 0,
                powers INTEGER DEFAULT 0,
                tens INTEGER DEFAULT 0,
                negs INTEGER DEFAULT 0,
                lit TEXT NOT NULL,
                history TEXT NOT NULL,
                science TEXT NOT NULL,
                fine_arts TEXT NOT NULL,
                geography TEXT NOT NULL,
                current_events TEXT NOT NULL,
                rmpss TEXT NOT NULL,
                trash TEXT NOT NULL,
                lightning TEXT NOT NULL,
                bonus_ans INTEGER DEFAULT 0,
                bonus_heard INTEGER DEFAULT 0
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
        _stat_tile("PP20TUH", f"{((point_distr["powers"] * 15 + point_distr["tens"] * 10 + -5 * point_distr["negs"]) / (point_distr["tuh"] if point_distr["tuh"] > 0 else 1) * 20):.1f}", styles, W / 6),
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
        _stat_tile("CONVERSION", f"{master_data_list["bonus_ans"] / master_data_list["bonus_heard"] * 100 if master_data_list["bonus_heard"] > 0 else 0:.1f}" + "%", styles, W / 4),
        _stat_tile("PP3BH", f"{master_data_list["bonus_ans"] / master_data_list["bonus_heard"] * 30 if master_data_list["bonus_heard"] > 0 else 0:.1f}", styles, W / 4)
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
        _stat_tile("CONVERSION", f"{master_data_list["lightning"][0] / master_data_list["lightning"][2] * 100 if master_data_list["lightning"][2] > 0 else 0:.1f}" + "%", styles, W / 5)
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


# ---------- demo / self-test ----------
if __name__ == "__main__":
    # Sample data derived from design reference
    rounds = [
        (1,"LITERATURE","Virginia Woolf",15,0,"20/30",35,0),
        (2,"HISTORY","Treaty of Westphalia",0,10,"30/30",35,40),
        (3,"SCIENCE","Enzyme kinetics",10,-5,"20/30",65,35),
        (4,"FINE ARTS","Caravaggio",0,0,"—",65,35),
        (5,"GEOGRAPHY","Caspian basin",15,0,"10/30",90,35),
        (6,"LITERATURE","Borges",-5,10,"20/30",85,65),
        (7,"MATH","Galois theory",0,15,"30/30",85,110),
        (8,"HISTORY","Meiji Restoration",10,0,"20/30",115,110),
        (9,"SCIENCE","Mitochondria",10,0,"30/30",155,110),
        (10,"POP CULTURE","Kurosawa films",0,10,"10/30",155,130),
        (11,"LITERATURE","Toni Morrison",15,-5,"20/30",190,125),
        (12,"MYTH","Norse cosmology",0,10,"20/30",190,155),
        (13,"SCIENCE","Titration",10,0,"10/30",210,155),
        (14,"HISTORY","Ottoman fall",0,10,"20/30",210,185),
        (15,"FINE ARTS","Debussy",10,0,"20/30",240,185),
        (16,"LITERATURE","Chekhov",15,0,"30/30",285,185),
        (17,"MATH","Topology",-5,0,"—",280,185),
        (18,"HISTORY","Deng Xiaoping",0,15,"20/30",280,220),
        (19,"GEOGRAPHY","Andean watersheds",10,0,"20/30",310,220),
        (20,"SCIENCE","Redshift",-5,10,"10/30",305,240),
    ]
    round_data = [
        {"tu": r[0], "category": r[1], "subject": r[2],
         "a_buzz": r[3], "b_buzz": r[4], "bonus": r[5],
         "a_total": r[6], "b_total": r[7], "margin": r[6] - r[7],
         "a_name": "Westbrook", "b_name": "Hartfield"}
        for r in rounds
    ]
    match_data = {
        "match_no": "0428", "date": "Saturday, April 18, 2026",
        "venue": "Room 211", "moderator": "L. Suárez",
        "team_a": {
            "name": "Stanton", "seed": 3, "record": "11–2",
            "nickname": "The Lanterns", "score": 305, "captain": "M. Okafor",
            "players": [
                {"name": "M. Okafor", "class": "Sr.", "points": 85,
                 "powers": 4, "gets": 3, "negs": 1, "no_buzz": 12,
                 "top_cats": [("LITERATURE", 4), ("HISTORY", 2), ("SCIENCE", 1)]},
                {"name": "J. Halvorsen", "class": "Jr.", "points": 50,
                 "powers": 2, "gets": 2, "negs": 0, "no_buzz": 16,
                 "top_cats": [("SCIENCE", 3), ("MATH", 1)]},
                {"name": "P. Aranda", "class": "So.", "points": 30,
                 "powers": 0, "gets": 2, "negs": 0, "no_buzz": 18,
                 "top_cats": [("FINE ARTS", 2), ("GEOGRAPHY", 1)]},
                {"name": "R. Chen", "class": "Fr.", "points": 25,
                 "powers": 0, "gets": 0, "negs": 0, "no_buzz": 20,
                 "top_cats": [("POP CULTURE", 1), ("MYTH", 1)]},
            ],
        },
        "team_b": {
            "name": "Hartfield College", "seed": 6, "record": "10–3",
            "nickname": "The Scholars", "score": 240, "captain": "D. Vitale",
            "players": [
                {"name": "D. Vitale", "class": "Sr.", "points": 55,
                 "powers": 3, "gets": 2, "negs": 2, "no_buzz": 13,
                 "top_cats": [("HISTORY", 3), ("LITERATURE", 2)]},
                {"name": "S. Park", "class": "Sr.", "points": 55,
                 "powers": 2, "gets": 3, "negs": 0, "no_buzz": 15,
                 "top_cats": [("SCIENCE", 3), ("MATH", 2)]},
                {"name": "A. Reyes-Linde", "class": "Jr.", "points": 25,
                 "powers": 0, "gets": 1, "negs": 0, "no_buzz": 19,
                 "top_cats": [("FINE ARTS", 1), ("MYTH", 1)]},
                {"name": "K. Brzezinski", "class": "So.", "points": 10,
                 "powers": 0, "gets": 0, "negs": 0, "no_buzz": 20,
                 "top_cats": [("POP CULTURE", 1)]},
            ],
        },
        "rounds": round_data,
    }

    player_data = {
        "match_no": "0428", "date": "Saturday, April 18, 2026",
        "venue": "Room 211",
        "player": {"name": "M. Okafor", "class": "Sr.",
                   "team": "Westbrook Academy",
                   "nickname": "The Lanterns", "captain": True},
        "totals": {"points": 85, "powers": 4, "gets": 3, "negs": 1,
                   "no_buzz": 12, "ppg": 21.3, "buzz_rate_pct": 40},
        "categories": [
            {"name": "Literature", "n": 4, "pct": 100, "points": 60},
            {"name": "History", "n": 4, "pct": 50, "points": 20},
            {"name": "Science", "n": 4, "pct": 25, "points": 10},
            {"name": "Geography", "n": 2, "pct": 50, "points": 15},
            {"name": "Fine Arts", "n": 2, "pct": 0, "points": 0},
            {"name": "Math", "n": 2, "pct": 0, "points": -5},
            {"name": "Myth", "n": 1, "pct": 0, "points": 0},
            {"name": "Pop Culture", "n": 1, "pct": 0, "points": 0},
        ],
        "recent_matches": [
            {"opp": "Hartfield College", "score": "305–240", "pts": 85, "powers": 4},
            {"opp": "Ridgemont Prep", "score": "280–195", "pts": 70, "powers": 3},
            {"opp": "Ashford Latin", "score": "320–275", "pts": 65, "powers": 2},
        ],
    }

    generate_match_report('May 05, 2026, 02:00 PM', "match_report.pdf")
    #generate_player_report("ethanf", ['May 02, 2026, 06:17 PM', 'May 02, 2026, 07:32 AM'], "player_report.pdf")
    print("OK")