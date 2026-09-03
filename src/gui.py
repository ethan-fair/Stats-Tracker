import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import sys
import ctypes
import pygame
import socket
import configparser
import threading
import time
import json
from queue import Queue

os.chdir(os.path.dirname(os.path.abspath(__file__)))

running = True
message_queue = Queue()

config = configparser.ConfigParser()
config.read('../config.ini')

if not config.has_section("CONNECTION"):
    print("config.ini does not exist or is incorrectly formatted.")
    running = False
    input("Press enter to continue.")

if running:
    try:
        IP = config["CONNECTION"]["ip"]
        PORT = int(config["CONNECTION"]["port"])
    except:
        print("The IP or port is incorrectly formatted.")
        running = False
        input("Press enter to continue.")

while running:
    session = input("Enter the \033[32msession id\033[0m: ").lower().strip()
    if session == "pass":
        running = False
        break
    client_socket = None
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_socket.settimeout(0.5)
        client_socket.sendto(str("ADSCR" + session).encode(), (IP, PORT))
        data, addr = client_socket.recvfrom(4096)
        data = data.decode("utf-8")
        if data == "pass":
            break
        else:
            print("Session id is invalid.")
    except (socket.timeout, ConnectionResetError):
        print("Error connecting to server.")
        input("Press \033[32menter\033[0m to continue.")
        running = False
        break
    finally:
        if client_socket:
            client_socket.close()
if running:
    state_version = -1
    POLL_INTERVAL = 0.1
else:
    sys.exit(0)

class TextBox():
    def __init__(self, screen, x, y):
        self.screen = screen
        self.x = x
        self.y = y

        self.lines = []

        self.font = pygame.font.Font("../assets/IBMPlexSerif-Regular.ttf", 20)
        self.text_color = (255, 255, 255)

        self.base_width = 200
        self.padding_x = 10
        self.padding_y = 10
        self.line_spacing = -5

        self.current_width = self.base_width
        self.width_speed = 0.2

        self.type_speed = 1

    def add_line(self, text):
        # Coerce to str: a player without a username can produce a non-string
        # (or None) payload, which would otherwise crash font.render().
        new_line = {
            "full": str(text) if text is not None else "",
            "visible": "",
            "progress": 0
        }

        self.lines.insert(0, new_line)
        self.lines = self.lines[:5]

    def sync_lines(self, entries):
        existing = {}
        for line in self.lines:
            if line.get("seq") is not None:
                existing[line["seq"]] = line
        synced = []
        for entry in reversed(entries):
            seq, text = entry[0], entry[1]
            line = existing.get(seq)
            if line is None:
                line = {
                    "seq": seq,
                    "full": str(text) if text is not None else "",
                    "visible": "",
                    "progress": 0
                }
            synced.append(line)
        self.lines = synced[:5]

    def update(self):
        rendered_lines = []
        max_line_width = 0

        for i, line in enumerate(self.lines):
            if i == 0 and line["progress"] < len(line["full"]):
                line["progress"] += self.type_speed
                line["visible"] = line["full"][:line["progress"]]
            else:
                line["visible"] = line["full"]

            surf = self.font.render(line["visible"], True, self.text_color)
            rendered_lines.append(surf)
            max_line_width = max(max_line_width, surf.get_width())

        target_width = max(
            self.base_width,
            max_line_width + self.padding_x * 2
        )

        self.current_width += (target_width - self.current_width) * self.width_speed
        fg_width = int(self.current_width)

        total_height = 0
        heights = []

        for surf in rendered_lines:
            h = surf.get_height()
            heights.append(h)
            total_height += h

        if len(rendered_lines) > 1:
            total_height += self.line_spacing * (len(rendered_lines) - 1)

        fg_height = total_height + self.padding_y * 2

        bg_rect = pygame.Rect(0, 0, fg_width + 6, fg_height + 6)
        bg_rect.midtop = (self.x, self.y)
        if rendered_lines:
            pygame.draw.rect(self.screen, (50, 50, 50), bg_rect)

        fg = pygame.Surface((fg_width, fg_height), pygame.SRCALPHA)
        if rendered_lines:
            pygame.draw.rect(fg, (100, 100, 100), fg.get_rect())

        y = self.padding_y

        for i, surf in enumerate(rendered_lines):
            rect = surf.get_rect()
            rect.centerx = fg_width // 2
            rect.y = y

            fg.blit(surf, rect)

            y += heights[i] + self.line_spacing

        fg_rect = fg.get_rect()
        fg_rect.center = bg_rect.center
        self.screen.blit(fg, fg_rect)

