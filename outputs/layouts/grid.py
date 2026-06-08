"""outputs.layouts.grid — 12x8 그리드 (Phase 4, Part 8-1).

PPT 16:9 (33.867cm × 19.05cm) 기준. carrier 가 cm → EMU 변환.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Grid:
    """12 컬럼 × 8 행 그리드."""

    canvas_cm: tuple[float, float] = (33.867, 19.05)  # PPT 16:9
    cols: int = 12
    rows: int = 8
    gutter_cm: float = 0.4
    margin_x_cm: float = 1.4
    margin_y_cm: float = 0.9
    header_band_cm: float = 1.6  # 상단 헤더 (so_what)
    footer_band_cm: float = 0.8  # 하단 푸터

    @property
    def safe_area_cm(self) -> tuple[float, float]:
        w = self.canvas_cm[0] - 2 * self.margin_x_cm
        h = self.canvas_cm[1] - 2 * self.margin_y_cm - self.header_band_cm - self.footer_band_cm
        return (w, h)

    def col_width(self) -> float:
        w = self.safe_area_cm[0]
        return (w - (self.cols - 1) * self.gutter_cm) / self.cols

    def row_height(self) -> float:
        h = self.safe_area_cm[1]
        return (h - (self.rows - 1) * self.gutter_cm) / self.rows

    def region(self, col: int, row: int, span_cols: int = 1, span_rows: int = 1) -> dict:
        """그리드 좌표 (col, row, span) → cm 단위 box."""
        cw = self.col_width()
        rh = self.row_height()
        x = self.margin_x_cm + col * (cw + self.gutter_cm)
        y = self.margin_y_cm + self.header_band_cm + row * (rh + self.gutter_cm)
        return {
            "x_cm": x,
            "y_cm": y,
            "w_cm": cw * span_cols + (span_cols - 1) * self.gutter_cm,
            "h_cm": rh * span_rows + (span_rows - 1) * self.gutter_cm,
        }


SLIDE_GRID = Grid()
