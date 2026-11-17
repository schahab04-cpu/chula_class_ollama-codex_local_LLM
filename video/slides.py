"""Render the video's slides (1920x1080) with matplotlib from video/scenes.py."""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenes  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / ".tmp" / "video" / "slides"
BG, INK, MUTED = "#04060c", "#eef4fb", "#8a9bb0"
CYAN, VIOLET, AMBER, GREEN = "#5ce8d6", "#a88bff", "#ffd27a", "#79dca6"
FONT = ["Helvetica Neue", "DejaVu Sans"]

# Architecture diagram: (row label, colour, [(box title, box detail), ...]).
PIPELINE = [
    ("Documents", CYAN, [("Upload", "PDF, Word, text"), ("Extract & chunk", "short passages"),
                         ("Embed", "nomic-embed-text"), ("SQLite index", "on this laptop")]),
    ("Questions", VIOLET, [("Question", "typed or spoken"), ("Hybrid search", "vectors + keywords"),
                           ("Qwen 3.5 · 9B", "in Ollama"), ("Answer", "with sources")]),
    ("Voice", AMBER, [("Silero VAD", "hears when you speak"), ("Whisper", "speech → text"),
                      ("Qwen 3.5 · 9B", "writes the reply"), ("Kokoro", "text → speech")]),
]


def canvas():
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1920)
    ax.set_ylim(1080, 0)
    ax.axis("off")
    # A soft glow in the corner, echoing the voice screen's animation.
    for radius, alpha in ((620, .05), (420, .06), (240, .07)):
        ax.add_patch(plt.Circle((1780, 120), radius, color=VIOLET, alpha=alpha, lw=0))
        ax.add_patch(plt.Circle((120, 1000), radius * .8, color=CYAN, alpha=alpha * .8, lw=0))
    return fig, ax


def heading(ax, text):
    ax.text(140, 190, text, color=INK, fontsize=72, fontweight="bold", family=FONT, va="center")
    ax.plot([140, 320], [270, 270], color=CYAN, lw=7, solid_capstyle="round")


def title_slide(slide):
    fig, ax = canvas()
    ax.text(960, 330, slide["kicker"], color=CYAN, fontsize=28, family=FONT, ha="center")
    ax.text(960, 500, slide["title"], color=INK, fontsize=150, fontweight="bold", family=FONT,
            ha="center", va="center")
    ax.text(960, 690, slide["subtitle"], color=MUTED, fontsize=38, family=FONT, ha="center", va="center",
            linespacing=1.5)
    return [fig]


def bullet_slide(slide):
    """One image per stage: the heading alone, then one more bullet each time."""
    figures = []
    for stage in range(len(slide["bullets"]) + 1):
        fig, ax = canvas()
        heading(ax, slide["title"])
        y = 350
        for index, bullet in enumerate(slide["bullets"][:stage]):
            colour = (CYAN, VIOLET, AMBER, GREEN)[index % 4]
            ax.add_patch(plt.Circle((172, y + 38), 16, color=colour))
            ax.text(230, y, bullet, color=INK, fontsize=48, family=FONT, va="top", linespacing=1.3)
            y += 76 * (bullet.count("\n") + 1) + 52
        figures.append(fig)
    return figures


def diagram(ax, top=300, rows=3, badge=True):
    box_w, box_h, gap, left, step = 330, 130, 70, 300, 200
    for row, (label, colour, boxes) in enumerate(PIPELINE[:rows]):
        y = top + row * step
        ax.text(250, y + box_h / 2, label, color=colour, fontsize=30, fontweight="bold", family=FONT,
                ha="right", va="center")
        for column, (name, detail) in enumerate(boxes):
            x = left + column * (box_w + gap)
            ax.add_patch(FancyBboxPatch((x, y), box_w, box_h, boxstyle="round,pad=0,rounding_size=22",
                                        facecolor="#0d1424", edgecolor=colour, lw=3))
            ax.text(x + box_w / 2, y + 50, name, color=INK, fontsize=30, fontweight="bold", family=FONT,
                    ha="center", va="center")
            ax.text(x + box_w / 2, y + 95, detail, color=MUTED, fontsize=22, family=FONT, ha="center",
                    va="center")
            if column:
                ax.add_patch(FancyArrowPatch((x - gap + 8, y + box_h / 2), (x - 8, y + box_h / 2),
                                             arrowstyle="-|>", mutation_scale=30, color=colour, lw=3))
    if rows >= 2:
        # The index feeds the search.
        index_x = left + 3 * (box_w + gap) + box_w / 2
        search_x = left + 1 * (box_w + gap) + box_w / 2
        ax.add_patch(FancyArrowPatch((index_x, top + box_h + 4), (search_x + 110, top + step - 4),
                                     arrowstyle="-|>", mutation_scale=30, color=CYAN, lw=2.5,
                                     linestyle=(0, (6, 5))))
    if badge:
        ax.text(1780, 190, "Everything runs locally\nno cloud APIs · no accounts",
                color=GREEN, fontsize=30, fontweight="bold", family=FONT, ha="right", va="center",
                linespacing=1.4)


def diagram_slide(slide):
    """Stages: heading, then one pipeline row at a time, then the "runs locally" badge."""
    figures = []
    for stage in range(len(PIPELINE) + 2):
        fig, ax = canvas()
        heading(ax, slide["title"])
        diagram(ax, rows=min(stage, len(PIPELINE)), badge=stage > len(PIPELINE))
        figures.append(fig)
    return figures


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for path in OUT.glob("*.png"):
        path.unlink()
    for slide in scenes.SLIDES:
        if slide["id"] == "hook":
            continue  # drawn over demo footage by build.py
        if slide.get("diagram"):
            figures = diagram_slide(slide)
        elif "bullets" in slide:
            figures = bullet_slide(slide)
        else:
            figures = title_slide(slide)
        for stage, fig in enumerate(figures):
            fig.savefig(OUT / f"{slide['id']}_{stage}.png", facecolor=BG)
            plt.close(fig)
        print(slide["id"], len(figures), "stages")
    # The architecture diagram on its own, for the report or slides: transparent PNG + SVG.
    fig, ax = canvas()
    for patch in list(ax.patches)[:6]:
        patch.remove()
    fig.patch.set_alpha(0)
    diagram(ax, top=180)
    for suffix in ("png", "svg"):
        fig.savefig(OUT / f"architecture_diagram.{suffix}", dpi=300, transparent=True)
    plt.close(fig)


if __name__ == "__main__":
    main()