class Counter():
    def __init__ (self, screen, x, y):
        self.x = x
        self.y = y
        self.screen = screen
        self.score = 0
        self.font = pygame.font.Font("../assets/UnicaOne-Regular.ttf", 128)
        self.text_color = (255, 255, 255)
        self.current_width = 195
        self.prev_score = 0
        self.score = 0

        self.anim_progress = 1.0
        self.anim_speed = 0.05 

    def update(self):
        base_width = 195
        base_height = 122
        padding = 10
        overlap = -10

        if self.anim_progress < 1.0:
            self.anim_progress += self.anim_speed
            if self.anim_progress > 1.0:
                self.anim_progress = 1.0

        prev_str = str(self.prev_score)
        curr_str = str(self.score)

        num_digits = max(len(prev_str), len(curr_str))

        prev_str = prev_str.zfill(num_digits)
        curr_str = curr_str.zfill(num_digits)

        digit_width = self.font.size("0")[0]

        if num_digits <= 3:
            target_width = base_width
        else:
            target_width = max(
                base_width,
                digit_width * num_digits + padding * 2 + overlap * (num_digits - 1)
            )

        width_speed = 0.2
        self.current_width += (target_width - self.current_width) * width_speed
        fg_width = int(self.current_width)

        bg_rect = pygame.Rect(0, 0, fg_width + 6, base_height + 6)
        bg_rect.center = (self.x, self.y)
        pygame.draw.rect(self.screen, (50, 50, 50), bg_rect)

        fg = pygame.Surface((fg_width, base_height), pygame.SRCALPHA)
        pygame.draw.rect(fg, (100, 100, 100), fg.get_rect())

        t = self.anim_progress
        t = 1 - (1 - t) ** 3
        offset_y = int(t * self.font.get_height())

        x = fg_width - padding

        for i in range(num_digits - 1, -1, -1):
            prev_digit = prev_str[i]
            curr_digit = curr_str[i]

            prev_len = len(str(self.prev_score))
            curr_len = len(str(self.score))

            if i < num_digits - prev_len:
                prev_digit = None

            if i < num_digits - curr_len:
                curr_digit = None

            if prev_digit is None and curr_digit is None:
                continue

            prev_surface = self.font.render(prev_digit, True, self.text_color) if prev_digit is not None else None
            curr_surface = self.font.render(curr_digit, True, self.text_color) if curr_digit is not None else None

            digit_rect = (prev_surface or curr_surface).get_rect()
            digit_rect.right = x
            center_y = fg.get_height() // 2

            if prev_digit != curr_digit:
                if prev_surface:
                    prev_rect = digit_rect.copy()
                    prev_rect.centery = center_y - offset_y
                    fg.blit(prev_surface, prev_rect)

                if curr_surface:
                    curr_rect = digit_rect.copy()
                    curr_rect.centery = center_y + (self.font.get_height() - offset_y)
                    fg.blit(curr_surface, curr_rect)
            else:
                digit_rect.centery = center_y
                fg.blit(prev_surface, digit_rect)

            x -= digit_rect.width + overlap

        fg_rect = fg.get_rect(center=bg_rect.center)
        self.screen.blit(fg, fg_rect)
    def set_score(self, new_score):
        if new_score != self.score:
            self.prev_score = self.score
            self.score = new_score
            if (new_score < 0) != (self.prev_score < 0):
                self.anim_progress = 1.0
            else:
                self.anim_progress = 0.0
    def add_score(self, amount):
        self.set_score(self.score + amount)

