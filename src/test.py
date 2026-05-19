categories = ["lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash"]

master_data_list = {"lit": [3, 0, 0, 0], "history": [0, 2, 0, 0], "science": [0, 0, 0, 5], "fine_arts": [0, 0, 0, 0], "geography": [0, 0, 0, 0], "current_events": [0, 0, 0, 0], "rmpss": [0, 0, 0, 0], "trash": [0, 0, 0, 0], "lightning": [1, 0, 0], "bonus_ans": 1, "bonus_heard": 0}

print(sum([(15 * master_data_list[section][0] + 10 * master_data_list[section][1] + -5 * master_data_list[section][3]) if section in categories else 0 for section in master_data_list]))