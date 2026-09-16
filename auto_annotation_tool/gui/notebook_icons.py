"""Small, DPI-aware line icons for notebook tabs; no external assets or fonts."""
from __future__ import annotations

from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk


MAIN_TAB_ICONS = {
    "campaign": "workflow",
    "annotation": "annotation",
    "characters": "characters",
    "training": "training",
    "help": "book",
}


def _draw_icon(name: str, size: int, color: str) -> Image.Image:
    scale = 4
    image = Image.new("RGBA", (20 * scale, 20 * scale))
    draw = ImageDraw.Draw(image)
    ink = color
    width = 6

    def line(points):
        draw.line([(round(x * scale), round(y * scale)) for x, y in points],
                  fill=ink, width=width, joint="curve")

    def box(bounds, radius=1):
        draw.rounded_rectangle(tuple(round(v * scale) for v in bounds),
                               radius=radius * scale, outline=ink, width=width)

    def ellipse(bounds):
        draw.ellipse(tuple(round(v * scale) for v in bounds), outline=ink, width=width)

    if name == "workflow":
        line([(5, 5), (15, 5), (15, 15), (5, 15)])
        for x, y in ((5, 5), (15, 5), (15, 15), (5, 15)):
            draw.ellipse(((x-2)*scale, (y-2)*scale, (x+2)*scale, (y+2)*scale), fill=ink)
    elif name == "annotation":
        box((2, 4, 17, 14), radius=2)
        line([(5, 7), (9, 7)])
        line([(5, 10), (7, 10)])
        line([(10, 17), (12, 13), (17, 8), (19, 10), (14, 15), (10, 17)])
    elif name == "characters":
        box((1, 3, 19, 17), radius=2)
        line([(4, 14), (7, 6), (10, 14)])
        line([(5, 11), (9, 11)])
        line([(13, 6), (13, 14), (16, 14)])
        line([(13, 6), (16, 6)])
        line([(13, 10), (16, 10)])
    elif name == "training":
        box((5, 5, 15, 15))
        box((8, 8, 12, 12), radius=0)
        for p in (7, 10, 13):
            for points in ([(p, 2), (p, 5)], [(p, 15), (p, 18)],
                           [(2, p), (5, p)], [(15, p), (18, p)]):
                line(points)
    elif name == "book":
        line([(10, 5), (7, 3), (2, 3), (2, 15), (7, 15), (10, 17),
              (13, 15), (18, 15), (18, 3), (13, 3), (10, 5), (10, 17)])
    elif name == "crop":
        line([(5, 1), (5, 15), (19, 15)])
        line([(1, 5), (15, 5), (15, 19)])
        line([(9, 11), (18, 2)])
    elif name == "dataset":
        for y in (3, 8, 13):
            box((2, y, 18, y+4))
            line([(5, y+2), (6, y+2)])
    elif name == "experiment":
        line([(7, 2), (13, 2)])
        line([(8, 2), (8, 8), (3, 16), (4, 18), (16, 18), (17, 16), (12, 8), (12, 2)])
        line([(6, 13), (14, 13)])
    elif name == "history":
        ellipse((2, 2, 18, 18))
        line([(10, 5), (10, 10), (14, 12)])
    elif name == "ranking":
        box((2, 10, 6, 18), radius=0)
        box((8, 3, 12, 18), radius=0)
        box((14, 7, 18, 18), radius=0)
    elif name == "images":
        box((2, 3, 18, 17))
        ellipse((5, 6, 8, 9))
        line([(3, 15), (8, 10), (11, 13), (14, 9), (18, 14)])
    elif name == "checklist":
        box((4, 3, 17, 18))
        box((7, 1, 14, 5))
        line([(7, 11), (9, 13), (14, 8)])
    elif name == "settings":
        for y, x in ((4, 7), (10, 14), (16, 6)):
            line([(2, y), (18, y)])
            draw.rectangle(((x-2)*scale, (y-2)*scale, (x+2)*scale, (y+2)*scale),
                           fill=ink)
    elif name == "export":
        line([(3, 9), (3, 17), (17, 17), (17, 9)])
        line([(10, 13), (10, 2)])
        line([(6, 6), (10, 2), (14, 6)])
    elif name == "code":
        line([(6, 4), (1, 10), (6, 16)])
        line([(14, 4), (19, 10), (14, 16)])
        line([(12, 3), (8, 17)])
    elif name == "compare":
        line([(2, 6), (18, 6), (14, 2)])
        line([(18, 14), (2, 14), (6, 18)])
    else:
        raise ValueError(f"Unknown notebook icon: {name}")

    return image.resize((size, size), Image.Resampling.LANCZOS)


class _NotebookIcons:
    def __init__(self, notebook):
        self.notebook = notebook
        self.images = {}
        self.signature = None
        notebook.bind("<<ThemeChanged>>", self._refresh, add="+")
        notebook.bind("<Destroy>", self._destroy, add="+")

    def _destroy(self, event):
        if event.widget is self.notebook:
            self.images.clear()
            self.notebook = None

    def _appearance(self):
        style = ttk.Style(self.notebook)
        size = max(16, round(12 * float(self.notebook.tk.call("tk", "scaling"))))
        colors = []
        for states in (("!selected", "!disabled"), ("selected", "!disabled"), ("disabled",)):
            color = style.lookup("TNotebook.Tab", "foreground", states) or "#64748b"
            colors.append("#" + "".join(f"{value // 257:02x}" for value in self.notebook.winfo_rgb(color)))
        return size, tuple(colors)

    def _refresh(self, _event=None):
        signature = self._appearance()
        if signature == self.signature:
            return
        self.signature = signature
        size, colors = signature
        for name, images in self.images.items():
            for photo, color in zip(images, colors):
                photo.paste(_draw_icon(name, size, color))

    def options(self, name):
        self._refresh()
        if name not in self.images:
            size, colors = self.signature
            self.images[name] = tuple(
                ImageTk.PhotoImage(_draw_icon(name, size, color), master=self.notebook)
                for color in colors
            )
        normal, selected, disabled = self.images[name]
        return {"image": (normal, "disabled", disabled, "selected", selected), "compound": "left"}


def notebook_tab_icon(notebook, name: str) -> dict:
    """Keep each icon alive in its own Tk interpreter, including hidden/lazy tabs."""
    icons = getattr(notebook, "_tab_icons", None)
    if icons is None:
        icons = notebook._tab_icons = _NotebookIcons(notebook)
    return icons.options(name)
