"""Synthetic UI acceptance checks; no modem, messages, budget writes or probes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fourg_bridge.windows.ui import Window


def check_usage(window: Window) -> int:
    cases = (
        (None, "—", "secondary", None),
        (0.114, "11.4%", "blue", 0),
        (0.60, "60.0%", "orange", 0),
        (0.75, "75.0%", "red", 0),
        (0.79999, "79.9%", "red", 0),
        (0.80, "80.0%", "red", 1),
        (0.97999, "97.9%", "red", 1),
        (0.98, "98.0%", "red", 2),
        (1.02, "102.0%", "red", 2),
    )
    checked = 0
    for theme in ("light", "dark"):
        window.runtime.preferences.theme = theme
        window.palette = window._palette()
        window._styles()
        for fraction, percent, color, stage in cases:
            window.render_usage(fraction)
            window.tabs.select(1)
            window.root.update_idletasks()
            canvas: Any = window.ring
            assert canvas.itemcget("usage-value", "text") == percent
            assert canvas.itemcget("usage-value", "fill") == window.palette[color]
            if fraction:
                assert canvas.itemcget("usage-arc", "outline") == window.palette[color]
            else:
                assert not canvas.find_withtag("usage-arc")
            assert window.labels["percent"].get().startswith(percent)
            for index, card in enumerate(window.stage_cards):
                assert ("当前区间" in card.cget("text")) == (stage == index)
            checked += 1
        for index in range(6):
            window.tabs.select(index)
            window.root.update_idletasks()
            page = window.pages[index]
            for child in page.winfo_children():
                assert child.winfo_y() + child.winfo_height() <= page.winfo_height(), (
                    f"Page {index}: content extends below viewport"
                )
    return checked
