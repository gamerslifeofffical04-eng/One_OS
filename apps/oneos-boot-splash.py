#!/usr/bin/env python3
import math
import sys
from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget


class AndroidTVBootSplash(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen
        )
        self.showFullScreen()
        self.elapsed_ms = 0
        self.total_duration_ms = 3200
        self.fading_out = False
        self.dot_colors = [
            QColor("#4F8BFF"),
            QColor("#FF5C77"),
            QColor("#FFCA3A"),
            QColor("#38D996"),
        ]
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    def _tick(self):
        self.elapsed_ms += 16
        if self.elapsed_ms >= self.total_duration_ms and not self.fading_out:
            self.fading_out = True
            eff = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", self)
            anim.setDuration(400)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
            anim.finished.connect(self.close)
            anim.start()
            self._fade_anim = anim
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0

        painter.fillRect(0, 0, w, h, QColor("#090B12"))
        t = self.elapsed_ms / 1000.0

        if t < 1.2:
            spacing = 46.0
            start_x = cx - 1.5 * spacing
            for i, col in enumerate(self.dot_colors):
                wave = math.sin(t * 7.5 - i * 0.65)
                bounce_y = -abs(wave) * 26.0
                self._draw_dot(painter, QPointF(start_x + i * spacing, cy + bounce_y), 11.0, col, 255)
        elif t < 2.0:
            p = (t - 1.2) / 0.8
            ease = 1.0 - pow(1.0 - p, 3)
            orbit_r = (1.0 - ease) * 75.0
            base_angle = ease * math.pi * 2.5
            alpha = int(255 * (1.0 - max(0.0, (p - 0.65) / 0.35)))
            for i, col in enumerate(self.dot_colors):
                angle = base_angle + i * (math.pi / 2.0)
                pos = QPointF(cx + math.cos(angle) * orbit_r, cy + math.sin(angle) * orbit_r)
                self._draw_dot(painter, pos, 11.0 - ease * 3.0, col, alpha)

        if t >= 1.75:
            p = min(1.0, (t - 1.75) / 0.65)
            ease = 1.0 - pow(1.0 - p, 3)
            alpha = int(255 * ease)
            star_cy = cy - 26.0 * ease
            self._draw_star(painter, QPointF(cx, star_cy), 34.0 * (0.45 + 0.55 * ease), alpha)

            if p > 0.25:
                tp = min(1.0, (p - 0.25) / 0.75)
                font = QFont("Sans Serif", 30, QFont.Weight.Bold)
                painter.setFont(font)
                painter.setPen(QColor(245, 248, 255, int(255 * tp)))
                painter.drawText(
                    QRectF(cx - 220, star_cy + 44, 440, 50),
                    Qt.AlignmentFlag.AlignCenter,
                    "OneOS",
                )

    def _draw_dot(self, painter, center, r, color, alpha):
        c = QColor(color)
        c.setAlpha(alpha)
        painter.setBrush(c)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, r, r)

    def _draw_star(self, painter, center, radius, alpha):
        path = QPainterPath()
        path.moveTo(center.x(), center.y() - radius)
        path.quadTo(center.x(), center.y(), center.x() + radius, center.y())
        path.quadTo(center.x(), center.y(), center.x(), center.y() + radius)
        path.quadTo(center.x(), center.y(), center.x() - radius, center.y())
        path.quadTo(center.x(), center.y(), center.x(), center.y() - radius)
        path.closeSubpath()
        grad = QLinearGradient(center.x() - radius, center.y() - radius, center.x() + radius, center.y() + radius)
        grad.setColorAt(0.0, QColor(90, 155, 255, alpha))
        grad.setColorAt(1.0, QColor(56, 217, 150, alpha))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = AndroidTVBootSplash()
    w.show()
    sys.exit(app.exec())
