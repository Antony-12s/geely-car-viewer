"""Window size picking. Needs a display: run under Xvfb with the screen size in EX5_SCREEN, e.g.
    Xvfb :91 -screen 0 1024x768x24 &  DISPLAY=:91 EX5_SCREEN=1024x768 pytest tests/test_ui_size.py
"""
import os
import tkinter as tk

import pytest

from ex5viewer import ui
from ex5viewer.settings import Settings

SCREEN = os.environ.get("EX5_SCREEN")
pytestmark = pytest.mark.skipif(not SCREEN, reason="set EX5_SCREEN and DISPLAY (see docstring)")


def open_app(tmp_path, **opts):
    settings = Settings(tmp_path / "s.json")
    settings.update(auto_connect=False, **opts)
    root = tk.Tk()
    app = ui.App(root, settings)
    root.update()
    return root, app


@pytest.mark.parametrize("size", ["auto", "large"])
def test_size(tmp_path, size):
    width, height = map(int, SCREEN.split("x"))
    root, app = open_app(tmp_path, size=size)
    try:
        if size == "large":  # an explicit choice is kept even when it overflows
            assert app.size_name == "large"
        elif SCREEN in ("1920x1080", "1600x900", "2560x1440"):
            assert app.size_name == "medium"  # auto never grows past medium
        else:  # 1024x768, 1280x720, 1366x768 (the car panel makes medium 777 px tall)
            assert app.size_name == "small"
            assert root.winfo_width() <= width and root.winfo_height() <= height
        assert app.s["size"] == size  # the saved setting is not overwritten
    finally:
        app.quit()
