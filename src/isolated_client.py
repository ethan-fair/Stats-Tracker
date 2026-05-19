import os
import sqlite3
import json
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))

#Declaration of colors
RED = "\033[1;31m"
GREEN = "\033[32m"
BLUE = "\033[1;34m"
RESET = "\033[0m"

def questionTracker(rows, tossups, lightnings, teamA, teamB):
    score = {"a": 0, "b": 0}
    tossup = 0
    while tossup < tossups:
        tossup += 1
        category = ""
        while True:
            print(GREEN + "Tossup " + str(tossup) + RESET + ": ")
            print(f"Enter {GREEN}category{RESET} (number): ")
            print(f"\t{RED}1.{RESET} Literature")
            print(f"\t{RED}2.{RESET} History")
            print(f"\t{RED}3.{RESET} Science")
            print(f"\t{RED}4.{RESET} Fine Arts")
            print(f"\t{RED}5.{RESET} Geography")
            print(f"\t{RED}6.{RESET} Current Events")
            print(f"\t{RED}7.{RESET} Religion, Mythology, Politics, Social Science (RMPSS)")  
            print(f"\t{RED}8.{RESET} Trash / Pop Culture")
            print(f"\t{RED}9.{RESET} Substitutions")
            catNum = input("Selection: ")
            valid = False
            try:
                catNum = int(catNum)
                if catNum > 0 and catNum <= 9:
                    valid = True
            except:
                pass
            if valid:
                match catNum:
                    case 1:
                        category = "lit"
                    case 2:
                        category = "history"
                    case 3:
                        category = "science"
                    case 4:
                        category = "fine_arts"
                    case 5:
                        category = "geography"
                    case 6:
                        category = "current_events"
                    case 7:
                        category = "rmpss"
                    case 8:
                        category = "trash"
                    case 9:
                        category = "subs"
                break
            else:
                print("That is not a valid input")
                continue
        if category == "subs":
            tossup -= 1
            while True:
                name_list = {}
                all_users = []
                for player in rows:
                    all_users.append(player["username"])
                    name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"] + RESET
                playerId = ""
                team = ""
                index = -1
                invalid_input = False
                player = input(f"{GREEN}Input{RESET} player (team & seat or player ID) to be subbed {GREEN}OUT{RESET}, or enter \"c\" to cancel: ").lower()
                if player == "c":
                    break
                if len(player) == 2:
                    if (player[:1] == "a"):
                        try:
                            playerId = teamA[int(player[1:]) - 1]
                        except:
                            invalid_input = True
                    elif (player[1:] == "a"):
                        try:
                            playerId = teamA[int(player[:1]) - 1]
                        except:
                            invalid_input = True
                    elif (player[:1] == "b"):
                        try:
                            playerId = teamB[int(player[1:]) - 1]
                        except:
                            invalid_input = True
                    elif (player[1:] == "b"):
                        try:
                            playerId = teamB[int(player[:1]) - 1]
                        except:
                            invalid_input = True
                else:
                    if player in teamA or player in teamB:
                        playerId = player
                    else:
                        invalid_input = True
                if invalid_input:
                    print("That is not a valid player.")
                    continue
                confirm = input(f"{GREEN}Confirm{RESET} that the player being subbed out is " + name_list[playerId] + ": ").lower()
                if confirm != "y":
                    continue
                if playerId in teamA:
                    team = "a"
                    index = teamA.index(playerId)
                elif playerId in teamB:
                    team = "b"
                    index = teamB.index(playerId)
                while True:
                    id = input(f"Enter user ID to {GREEN}replace{RESET} " + name_list[playerId] + ": ")
                    if id in teamA or id in teamB:
                        print("That player is already in play.")
                        continue
                    if id in all_users:
                        confirm = input(f"{GREEN}Confirm{RESET} that the player being subbed in is " + name_list[id] + " (y or n): ")
                        if confirm.lower() == "y":
                            teamA[index] = id
                            break
                        else:
                            continue
                    elif len(id) >= 3:
                        choice = input(f"Player not found in database. {GREEN}Add{RESET} a player with this username? (y or n): ")
                        if choice.lower() == "y":
                            first_name = input(f"Enter the player's {GREEN}first name{RESET}: ")
                            last_name = input(f"Enter the player's {GREEN}last name{RESET}: ")
                            rows.append({"username": id, "first_name": first_name, "last_name": last_name, "tuh": 0, "powers": 0, "tens": 0, "negs": 0, "lit": [0, 0], "history": [0, 0], "science": [0, 0], "fine_arts": [0, 0], "geography": [0, 0], "current_events": [0, 0], "rmpss": [0, 0], "trash": [0, 0], "lightning": [0, 0]})
                            teamA[index] = id
                            all_users.append(id)
                            name_list[id] = BLUE + first_name + " " + last_name + RESET
                            writeToDatabase()
                            break
                        else:
                            continue
                    elif len(id) < 3:
                        print("Usernames must be 3 characters or longer.")
                        continue
                    
                if team == "a":
                    teamA[index] = id
                elif team == "b":
                    teamB[index] = id
                print(name_list[playerId] + " has been replaced by " + name_list[id] + ".")
                
        else:
            team_a_answer = False
            team_b_answer = False
            bonus = True
            scoreToAdd = {"a": 0, "b": 0}
            while True:
                name_list = {}
                all_users = []
                for player in rows:
                    all_users.append(player["username"])
                    name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"] + RESET
                playerId = ""
                invalid_input = False
                return_with_neg_error = False
                player = input("Player (team & seat or player ID): ").lower()
                if len(player) == 2:
                    if (player[:1] == "a"):
                        try:
                            playerId = teamA[int(player[1:]) - 1]
                            team = "a"
                            if team_a_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    elif (player[1:] == "a"):
                        try:
                            playerId = teamA[int(player[:1]) - 1]
                            team = "a"
                            if team_a_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    elif (player[:1] == "b"):
                        try:
                            playerId = teamB[int(player[1:]) - 1]
                            team = "b"
                            if team_b_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    elif (player[1:] == "b"):
                        try:
                            playerId = teamB[int(player[:1]) - 1]
                            team = "b"
                            if team_a_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    if input(f"{GREEN}Confirm{RESET} that the player is " + name_list[playerId] + " (y or n): ").lower() != "y":
                        continue
                elif player == "pass":
                    print("No player answered.")
                    bonus = False
                    break
                else:
                    if player in teamA:
                        playerId = player
                        team = "a"
                        if team_a_answer:
                            return_with_neg_error = True
                    elif player in teamB:
                        playerId = player
                        team = "b"
                        if team_b_answer:
                            return_with_neg_error = True
                    else:
                        invalid_input = True
                if invalid_input:
                    print("That is not a valid player.")
                    continue
                if return_with_neg_error:
                    print(f"A player on {BLUE}team " + team.upper() + RESET + " has already answered.")
                    continue
                answerType = input(f"{GREEN}Power{RESET}, {GREEN}ten{RESET}, {GREEN}neg{RESET}, or {GREEN}zero{RESET} (1, 2, 3, or 4): ").lower()
                if answerType == "power" or answerType == "1" or answerType == "15":
                    finalType = 1
                elif answerType == "ten" or answerType == "2" or answerType == "10":
                    finalType = 2
                elif answerType == "neg" or answerType == "3" or answerType == "-5":
                    finalType = 3
                elif answerType == "zero" or answerType == "4" or answerType == "0":
                    finalType = 4
                for i, dict in enumerate(rows):
                    if dict["username"] == playerId:
                        if finalType == 1:
                            rows[i]["powers"] += 1
                            scoreToAdd[team] += 15
                        elif finalType == 2:
                            rows[i]["tens"] += 1
                            scoreToAdd[team] += 10
                        elif finalType == 3:
                            rows[i]["negs"] += 1
                            scoreToAdd[team] -= 5
                            if playerId in teamA:
                                team_a_answer = True
                            elif playerId in teamB:
                                team_b_answer = True
                        elif finalType == 4:
                            if playerId in teamA:
                                team_a_answer = True
                            elif playerId in teamB:
                                team_b_answer = True
                        writeToDatabase()
                        if finalType != 3 and finalType != 4:
                            if isinstance(rows[i][category], str):
                                rows[i][category] = json.loads(rows[i][category])
                            rows[i][category][0] = int(rows[i][category][0])
                            rows[i][category][0] += 1
                            writeToDatabase()
                if team_a_answer and team_b_answer:
                    bonus = False
                    break
                if finalType == 1 or finalType == 2 or (team_a_answer and team_b_answer):
                    break
            for i, dict in enumerate(rows):
                if dict["username"] in teamA or dict["username"] in teamB:
                    if isinstance(rows[i][category], str):
                        rows[i][category] = json.loads(rows[i][category])
                    rows[i]["tuh"] = int(rows[i]["tuh"])
                    rows[i][category][1] = int(rows[i][category][1])
                    rows[i][category][1] += 1
                    rows[i]["tuh"] += 1
                    writeToDatabase()
            if bonus:
                for i in range(3):
                    while True:
                        print(f"{GREEN}Bonus " + str(i + 1) + RESET + f" for {GREEN}team " + team.upper() + RESET + ":")
                        choice = input(f"{GREEN}Correct{RESET}, {GREEN}incorrect{RESET}, or {GREEN}bounceback{RESET} (c, i, bb): ").lower()
                        if choice == "c":
                            scoreToAdd[team] += 10
                            break
                        elif choice == "bb":
                            if team == "a":
                                scoreAdd = "b"
                            elif team == "b":
                                scoreAdd = "a"
                            scoreToAdd[scoreAdd] += 5
                            break
                        elif choice == "i":
                            break
                        else:
                            print("That is not a valid input.")
            for key, value in scoreToAdd.items():
                score[key] += value
            if i < tossups - 1:
                print("Score: " + BLUE + str(score["a"]) + " - " + str(score["b"]) + RESET)
            elif lightnings > 0:
                print("Score: " + BLUE + str(score["a"]) + " - " + str(score["b"]) + RESET)
            time.sleep(2)
    writeToDatabase()
    while True:
        if lightnings == 0:
            break
        name_list = {}
        all_users = []
        for player in rows:
            all_users.append(player["username"])
            name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"] + RESET
        playerId = ""
        team = ""
        index = -1
        invalid_input = False
        player = input(f"{GREEN}Input{RESET} player (team & seat or player ID) to be subbed {GREEN}OUT{RESET}, or enter \"c\" to cancel: ").lower()
        if player == "c":
            break
        if len(player) == 2:
            if (player[:1] == "a"):
                try:
                    playerId = teamA[int(player[1:]) - 1]
                except:
                    invalid_input = True
            elif (player[1:] == "a"):
                try:
                    playerId = teamA[int(player[:1]) - 1]
                except:
                    invalid_input = True
            elif (player[:1] == "b"):
                try:
                    playerId = teamB[int(player[1:]) - 1]
                except:
                    invalid_input = True
            elif (player[1:] == "b"):
                try:
                    playerId = teamB[int(player[:1]) - 1]
                except:
                    invalid_input = True
        else:
            if player in teamA or player in teamB:
                playerId = player
            else:
                invalid_input = True
        if invalid_input:
            print("That is not a valid player.")
            continue
        confirm = input(f"{GREEN}Confirm{RESET} that the player being subbed out is " + name_list[playerId] + ": ").lower()
        if confirm != "y":
            continue
        if playerId in teamA:
            team = "a"
            index = teamA.index(playerId)
        elif playerId in teamB:
            team = "b"
            index = teamB.index(playerId)
        while True:
            id = input(f"Enter user ID to {GREEN}replace{RESET} " + name_list[playerId] + ": ")
            if id in teamA or id in teamB:
                print("That player is already in play.")
                continue
            if id in all_users:
                confirm = input(f"Confirm that the player is " + name_list[id] + " (y or n): ")
                if confirm.lower() == "y":
                    teamA[index] = id
                    break
                else:
                    continue
            elif len(id) >= 3:
                choice = input(f"Player not found in database. {GREEN}Add{RESET} a player with this username? (y or n): ")
                if choice.lower() == "y":
                    first_name = input(f"Enter the player's {GREEN}first name{RESET}: ")
                    last_name = input(f"Enter the player's {GREEN}last name{RESET}: ")
                    rows.append({"username": id, "first_name": first_name, "last_name": last_name, "tuh": 0, "powers": 0, "tens": 0, "negs": 0, "lit": [0, 0], "history": [0, 0], "science": [0, 0], "fine_arts": [0, 0], "geography": [0, 0], "current_events": [0, 0], "rmpss": [0, 0], "trash": [0, 0], "lightning": [0, 0]})
                    teamA[index] = id
                    writeToDatabase()
                    all_users.append(id)
                    name_list[id] = BLUE + first_name + " " + last_name + RESET
                    break
                else:
                    continue
            elif len(id) < 3:
                print("Usernames must be 3 characters or longer.")
                continue
            
        if team == "a":
            teamA[index] = id
        elif team == "b":
            teamB[index] = id
        print(name_list[playerId] + f" has been {GREEN}replaced{RESET} by " + name_list[id] + ".")
    writeToDatabase()
    for i in range(lightnings):
        writeToDatabase()
        print(GREEN + "Lightning " + str(i + 1) + RESET + ":")
        while True:
            name_list = {}
            all_users = []
            for player in rows:
                all_users.append(player["username"])
                name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"] + RESET
            playerId = ""
            invalid_input = False
            player = input(f"{GREEN}Player{RESET} (team & seat or player ID): ").lower()
            do_pass = False
            if len(player) == 2:
                if (player[:1] == "a"):
                    try:
                        playerId = teamA[int(player[1:]) - 1]
                        team = "a"
                    except:
                        invalid_input = True
                elif (player[1:] == "a"):
                    try:
                        playerId = teamA[int(player[:1]) - 1]
                        team = "a"
                    except:
                        invalid_input = True
                elif (player[:1] == "b"):
                    try:
                        playerId = teamB[int(player[1:]) - 1]
                        team = "b"
                    except:
                        invalid_input = True
                elif (player[1:] == "b"):
                    try:
                        playerId = teamB[int(player[:1]) - 1]
                        team = "b"
                    except:
                        invalid_input = True
            elif player == "pass":
                print("No player answered, going to next question.")
                do_pass = True
                break
            else:
                if player in teamA:
                    playerId = player
                    team = "a"
                elif player in teamB:
                    playerId = player
                    team = "b"
                else:
                    invalid_input = True
            if invalid_input:
                print("That is not a valid player.")
                continue
            break
        for num, dict in enumerate(rows):
            if dict["username"] in teamA or dict["username"] in teamB:
                if isinstance(rows[num]["lightning"], str):
                    rows[num]["lightning"] = json.loads(rows[num]["lightning"])
                rows[num]["lightning"][1] = int(rows[num]["lightning"][1])
                rows[num]["lightning"][1] += 1
                writeToDatabase()
        if do_pass:
            writeToDatabase()
            pass
        else:
            while True:
                up_or_down = input("+10 or -10: ").lower()
                up_or_down = "".join(up_or_down.split())
                if up_or_down == "+10" or up_or_down == "+" or up_or_down == "plus":
                    if team == "a":
                        score["a"] += 10
                    elif team == "b":
                        score["b"] += 10
                    for num, dict in enumerate(rows):
                        if dict["username"] == playerId:
                            if isinstance(rows[num]["lightning"], str):
                                rows[num]["lightning"] = json.loads(rows[num]["lightning"])
                            rows[num]["lightning"][0] = int(rows[num]["lightning"][0])
                            rows[num]["lightning"][0] += 1
                            writeToDatabase()
                elif up_or_down == "-10" or up_or_down == "-" or up_or_down == "neg":
                    if team == "a":
                        score["a"] -= 10
                    elif team == "b":
                        score["b"] -= 10
                else:
                    print("That is not a valid input.")
                    pass
                break
        writeToDatabase()
        if i < lightnings - 1:
            print("Score: " + BLUE + str(score["a"]) + " - " + str(score["b"]) + RESET)
            time.sleep(2)
    print("Final Score: " + BLUE + str(score["a"]) + " - " + str(score["b"]) + RESET)
    time.sleep(2)
    writeToDatabase()