class QuestionWheel():
    """Slot-machine counter for the current question number.

    The numbers sit on a vertical wheel a full panel apart, so only the current
    one rests in the window. Changing the number turns the wheel: the old one
    rolls up out of the panel as the new one rolls in behind it.
    """
    TOSSUP_COLOUR = (255, 255, 255)
    LIGHTNING_COLOUR = (255, 224, 32)

    def __init__(self, screen, x, y):
        self.screen = screen
        self.x = x
        self.y = y
        # The wheel runs over one continuous sequence of positions: 1..tossups
        # are the tossups, then the lightnings follow straight on, so the last
        # tossup's lower neighbour is the first lightning. What each position
        # prints, and its colour, comes from which phase it lands in.
        self.position = 0        # 0 until the first question arrives
        self.prev_position = 0
        self.tossups = 0
        self.lightnings = 0
        self.display = 0.0       # animated wheel position, in whole positions
        self.anim_progress = 1.0
        self.anim_speed = 0.09
        # --- box size: change these two and everything below re-fits itself ---
        self.base_width = 40
        self.height = 60
        self.padding = 4
        self.current_width = self.base_width
        # Largest size of the score counters' face that keeps a two-digit
        # number inside the panel width while leaving vertical room for the
        # neighbours, so the numbers fit whatever box size is set above.
        self.font, _ = self._fit_font()
        # A full panel between consecutive numbers, so only the current one is
        # ever at rest in the window: the number leaving has completely cleared
        # the panel by the time the next settles. Both are on screen only while
        # the wheel is actually turning.
        self.slot = self.height

    def _fit_font(self):
        """Biggest UnicaOne that fits the panel, with its digit ink height."""
        best = None
        for size in range(10, 200):
            font = pygame.font.Font("../assets/UnicaOne-Regular.ttf", size)
            ink = font.render("88", True, (255, 255, 255)).get_bounding_rect()
            if (ink.width > self.base_width - self.padding * 2
                    or ink.height > self.height * 0.45):
                break
            best = (font, ink.height)
        if best is None:        # box too small for even the smallest size
            font = pygame.font.Font("../assets/UnicaOne-Regular.ttf", 10)
            best = (font, font.render("88", True, (255, 255, 255)).get_bounding_rect().height)
        return best

    def set_number(self, n, tossups=0, lightnings=0, phase=None):
        try:
            n = int(n)
            tossups = int(tossups)
            lightnings = int(lightnings)
        except (TypeError, ValueError):
            return
        if n < 1:
            return
        if tossups or lightnings:
            self.tossups, self.lightnings = tossups, lightnings
        # Lightning numbering restarts at 1, so it sits after the tossups on
        # the wheel. Moving from the last tossup to the first lightning is then
        # an ordinary one-step roll rather than a jump back to the start.
        position = self.tossups + n if phase == "lightning" else n
        if self.position < 1:
            # First question: settle straight onto it rather than rolling up
            # from a position the wheel never shows.
            self.position = self.prev_position = position
            self.display = float(position)
            self.anim_progress = 1.0
            return
        if position == self.position:
            return
        self.prev_position = self.position
        self.position = position
        self.anim_progress = 0.0

    def label_for(self, k):
        """A wheel position's printed number and colour, by the phase it's in."""
        if k <= self.tossups:
            return str(k), self.TOSSUP_COLOUR
        return str(k - self.tossups), self.LIGHTNING_COLOUR

    def reset(self):
        self.position = 0
        self.prev_position = 0
        self.tossups = 0
        self.lightnings = 0
        self.display = 0.0
        self.anim_progress = 1.0
        self.current_width = self.base_width

    def update(self):
        if self.position < 1:
            return               # nothing to show until the first question
        if self.anim_progress < 1.0:
            self.anim_progress = min(1.0, self.anim_progress + self.anim_speed)
        t = 1 - (1 - self.anim_progress) ** 3
        self.display = self.prev_position + (self.position - self.prev_position) * t

        # Measure the actual ink, not the advance width, so a number that fits
        # the box does not push it wider than it needs to be.
        widest = max((self.label_for(k)[0]
                      for k in (int(self.display), int(self.display) + 1, self.position)
                      if k >= 1), key=len, default="8")
        ink_width = self.font.render(widest, True, (255, 255, 255)).get_bounding_rect().width
        target_width = max(self.base_width, ink_width + self.padding * 2)
        self.current_width += (target_width - self.current_width) * 0.2
        fg_width = int(self.current_width)

        bg_rect = pygame.Rect(0, 0, fg_width + 6, self.height + 6)
        bg_rect.center = (self.x, self.y)
        pygame.draw.rect(self.screen, (50, 50, 50), bg_rect)

        fg = pygame.Surface((fg_width, self.height), pygame.SRCALPHA)
        pygame.draw.rect(fg, (100, 100, 100), fg.get_rect())

        centre_y = self.height // 2
        first = int(self.display) - 1
        last = self.tossups + self.lightnings
        for k in range(first, first + 4):
            if k < 1:
                continue         # the wheel starts at the first question
            if last and k > last:
                continue         # and stops at the last one of the game
            dy = (k - self.display) * self.slot
            if abs(dy) > self.slot * 1.6:
                continue
            text, colour = self.label_for(k)
            surf = self.font.render(text, True, colour)
            rect = surf.get_rect()
            rect.centerx = fg_width // 2
            rect.centery = int(centre_y + dy)
            fg.blit(surf, rect)

        fg_rect = fg.get_rect(center=bg_rect.center)
        self.screen.blit(fg, fg_rect)

