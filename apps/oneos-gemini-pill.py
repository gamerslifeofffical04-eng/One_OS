#!/usr/bin/env python3
import os
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu-sandbox --disable-dev-shm-usage")

from PyQt6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRect, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

SOCK_PATH = f"/tmp/oneos-gemini-{os.getuid()}.sock"
STORAGE_DIR = Path.home() / ".local" / "share" / "OneOS-Gemini"


class CommandBridge(QObject):
    command_received = pyqtSignal(str)


class GeminiWebPage(QWebEnginePage):
    def createWindow(self, _type):
        return self


class AndroidGeminiPill(QWidget):
    def __init__(self):
        super().__init__()
        self.expanded = False
        self.web_initialized = False
        self.webview = None
        self.anim = None

        self.pill_w, self.pill_h = 216, 50
        self.sheet_w, self.sheet_h = 430, 640
        self.margin_right, self.margin_bottom = 20, 16

        self._build_ui()
        self._position_bottom_right(animated=False)

    def _build_ui(self):
        self.setWindowTitle("OneOS Gemini Pill")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(10, 10, 10, 10)

        # Collapsed Pill
        self.pill_frame = QFrame(self)
        self.pill_frame.setObjectName("GeminiPill")
        self.pill_frame.setStyleSheet(
            "QFrame#GeminiPill {"
            " background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #171C2E, stop:1 #222942);"
            " border: 1px solid rgba(135, 170, 255, 135);"
            " border-radius: 25px;"
            " }"
        )
        pill_shadow = QGraphicsDropShadowEffect(self)
        pill_shadow.setBlurRadius(22)
        pill_shadow.setOffset(0, 6)
        pill_shadow.setColor(QColor(0, 0, 0, 170))
        self.pill_frame.setGraphicsEffect(pill_shadow)

        pill_layout = QHBoxLayout(self.pill_frame)
        pill_layout.setContentsMargins(14, 4, 8, 4)
        pill_layout.setSpacing(6)

        self.ask_btn = QPushButton("✦  Ask Gemini")
        self.ask_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ask_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #F4F7FF; border: none; font-size: 13px; font-weight: 700; text-align: left; }"
            " QPushButton:hover { color: #A9C4FF; }"
        )
        self.ask_btn.clicked.connect(self.expand_sheet)
        pill_layout.addWidget(self.ask_btn, stretch=1)

        self.cts_pill_btn = QPushButton("◎")
        self.cts_pill_btn.setToolTip("Circle to Search")
        self.cts_pill_btn.setFixedSize(34, 34)
        self.cts_pill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cts_pill_btn.setStyleSheet(
            "QPushButton { background: rgba(95, 135, 255, 65); color: #FFFFFF; border: none; border-radius: 17px; font-size: 14px; font-weight: bold; }"
            " QPushButton:hover { background: rgba(115, 155, 255, 115); }"
        )
        self.cts_pill_btn.clicked.connect(self.trigger_circle_to_search)
        pill_layout.addWidget(self.cts_pill_btn)

        self.root_layout.addWidget(self.pill_frame)

        # Expanded Sheet
        self.sheet_frame = QFrame(self)
        self.sheet_frame.setObjectName("GeminiSheet")
        self.sheet_frame.setVisible(False)
        self.sheet_frame.setStyleSheet(
            "QFrame#GeminiSheet {"
            " background-color: #131622;"
            " border: 1px solid rgba(135, 170, 255, 110);"
            " border-radius: 22px;"
            " }"
        )
        sheet_shadow = QGraphicsDropShadowEffect(self)
        sheet_shadow.setBlurRadius(30)
        sheet_shadow.setOffset(0, 10)
        sheet_shadow.setColor(QColor(0, 0, 0, 195))
        self.sheet_frame.setGraphicsEffect(sheet_shadow)

        sheet_layout = QVBoxLayout(self.sheet_frame)
        sheet_layout.setContentsMargins(10, 10, 10, 10)
        sheet_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(6, 2, 4, 2)
        title = QLabel("✦ Gemini")
        title.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))
        title.setStyleSheet("color: #F4F7FF;")
        header.addWidget(title)
        header.addStretch()

        cts_hdr_btn = QPushButton("◎ Circle")
        cts_hdr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cts_hdr_btn.setStyleSheet(
            "QPushButton { background: rgba(95, 135, 255, 50); color: #DCE6FF; border: none; border-radius: 10px; padding: 5px 10px; font-size: 11px; font-weight: 600; }"
            " QPushButton:hover { background: rgba(95, 135, 255, 90); }"
        )
        cts_hdr_btn.clicked.connect(self.trigger_circle_to_search)
        header.addWidget(cts_hdr_btn)

        home_btn = QPushButton("⌂")
        home_btn.setToolTip("Reload Gemini")
        home_btn.setFixedSize(28, 28)
        home_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        home_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,14); color: #CBD5F5; border: none; border-radius: 14px; font-weight: bold; }"
            " QPushButton:hover { background: rgba(255,255,255,28); }"
        )
        home_btn.clicked.connect(self.reload_gemini)
        header.addWidget(home_btn)

        min_btn = QPushButton("⌄")
        min_btn.setToolTip("Collapse to Pill")
        min_btn.setFixedSize(28, 28)
        min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        min_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,14); color: #CBD5F5; border: none; border-radius: 14px; font-size: 14px; font-weight: bold; }"
            " QPushButton:hover { background: rgba(255,255,255,28); }"
        )
        min_btn.clicked.connect(self.collapse_to_pill)
        header.addWidget(min_btn)

        sheet_layout.addLayout(header)

        self.web_container = QVBoxLayout()
        self.web_container.setContentsMargins(0, 0, 0, 0)
        sheet_layout.addLayout(self.web_container, stretch=1)

        self.root_layout.addWidget(self.sheet_frame)

    def _ensure_webview(self):
        if self.web_initialized:
            return
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        profile = QWebEngineProfile("OneOSGeminiProfile", self)
        profile.setPersistentStoragePath(str(STORAGE_DIR / "storage"))
        profile.setCachePath(str(STORAGE_DIR / "cache"))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )

        page = GeminiWebPage(profile, self)
        self.webview = QWebEngineView(self)
        self.webview.setPage(page)
        self.webview.load(QUrl("https://gemini.google.com/app"))
        self.web_container.addWidget(self.webview)
        self.web_initialized = True

    def _target_geometry(self, is_expanded: bool) -> QRect:
        screen = QApplication.primaryScreen().availableGeometry()
        w = (self.sheet_w if is_expanded else self.pill_w) + 20
        h = (self.sheet_h if is_expanded else self.pill_h) + 20
        return QRect(
            screen.x() + screen.width() - w - self.margin_right + 10,
            screen.y() + screen.height() - h - self.margin_bottom + 10,
            w,
            h,
        )

    def _position_bottom_right(self, animated: bool = True):
        target = self._target_geometry(self.expanded)
        if not animated:
            self.setGeometry(target)
            return
        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(240)
        anim.setStartValue(self.geometry())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self.anim = anim

    def expand_sheet(self):
        self._ensure_webview()
        if not self.expanded:
            self.expanded = True
            self.pill_frame.setVisible(False)
            self.sheet_frame.setVisible(True)
            self._position_bottom_right(animated=True)
        self.show()
        self.raise_()
        self.activateWindow()

    def collapse_to_pill(self):
        if self.expanded:
            self.expanded = False
            self.sheet_frame.setVisible(False)
            self.pill_frame.setVisible(True)
            self._position_bottom_right(animated=True)

    def toggle_state(self):
        if self.expanded:
            self.collapse_to_pill()
        else:
            self.expand_sheet()

    def reload_gemini(self):
        if self.webview is not None:
            self.webview.load(QUrl("https://gemini.google.com/app"))

    def trigger_circle_to_search(self):
        self.hide()
        QTimer.singleShot(220, self._run_crop_and_paste)

    def _run_crop_and_paste(self):
        crop_path = "/tmp/oneos_cts_crop.png"
        if os.path.exists(crop_path):
            os.remove(crop_path)
        res = subprocess.run(["spectacle", "-r", "-b", "-n", "-o", crop_path], check=False)
        self.show()
        if res.returncode == 0 and os.path.isfile(crop_path):
            img = QImage(crop_path)
            if not img.isNull():
                QApplication.clipboard().setImage(img)
            self.expand_sheet()
            if self.webview is not None:
                QTimer.singleShot(
                    450,
                    lambda: self.webview.page().triggerAction(QWebEnginePage.WebAction.Paste),
                )

    def handle_ipc(self, msg: str):
        if msg == "expand":
            self.expand_sheet()
        elif msg == "collapse":
            self.collapse_to_pill()
        elif msg == "cts":
            self.trigger_circle_to_search()
        else:
            self.toggle_state()