def writeToDatabase():
    global rows
    conn = sqlite3.connect("players.db")
    c = conn.cursor()
    for player in rows:
        for key, value in player.items():
            if type(value) is list:
                player[key] = json.dumps(value)
        c.execute("""
        INSERT INTO players (username, first_name, last_name, tuh, powers, tens, negs, lit, history, science, fine_arts, geography, current_events, rmpss, trash, lightning)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            tuh=excluded.tuh,
            powers=excluded.powers,
            tens=excluded.tens,
            negs=excluded.negs,
            lit=excluded.lit,
            history=excluded.history,
            science=excluded.science,
            fine_arts=excluded.fine_arts,
            geography=excluded.geography,
            current_events=excluded.current_events,
            rmpss=excluded.rmpss,
            trash=excluded.trash,
            lightning=excluded.lightning
        """, (
            player["username"],
            player["first_name"],
            player["last_name"],
            player["tuh"],
            player["powers"],
            player["tens"],
            player["negs"],
            player["lit"],
            player["history"],
            player["science"],
            player["fine_arts"],
            player["geography"],
            player["current_events"],
            player["rmpss"],
            player["trash"],
            player["lightning"]
        ))
    conn.commit()
    conn.close()
        
rows = []
fieldnames = ["username", "first_name", "last_name", "tuh", "powers", "tens", "negs", "lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash", "lightning"]
scriptRunning = True

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
            lightning TEXT NOT NULL
        )
        """)
    conn.commit()

    cursor.execute("SELECT * FROM players")
    result = cursor.fetchall()

rows = [dict(row) for row in result]
conn.close()

for i, row in enumerate(rows):
    for key, value in row.items():
        if type(value) is str and (key != "username" and key != "first_name" and key != "last_name"):
            rows[i][key] = json.loads(value)
            rows[i][key][0] = int(rows[i][key][0])
            rows[i][key][1] = int(rows[i][key][1])

while scriptRunning:
    print("Select a command: ")
    print(f"\t{RED}1.{RESET} Start Game")
    print(f"\t{RED}2.{RESET} Stats Viewer")
    print(f"\t{RED}3.{RESET} Close")
    while True:
        selection = input("Selection: ")
        if selection == "1":
            while True:
                tossups = input(f"Enter number of {GREEN}tossups{RESET}: ")
                try:
                    tossups = int(tossups)
                    break
                except:
                    print("That is not a valid input.")
            while True:
                lightnings = input(f"Enter number of {GREEN}lightnings{RESET}: ")
                try:
                    lightnings = int(lightnings)
                    break
                except:
                    print("That is not a valid input.")
            while True:
                players = input(f"Enter number of {GREEN}players per team{RESET}: ")
                try:
                    players = int(players)
                    break
                except:
                    print("That is not a valid input.")
            teamA = [""] * players
            teamB = [""] * players
            all_users = []
            name_list = {}
            for player in rows:
                all_users.append(player["username"])
                name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"] + RESET
            for i in range(players):
                while True:
                    id = input(f"Enter user ID for {GREEN}seat " + str(i + 1) + RESET + f" on {GREEN}team A{RESET}: ")
                    if id in all_users:
                        confirm = input("Confirm that the player is " + name_list[id] + " (y or n): ")
                        if confirm.lower() == "y":
                            teamA[i] = id
                            break
                        else:
                            continue
                    elif len(id) >= 3:
                        choice = input("Player not found in database. Add a player with this username? (y or n): ")
                        if choice.lower() == "y":
                            first_name = input(f"Enter the player's {GREEN}first name{RESET}: ")
                            last_name = input(f"Enter the player's {GREEN}last name{RESET}: ")
                            rows.append({"username": id, "first_name": first_name, "last_name": last_name, "tuh": 0, "powers": 0, "tens": 0, "negs": 0, "lit": [0, 0], "history": [0, 0], "science": [0, 0], "fine_arts": [0, 0], "geography": [0, 0], "current_events": [0, 0], "rmpss": [0, 0], "trash": [0, 0], "lightning": [0, 0]})
                            teamA[i] = id
                            writeToDatabase()
                            break
                        else:
                            continue
                    elif len(id) < 3:
                        print("Usernames must be 3 characters or longer.")
                        continue
            for i in range(players):
                while True:
                    id = input(f"Enter user ID for {GREEN}seat " + str(i + 1) + RESET + f" on {GREEN}team B{RESET}: ")
                    if id in all_users:
                        confirm = input("Confirm that the player is " + name_list[id] + " (y or n): ")
                        if confirm.lower() == "y":
                            teamB[i] = id
                            break
                        else:
                            continue
                    elif len(id) >= 3:
                        choice = input("Player not found in database. Add a player with this username? (y or n): ")
                        if choice.lower() == "y":
                            first_name = input("Enter the player's first name: ")
                            last_name = input("Enter the player's last name: ")
                            rows.append({"username": id, "first_name": first_name, "last_name": last_name, "tuh": 0, "powers": 0, "tens": 0, "negs": 0, "lit": [0, 0], "history": [0, 0], "science": [0, 0], "fine_arts": [0, 0], "geography": [0, 0], "current_events": [0, 0], "rmpss": [0, 0], "trash": [0, 0], "lightning": [0, 0]})
                            teamB[i] = id
                            writeToDatabase()
                            break
                        else:
                            continue
                    elif len(id) < 3:
                        print("Usernames must be 3 characters or longer.")
                        continue
            writeToDatabase()
            questionTracker(rows, tossups, lightnings, teamA, teamB)
            input(f"Press {GREEN}enter{RESET} to continue.")
            break
        elif selection == "2":
            for row in rows:
                print(row)
                print("")
            
            all_users = []
            name_list = {}
            for player in range(len(rows)):
                all_users.append(rows[player]["username"])
                name_list[rows[player]["username"]] = BLUE + rows[player]["first_name"] + " " + rows[player]["last_name"] + RESET
            while True:
                id = input(f"Enter user ID to {GREEN}pull data{RESET}: ")
                if id in all_users:
                    break
                else:
                    print("That is not a valid user ID.")
                    continue
            for num in range(len(rows)): 
                for key in rows[num].keys():
                    if isinstance(rows[num][key], str) and key != "first_name" and key == "last_name" and key == "username":
                        rows[num][key] = json.loads(rows[num][key])
            playerId = id
            id = all_users.index(id)
            print_list = [
                "Data for " + name_list[playerId] + ":",
                "    " + RED + str(rows[id]["powers"]) + "/" + str(rows[id]["tens"]) + "/" + str(rows[id]["negs"]) + RESET + " with " + str(rows[id]["tuh"]) + " tossups heard." + (" (" + str(round((rows[id]["powers"] + rows[id]["tens"]) / rows[id]["tuh"] * 10000) / 100) + "%)" if rows[id]["tuh"] > 0 else ""),
                "\t" + GREEN + "Literature" + RESET + ": " + (RED + str(round(rows[id]["lit"][0] / rows[id]["lit"][1] * 10000) / 100) + f"%{RESET} (" + str(rows[id]["lit"][0]) + "/" + str(rows[id]["lit"][1]) + ")" if rows[id]["lit"][1] > 0 else f"{RED}No questions heard{RESET}"),
                "\t" + GREEN + "History" + RESET + ": " + (RED + str(round(rows[id]["history"][0] / rows[id]["history"][1] * 10000) / 100) + f"%{RESET} (" + str(rows[id]["history"][0]) + "/" + str(rows[id]["history"][1]) + ")" if rows[id]["history"][1] > 0 else f"{RED}No questions heard{RESET}"),
                "\t" + GREEN + "Science" + RESET + ": " + (RED + str(round(rows[id]["science"][0] / rows[id]["science"][1] * 10000) / 100) + f"%{RESET} (" + str(rows[id]["science"][0]) + "/" + str(rows[id]["science"][1]) + ")" if rows[id]["science"][1] > 0 else f"{RED}No questions heard{RESET}"),
                "\t" + GREEN + "Fine Arts" + RESET + ": " + (RED + str(round(rows[id]["fine_arts"][0] / rows[id]["fine_arts"][1] * 10000) / 100) + f"%{RESET} (" + str(rows[id]["fine_arts"][0]) + "/" + str(rows[id]["fine_arts"][1]) + ")" if rows[id]["fine_arts"][1] > 0 else f"{RED}No questions heard{RESET}"),
                "\t" + GREEN + "Geography" + RESET + ": " + (RED + str(round(rows[id]["geography"][0] / rows[id]["geography"][1] * 10000) / 100) + f"%{RESET} (" + str(rows[id]["geography"][0]) + "/" + str(rows[id]["geography"][1]) + ")" if rows[id]["geography"][1] > 0 else f"{RED}No questions heard{RESET}"),
                "\t" + GREEN + "Current Events" + RESET + ": " + (RED + str(round(rows[id]["current_events"][0] / rows[id]["current_events"][1] * 10000) / 100) + f"%{RESET} (" + str(rows[id]["current_events"][0]) + "/" + str(rows[id]["current_events"][1]) + ")" if rows[id]["current_events"][1] > 0 else f"{RED}No questions heard{RESET}"),
                "\t" + GREEN + "Religion, Mythology, Politics, Social Science" + RESET + ": " + (RED + str(round(rows[id]["rmpss"][0] / rows[id]["rmpss"][1] * 10000) / 100) + f"%{RESET} (" + str(rows[id]["rmpss"][0]) + "/" + str(rows[id]["rmpss"][1]) + ")" if rows[id]["rmpss"][1] > 0 else f"{RED}No questions heard{RESET}"),
                "\t" + GREEN + "Trash" + RESET + ": " + (RED + str(round(rows[id]["trash"][0] / rows[id]["trash"][1] * 10000) / 100) + f"%{RESET} (" + str(rows[id]["trash"][0]) + "/" + str(rows[id]["trash"][1]) + ")" if rows[id]["trash"][1] > 0 else f"{RED}No questions heard{RESET}"),
                "\t" + GREEN + "Lightning" + RESET + ": " + (RED + str(round(rows[id]["lightning"][0] / rows[id]["lightning"][1] * 10000) / 100) + f"%{RESET} (" + str(rows[id]["lightning"][0]) + "/" + str(rows[id]["lightning"][1]) + ")" if rows[id]["lightning"][1] > 0 else f"{RED}No questions heard{RESET}")
            ]
            for i in print_list:
                print(i)
            input(f"Press {GREEN}enter{RESET} to continue.")
            break
        elif selection == "3":
            scriptRunning = False
            break
        else:
            print("That is not a valid input.")

writeToDatabase()
