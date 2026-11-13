#!/usr/bin/env python3

"""Rofi interface for i3-cheatsheet."""

import html
import shutil
import subprocess
import sys


def markup(value: str) -> str:
    """Escape text for Pango markup."""
    return html.escape(str(value))


def make_entry(binding: dict) -> str:
    key = markup(binding.get("key", ""))
    description = markup(binding.get("description", ""))
    category = markup(binding.get("category", "Other"))
    mode = binding.get("mode", "default")

    tags = binding.get("tags", [])
    tags_text = " ".join(str(tag) for tag in tags)

    if mode != "default":
        category += f" / {markup(mode)}"

    # Tags remain searchable but visually subtle.
    search_text = markup(tags_text)

    return (
        f"<b>{key:<24}</b>  "
        f"{description}  "
        f"<span foreground='#888888'>"
        f"[{category}]"
        f"</span>"
        f"<span alpha='1'>{search_text}</span>"
    )


def show(bindings: list[dict]):
    rofi = shutil.which("rofi")

    if not rofi:
        print("Error: Rofi is not installed.", file=sys.stderr)
        return 1

    if not bindings:
        print("No keyboard shortcuts found.", file=sys.stderr)
        return 1

    ordered = sorted(
        bindings,
        key=lambda item: (
            item.get("mode", "default") != "default",
            item.get("category", "Other").lower(),
            item.get("key", "").lower(),
        ),
    )

    entries = "\n".join(make_entry(item) for item in ordered)

    command = [
        rofi,
        "-dmenu",
        "-i",
        "-matching", "fuzzy",
        "-markup-rows",
        "--no-lazy-grab",
        "-no-custom",
        "-p", "Shortcuts",
        "-mesg", f"{len(bindings)} keyboard shortcuts",
        "-theme-str",
        """
        configuration {
            font: "JetBrainsMono Nerd Font 15";
        }

        window {
            width: 40%;
            location: center;
            anchor: center;
        }

        listview {
            lines: 18;
            columns: 1;
            fixed-height: false;
            spacing: 5px;
        }

        element {
            padding: 8px;
        }

        element-text {
            vertical-align: 0.5;
        }
        """
    ]

    try:
        subprocess.run(
            command,
            input=entries,
            text=True,
            check=False,
        )
    except OSError as error:
        print(f"Unable to launch Rofi: {error}", file=sys.stderr)
        return 1

    return 0