def send_ipc(command: str) -> bool:
    if not os.path.exists(SOCK_PATH):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1.0)
            client.connect(SOCK_PATH)
            client.sendall(command.encode("utf-8"))
        return True
    except OSError:
        try:
            os.remove(SOCK_PATH)
        except OSError:
            pass
        return False


def start_ipc_server(bridge: CommandBridge):
    if os.path.exists(SOCK_PATH):
        try:
            os.remove(SOCK_PATH)
        except OSError:
            pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCK_PATH)
    server.listen(5)

    def loop():
        while True:
            try:
                conn, _ = server.accept()
                with conn:
                    data = conn.recv(64).decode("utf-8").strip()
                    if data:
                        bridge.command_received.emit(data)
            except OSError:
                break

    t = threading.Thread(target=loop, daemon=True)
    t.start()


def main():
    cmd = sys.argv[1].lstrip("-") if len(sys.argv) > 1 else "toggle"

    if send_ipc(cmd):
        sys.exit(0)

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    app.setApplicationName("OneOS Gemini Pill")
    app.setQuitOnLastWindowClosed(False)

    pill = AndroidGeminiPill()
    bridge = CommandBridge()
    bridge.command_received.connect(pill.handle_ipc)
    start_ipc_server(bridge)

    pill.show()
    if cmd == "expand":
        QTimer.singleShot(150, pill.expand_sheet)
    elif cmd == "cts":
        QTimer.singleShot(150, pill.trigger_circle_to_search)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
