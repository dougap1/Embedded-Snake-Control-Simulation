# Import statements
import sys
import random
import time
import math
import serial
from PyQt6.QtCore import QTimer, Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QPixmap, QFont, QLinearGradient
from PyQt6.QtWidgets import QApplication, QWidget
from qt_material import apply_stylesheet

# Beginning of UltraSnake GUI code
class SnakeWindow(QWidget):
    """PyQt6 Snake game controlled by keyboard + SLATE serial sensor data."""

    SERIAL_PORT = "COM4"
    BAUD_RATE = 115200
    APPLE_PATH = "desktop/assets/apple.png"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("UltraSnake")
        self.resize(1140, 800)
        self.setFixedSize(1140, 800)

        # Board layout: 40 x 40 grid for more room to move.
        self.board_width = 800
        self.board_height = 800
        self.cell_size = 20

        # Right-side dashboard scales from the board size.
        self.panel_width = 270
        self.panel_x = self.board_width + 40
        self.grid_width = self.board_width // self.cell_size
        self.grid_height = self.board_height // self.cell_size

        # Input tuning
        self.last_turn_time = 0
        self.turn_cooldown = 0.25

        # Ultrasonic smoothing / speed tuning
        self.current_speed = 200
        self.sensor_value = 0
        self.last_sensor = 0
        self.min_delay = 40      # lower = faster snake
        self.max_delay = 320     # higher = slower snake
        self.min_distance = 8
        self.max_distance = 35

        # UI / animation state
        self.speed_percent = 0.0
        self.target_speed_percent = 0.0
        self.temperature = 22.0
        self.last_input = "Keyboard ready"
        self.food_pulse = 0.0

        # Assets
        self.food_icon = QPixmap(self.APPLE_PATH)

        # Serial is optional-safe: keyboard still works if board is unplugged.
        self.serial = None
        self.serial_status = "Disconnected"
        self.connect_serial()

        # Main game timer: controls the snake movement rate.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_game)

        # Separate UI timer: keeps visual animations smooth even when snake is slow.
        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.update_ui_animation)
        self.ui_timer.start(16)  # about 60 FPS

        self.reset_game()
        self.timer.start(self.current_speed)

    def connect_serial(self):
        """Try to connect to the SLATE board without crashing the GUI."""
        try:
            self.serial = serial.Serial(self.SERIAL_PORT, self.BAUD_RATE, timeout=0)
            self.serial_status = f"Connected: {self.SERIAL_PORT}"
        except serial.SerialException:
            self.serial = None
            self.serial_status = "No board / COM4 unavailable"

    def send_to_board(self, message):
        """Send event messages back to the SLATE board: EAT, GAMEOVER, RESET."""
        try:
            if self.serial is not None and self.serial.is_open:
                self.serial.write((message + "\n").encode())
        except serial.SerialException:
            self.serial = None
            self.serial_status = "Board disconnected"

    def reset_game(self):
        center_x = self.grid_width // 2
        center_y = self.grid_height // 2
        self.snake = [(center_x, center_y), (center_x - 1, center_y), (center_x - 2, center_y)]
        self.direction = (1, 0)
        self.next_direction = self.direction
        self.score = 0
        self.game_over = False
        self.paused = False

        self.last_turn_time = 0
        self.sensor_value = 0
        self.last_sensor = 0
        self.current_speed = 200
        self.speed_percent = self.get_speed_percent()
        self.target_speed_percent = self.speed_percent
        self.last_input = "Keyboard ready"

        self.food = self.random_food_position()

        # Clear hardware feedback when the game restarts.
        self.send_to_board("RESET")

        self.timer.start(self.current_speed)
        self.update()

    def random_food_position(self):
        while True:
            food = (
                random.randint(0, self.grid_width - 1),
                random.randint(0, self.grid_height - 1),
            )
            if food not in self.snake:
                return food

    def can_turn(self):
        now = time.time()
        if now - self.last_turn_time >= self.turn_cooldown:
            self.last_turn_time = now
            return True
        return False

    def set_direction(self, new_direction):
        """Set direction while preventing instant 180-degree reversal."""
        dx, dy = self.direction
        ndx, ndy = new_direction
        if (ndx, ndy) != (-dx, -dy):
            self.next_direction = new_direction

    def turn_left(self):
        if self.game_over or self.paused or not self.can_turn():
            return
        dx, dy = self.direction
        self.set_direction((dy, -dx))

    def turn_right(self):
        if self.game_over or self.paused or not self.can_turn():
            return
        dx, dy = self.direction
        self.set_direction((-dy, dx))

    def read_serial_input(self):
        """Read all waiting serial lines from the board.

        Expected board messages:
        DIR:L
        DIR:R
        DIR:N
        DIST:24
        TEMP:22
        """
        if self.serial is None:
            return

        try:
            while self.serial.in_waiting:
                line = self.serial.readline().decode(errors="ignore").strip()
                if not line:
                    continue

                if line == "DIR:L":
                    self.last_input = "Joystick LEFT"
                    self.turn_left()
                elif line == "DIR:R":
                    self.last_input = "Joystick RIGHT"
                    self.turn_right()
                elif line == "DIR:N":
                    self.last_input = "Joystick neutral"
                elif line.startswith("DIST:"):
                    try:
                        new_value = int(line.split(":", 1)[1])
                        # Smooth noisy ultrasonic readings.
                        self.sensor_value = int(0.7 * self.sensor_value + 0.3 * new_value)
                    except ValueError:
                        pass
                elif line.startswith("TEMP:"):
                    try:
                        self.temperature = float(line.split(":", 1)[1])
                    except ValueError:
                        pass
        except serial.SerialException:
            self.serial = None
            self.serial_status = "Board disconnected"

    def update_speed_from_sensor(self):
        if abs(self.sensor_value - self.last_sensor) < 2:
            return

        self.last_sensor = self.sensor_value

        # Clamp distance so one bad reading does not make the game unusable.
        d = max(self.min_distance, min(self.max_distance, self.sensor_value))

        # Closer hand = faster snake. Farther hand = slower snake.
        percent = (d - self.min_distance) / (self.max_distance - self.min_distance)
        self.current_speed = int(self.min_delay + percent * (self.max_delay - self.min_delay))
        self.current_speed = max(self.min_delay, min(self.max_delay, self.current_speed))
        self.target_speed_percent = self.get_speed_percent()
        self.timer.start(self.current_speed)

    def get_speed_percent(self):
        # Convert delay into a visual percentage. Lower delay means faster.
        percent = 1 - ((self.current_speed - self.min_delay) / (self.max_delay - self.min_delay))
        return max(0.0, min(1.0, percent))

    def update_ui_animation(self):
        # Ease the displayed bar toward the real speed instead of jumping.
        self.target_speed_percent = self.get_speed_percent()
        self.speed_percent += (self.target_speed_percent - self.speed_percent) * 0.12
        self.food_pulse = time.time() * 6
        self.update()

    def update_game(self):
        self.read_serial_input()
        self.update_speed_from_sensor()

        if self.game_over:
            return

        if self.paused:
            self.update()
            return

        # Apply any queued keyboard/joystick direction change.
        self.direction = self.next_direction

        # Compute the next head position.
        head_x, head_y = self.snake[0]
        dx, dy = self.direction
        new_head = (head_x + dx, head_y + dy)

        # Check wall and self collisions.
        hit_wall = (
            new_head[0] < 0
            or new_head[0] >= self.grid_width
            or new_head[1] < 0
            or new_head[1] >= self.grid_height
        )
        hit_self = new_head in self.snake

        if hit_wall or hit_self:
            self.game_over = True
            self.send_to_board("GAMEOVER")
            self.update()
            return

        self.snake.insert(0, new_head)

        if new_head == self.food:
            self.score += 1
            self.food = self.random_food_position()

            # Hardware sound effect is handled by the board speaker.
            self.send_to_board("EAT")
        else:
            self.snake.pop()

        self.update()

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key.Key_P:
            self.last_input = "Keyboard: Pause"
            self.paused = not self.paused
            self.update()
            return

        if key == Qt.Key.Key_R:
            self.reset_game()
            return

        if self.game_over:
            return

        if key == Qt.Key.Key_Up:
            self.last_input = "Keyboard UP"
            self.set_direction((0, -1))
        elif key == Qt.Key.Key_Down:
            self.last_input = "Keyboard DOWN"
            self.set_direction((0, 1))
        elif key == Qt.Key.Key_Left:
            self.last_input = "Keyboard LEFT"
            self.set_direction((-1, 0))
        elif key == Qt.Key.Key_Right:
            self.last_input = "Keyboard RIGHT"
            self.set_direction((1, 0))

    def draw_text(self, painter, x, y, text, size=12, bold=False, color="white"):
        font = QFont(painter.font())
        font.setPointSize(size)
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(x, y, text)

    def draw_center_message(self, painter, title, subtitle):
        # Overlay is centered on the board, so it still looks right after resizing.
        box_w = 400
        box_h = 130
        box_x = (self.board_width - box_w) // 2
        box_y = (self.board_height - box_h) // 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawRoundedRect(box_x, box_y, box_w, box_h, 18, 18)

        painter.setPen(QColor("white"))
        font = painter.font()
        font.setPointSize(20)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(box_x, box_y + 25, box_w, 35), Qt.AlignmentFlag.AlignCenter, title)

        font.setPointSize(10)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(QRectF(box_x, box_y + 75, box_w, 30), Qt.AlignmentFlag.AlignCenter, subtitle)

    def draw_section_title(self, painter, y, title):
        # Section headers use the full usable panel width.
        self.draw_text(painter, self.panel_x, y, title, size=11, bold=True, color="#40E090")
        painter.setPen(QColor(65, 75, 75))
        painter.drawLine(self.panel_x, y + 8, self.panel_x + self.panel_width - 45, y + 8)

    def draw_stat_row(self, painter, y, label, value, color="white"):
        # Draw values right-aligned so they stay inside the side panel.
        self.draw_text(painter, self.panel_x, y, label, size=9, color="#AFC7C7")

        font = QFont(painter.font())
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(color))

        value_rect = QRectF(
            self.panel_x + 95,
            y - 14,
            self.panel_width - 125,
            22,
        )
        painter.drawText(value_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value)
    def board_gradient(self):
        if self.temperature < 18:
            top = QColor(15, 30, 55)      # cold blue tint
            bottom = QColor(8, 15, 28)
        elif self.temperature > 27:
            top = QColor(65, 35, 25)      # warm orange/red tint
            bottom = QColor(28, 12, 10)
        else:
            top = QColor(20, 28, 28)      # normal dark teal
            bottom = QColor(8, 14, 14)

        gradient = QLinearGradient(0, 0, 0, self.board_height)
        gradient.setColorAt(0, top)
        gradient.setColorAt(1, bottom)
        return gradient

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Board background: now a subtle gradient, optionally temperature tinted.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.board_gradient())
        painter.drawRect(0, 0, self.board_width, self.board_height)

        # Softer grid so it does not overpower the snake.
        painter.setPen(QColor(38, 48, 48))
        for x in range(0, self.board_width + 1, self.cell_size):
            painter.drawLine(x, 0, x, self.board_height)
        for y in range(0, self.board_height + 1, self.cell_size):
            painter.drawLine(0, y, self.board_width, y)

        # Side panel card.
        painter.setPen(Qt.PenStyle.NoPen)
        panel_gradient = QLinearGradient(self.panel_x - 20, 10, self.panel_x + self.panel_width, self.board_height - 10)
        panel_gradient.setColorAt(0, QColor(32, 42, 42))
        panel_gradient.setColorAt(1, QColor(18, 22, 22))
        painter.setBrush(panel_gradient)
        painter.drawRoundedRect(self.panel_x - 10, 10, self.panel_width, self.board_height - 20, 16, 16)

        # Title block.
        self.draw_text(painter, self.panel_x, 45, "UltraSnake", size=24, bold=True, color="#40E090")

        # Stats section.
        self.draw_section_title(painter, 100, "GAME")
        self.draw_stat_row(painter, 130, "Score", str(self.score), color="#40E090")
        self.draw_stat_row(painter, 155, "Distance", f"{self.sensor_value} cm")
        self.draw_stat_row(painter, 180, "Delay", f"{self.current_speed} ms")

        # Smooth speed bar.
        bar_x = self.panel_x
        bar_y = 200
        bar_w = self.panel_width - 60
        bar_h = 16
        speed_percent = max(0.0, min(1.0, self.speed_percent))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(55, 65, 65))
        painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 8, 8)

        fill_w = max(8, int(bar_w * speed_percent))
        painter.setBrush(QColor(40, 220, 140))
        painter.drawRoundedRect(bar_x, bar_y, fill_w, bar_h, 8, 8)
        self.draw_text(painter, bar_x, bar_y - 6, "Speed", size=8, color="#AFC7C7")

        # System section.
        self.draw_section_title(painter, 245, "SYSTEM")
        status_color = "#40E090" if "Connected" in self.serial_status else "#FF5C5C"
        self.draw_stat_row(painter, 275, "SLATE", "ON" if "Connected" in self.serial_status else "OFF", color=status_color)
        self.draw_text(painter, self.panel_x, 295, self.serial_status, size=7, color="#AFC7C7")
        self.draw_text(painter, self.panel_x, 320, f"Input: {self.last_input}", size=8, color="#FFFFFF")
        self.draw_stat_row(painter, 345, "Temp", f"{self.temperature:.1f} C")

        # Controls section.
        self.draw_section_title(painter, 380, "CONTROLS")
        self.draw_text(painter, self.panel_x, 410, "Arrows: Move", size=8)
        self.draw_text(painter, self.panel_x, 430, "Joystick: L/R turn", size=8)
        self.draw_text(painter, self.panel_x, 450, "P: Pause    R: Restart", size=8)

        # Snake glow + body.
        padding = 2
        painter.setPen(Qt.PenStyle.NoPen)
        for i, (x, y) in enumerate(self.snake):
            px = x * self.cell_size + padding
            py = y * self.cell_size + padding
            size = self.cell_size - 2 * padding

            if i == 0:
                painter.setBrush(QColor(30, 220, 120, 70))
                painter.drawRoundedRect(px - 3, py - 3, size + 6, size + 6, 11, 11)
                painter.setBrush(QColor(40, 240, 140))
                radius = 9
            else:
                painter.setBrush(QColor(70, 200, 110))
                radius = 8

            painter.drawRoundedRect(px, py, size, size, radius, radius)

        # Snake eyes.
        head_x, head_y = self.snake[0]
        hx = head_x * self.cell_size
        hy = head_y * self.cell_size
        eye_size = max(2, self.cell_size // 7)
        painter.setBrush(QColor("white"))

        # Eye positions scale with the cell size.
        near = int(self.cell_size * 0.25)
        far = int(self.cell_size * 0.65)
        mid1 = int(self.cell_size * 0.30)
        mid2 = int(self.cell_size * 0.60)

        if self.direction == (1, 0):
            eyes = [(hx + far, hy + mid1), (hx + far, hy + mid2)]
        elif self.direction == (-1, 0):
            eyes = [(hx + near, hy + mid1), (hx + near, hy + mid2)]
        elif self.direction == (0, -1):
            eyes = [(hx + mid1, hy + near), (hx + mid2, hy + near)]
        else:
            eyes = [(hx + mid1, hy + far), (hx + mid2, hy + far)]

        for ex, ey in eyes:
            painter.drawEllipse(ex, ey, eye_size, eye_size)

        # Food icon with pulse animation.
        fx, fy = self.food
        pulse = 1 + 0.08 * math.sin(self.food_pulse)
        food_size = int((self.cell_size - 4) * pulse)
        food_x = fx * self.cell_size + (self.cell_size - food_size) // 2
        food_y = fy * self.cell_size + (self.cell_size - food_size) // 2

        if not self.food_icon.isNull():
            painter.drawPixmap(food_x, food_y, food_size, food_size, self.food_icon)
        else:
            painter.setBrush(QColor(220, 60, 60))
            painter.drawEllipse(food_x, food_y, food_size, food_size)

        # Overlay states.
        if self.paused:
            self.draw_center_message(painter, "Paused", "Press P to resume")

        if self.game_over:
            self.draw_center_message(painter, "Game Over", "Press R to restart")


def main():
    app = QApplication(sys.argv)
    apply_stylesheet(app, theme="dark_teal.xml")
    window = SnakeWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