class SeatTracker():
    def __init__(self, screen, x, y, name_list, alignment):
        self.screen = screen
        self.x = x
        self.y = y
        self.number = len(name_list)
        self.name_list = name_list
        self.alignment = alignment
        self.font = pygame.font.Font("../assets/IBMPlexSerif-Regular.ttf", 20)
        self.timer = 0
        self.highlighted = []

    def update(self):
        count = len(self.name_list)
        surface = pygame.Surface((250, 55 * max(count, 1)), pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        highlighted_list = []
        for i in range(len(self.highlighted)):
            if self.highlighted[i][1] > 0:
                highlighted_list.append(self.highlighted[i][0])
                self.highlighted[i][1] -= 1
        self.highlighted = [h for h in self.highlighted if h[1] > 0]

        for i in range(count):
            if (i + 1) not in highlighted_list:
                if self.alignment == "LEFT":
                    pygame.draw.rect(surface, (50, 50, 50), pygame.Rect(0, 55 * i, 50, 50))
                    pygame.draw.rect(surface, (100, 100, 100), pygame.Rect(5, 55 * i + 5, 40, 40))
                if self.alignment == "RIGHT":
                    pygame.draw.rect(surface, (50, 50, 50), pygame.Rect(200, 55 * i, 50, 50))
                    pygame.draw.rect(surface, (100, 100, 100), pygame.Rect(205, 55 * i + 5, 40, 40))
            else:
                if self.alignment == "LEFT":
                    bottom_rect = pygame.Rect(0, 55 * i, 50, 50)
                    pygame.draw.rect(surface, (0, 100, 0), bottom_rect)
                    pygame.draw.rect(surface, (0, 200, 0), pygame.Rect(5, 55 * i + 5, 40, 40))
                    text = self.font.render(self.name_list[i], True, (0, 0, 0))
                    text_rect = text.get_rect()
                    text_rect.midleft = (bottom_rect.right + 10, bottom_rect.centery)
                elif self.alignment == "RIGHT":
                    bottom_rect = pygame.Rect(200, 55 * i, 50, 50)
                    pygame.draw.rect(surface, (0, 100, 0), bottom_rect)
                    pygame.draw.rect(surface, (0, 200, 0), pygame.Rect(205, 55 * i + 5, 40, 40))
                    text = self.font.render(self.name_list[i], True, (0, 0, 0))
                    text_rect = text.get_rect()
                    text_rect.midright = (bottom_rect.left - 10, bottom_rect.centery)
                #pygame.draw.rect(surface, (0, 0, 0), pygame.Rect(text_rect.left - 5, text_rect.top - 5, text_rect.width + 10, text_rect.height + 10), 2)
                surface.blit(text, text_rect)
                
        rect = surface.get_rect()
        if self.alignment == "LEFT":
            rect.midleft = (self.x, self.y)
        elif self.alignment == "RIGHT":
            rect.midright = (self.x, self.y)
        self.screen.blit(surface, rect)


def poll_server():
    global state_version
    while running:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            sock.sendto(("UPDTE" + session + "|" + str(state_version)).encode(), (IP, PORT))
            data, addr = sock.recvfrom(4096)
            msg = data.decode("utf-8")
            if msg.startswith("SNAP|"):
                payload = json.loads(msg.split("|", 1)[1])
                if payload["version"] >= state_version:
                    state_version = payload["version"]
                    message_queue.put(payload)
            elif msg == "CLOSED":
                message_queue.put(msg)
            print(msg)
            sock.close()
        except socket.timeout:
            pass
        except Exception as e:
            print(e)
        time.sleep(POLL_INTERVAL)

threading.Thread(target=poll_server, args=(), daemon=True).start()

pygame.init()
game_width = 1280
game_height = 720
final_screen = pygame.display.set_mode((game_width, game_height), pygame.SCALED | pygame.FULLSCREEN)
screen = pygame.Surface((game_width, game_height))
swap_button = pygame.image.load("../assets/swap.png")
bg = pygame.image.load("../assets/bg.png")
bg = pygame.transform.scale(bg, (1280, 720))
button = pygame.transform.scale(swap_button, (50, 50))
button_rect = button.get_rect(topleft = (615, 500))
clock = pygame.time.Clock()
timer = 0
default_pos = True

teamACounter = Counter(screen, 320, 200)
teamBCounter = Counter(screen, 960, 200)
teamAText = TextBox(screen, 320, 500)
teamBText = TextBox(screen, 960, 500)
teamASeats = SeatTracker(screen, 0, 360, [], "LEFT")
teamBSeats = SeatTracker(screen, 1280, 360, [], "RIGHT")
questionWheel = QuestionWheel(screen, 640, 200)

while running:
    while not message_queue.empty():
        try:
            msg = message_queue.get()
            if msg == "CLOSED":
                print("Client has closed this session.")
                running = False
                continue
            teamACounter.set_score(msg["score"]["a"])
            teamBCounter.set_score(msg["score"]["b"])
            teamASeats.name_list = list(msg["seats"]["a"])
            teamASeats.number = len(teamASeats.name_list)
            teamBSeats.name_list = list(msg["seats"]["b"])
            teamBSeats.number = len(teamBSeats.name_list)
            teamASeats.highlighted = [[h[0], h[1]] for h in msg["highlights"]["a"]]
            teamBSeats.highlighted = [[h[0], h[1]] for h in msg["highlights"]["b"]]
            teamAText.sync_lines(msg["messages"]["a"])
            teamBText.sync_lines(msg["messages"]["b"])
            q = msg["question"]
            if q and q[0]:
                questionWheel.set_number(q[0], q[1], q[2], q[3])
            else:
                questionWheel.reset()
        except Exception:
            pass

    if timer > 0:
        timer -= 1

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False
        if event.type == pygame.MOUSEBUTTONDOWN:
            mouse_position = pygame.mouse.get_pos()
            if button_rect.collidepoint(mouse_position) and timer <= 0:
                timer = 10
                if default_pos:
                    teamACounter.x = 960
                    teamBCounter.x = 320
                    teamAText.x = 960
                    teamBText.x = 320
                    teamASeats.x = 1280
                    teamBSeats.x = 0
                    teamASeats.alignment = "RIGHT"
                    teamBSeats.alignment = "LEFT"
                    default_pos = False
                else:
                    teamACounter.x = 320
                    teamBCounter.x = 960
                    teamAText.x = 320
                    teamBText.x = 960
                    teamASeats.x = 0
                    teamBSeats.x = 1280
                    teamASeats.alignment = "LEFT"
                    teamBSeats.alignment = "RIGHT"
                    default_pos = True

    screen.fill((255, 255, 255))
    pygame.draw.rect(screen, (0, 0, 0), pygame.Rect(638, 20, 4, 460))
    pygame.draw.rect(screen, (0, 0, 0), pygame.Rect(638, 570, 4, 130))
    screen.blit(button, button_rect)
    for widget in (teamACounter, teamBCounter, teamAText, teamBText, teamASeats, teamBSeats, questionWheel):
        try:
            widget.update()
        except Exception as e:
            print("Render error (skipping frame for widget):", e)

    screen_draw = pygame.transform.smoothscale(screen, final_screen.get_size())

    final_screen.blit(screen_draw, (0, 0))

    pygame.display.flip()
    clock.tick(40)
    pygame.display.set_caption("Scoreboard - session id:" + str(session))

pygame.quit()

