#!/usr/bin/env python3
"""Parse i3 configuration files into searchable keyboard shortcuts."""

from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path
from typing import Any


ANNOTATION_RE = re.compile(
    r"^#\s*@(?P<key>desc|category|tags)\s*(?P<value>.*)$",
    re.IGNORECASE,
)

VARIABLE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")

DEFAULT_MODE = "default"


def expand_variables(value: str, variables: dict[str, str]) -> str:
    """Expand i3 variables recursively."""

    for _ in range(20):
        expanded = VARIABLE_RE.sub(
            lambda match: variables.get(match.group(), match.group()),
            value,
        )

        if expanded == value:
            break

        value = expanded

    return value


def split_words(line: str) -> list[str]:
    """Split a configuration line while preserving quoted arguments."""

    try:
        return shlex.split(line, comments=False, posix=True)
    except ValueError:
        return line.split()


def normalize_key(key: str, variables: dict[str, str]) -> str:
    """Convert i3 key notation into readable display notation."""

    key = expand_variables(key, variables)

    replacements = {
        "Mod4": "SUPER",
        "Mod1": "ALT",
        "Mod2": "NUM",
        "Mod3": "MOD3",
        "Mod5": "MOD5",
        "Control": "CTRL",
        "Ctrl": "CTRL",
        "Shift": "SHIFT",
        "Shift_L": "SHIFT",
        "Shift_R": "SHIFT",
    }

    parts = key.split("+")

    normalized = []

    for part in parts:
        normalized.append(replacements.get(part, part.upper()))

    return " + ".join(normalized)


def infer_description(command: str) -> tuple[str, str, list[str]]:
    """Infer a human-readable description from an i3 command."""

    cmd = command.strip()

    rules = [
        (r"^kill\b", "Close focused window", "Windows", ["close", "terminate"]),
        (r"^fullscreen\b", "Toggle fullscreen", "Layout", ["maximize", "screen"]),
        (r"^focus\s+left", "Focus window left", "Navigation", ["navigate"]),
        (r"^focus\s+right", "Focus window right", "Navigation", ["navigate"]),
        (r"^focus\s+up", "Focus window above", "Navigation", ["navigate"]),
        (r"^focus\s+down", "Focus window below", "Navigation", ["navigate"]),
        (r"^move\s+", "Move focused window", "Windows", ["reposition"]),
        (r"^workspace\b", "Switch workspace", "Workspaces", ["desktop", "switch"]),
        (r"^split\s+h", "Split horizontally", "Layout", ["horizontal"]),
        (r"^split\s+v", "Split vertically", "Layout", ["vertical"]),
        (r"^floating\s+", "Toggle floating window", "Windows", ["floating"]),
        (r"^layout\s+stacking", "Switch to stacking layout", "Layout", ["stacking"]),
        (r"^layout\s+tabbed", "Switch to tabbed layout", "Layout", ["tabs"]),
        (r"^layout\s+toggle", "Toggle container layout", "Layout", ["split"]),
        (r"^reload\b", "Reload i3 configuration", "System", ["config", "refresh"]),
        (r"^restart\b", "Restart i3", "System", ["refresh"]),
        (r"^resize\b", "Resize window", "Resize", ["grow", "shrink"]),
        (r"^mode\b", "Switch i3 mode", "System", ["mode"]),
    ]

    for pattern, description, category, tags in rules:
        if re.search(pattern, cmd, re.IGNORECASE):
            return description, category, tags

    if cmd.startswith("exec"):
        executable = cmd[4:].strip()

        if "--no-startup-id" in executable:
            executable = executable.replace("--no-startup-id", "").strip()

        executable = executable.split()[0] if executable else ""

        if executable:
            name = Path(executable).name
            return f"Launch {name}", "Applications", ["launch", "application"]

    return cmd[:80] or "Unknown command", "Other", []


class I3Parser:
    def __init__(self):
        self.variables: dict[str, str] = {}
        self.bindings: list[dict[str, Any]] = []
        self.files: set[Path] = set()

    def parse(self, config_path: str | Path) -> list[dict[str, Any]]:
        self.variables.clear()
        self.bindings.clear()
        self.files.clear()

        self._parse_file(Path(config_path).expanduser().resolve())

        return self.bindings

    def _parse_file(
        self,
        path: Path,
        inherited_mode: str = DEFAULT_MODE,
        depth: int = 0,
    ):
        if depth > 20 or path in self.files or not path.is_file():
            return

        self.files.add(path)

        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return

        mode_stack = [inherited_mode]
        pending: dict[str, Any] = {}
        block_modes: list[str] = []

        for line_number, raw in enumerate(lines, 1):
            stripped = raw.strip()

            if not stripped:
                continue

            # Annotations are attached to the next binding.
            annotation = ANNOTATION_RE.match(stripped)

            if annotation:
                key = annotation.group("key").lower()
                value = annotation.group("value").strip()

                if key == "desc":
                    pending["description"] = value
                elif key == "category":
                    pending["category"] = value
                elif key == "tags":
                    pending["tags"] = value.split()

                continue

            # Ordinary comments do not create bindings.
            if stripped.startswith("#"):
                continue

            # Remove inline comments outside quoted strings.
            line = self._remove_inline_comment(stripped)

            if not line:
                continue

            # Handle block opening.
            if line.endswith("{"):
                header = line[:-1].strip()
                words = split_words(header)

                if words and words[0] == "mode":
                    mode_name = " ".join(words[1:]).strip('"')
                    mode_name = expand_variables(mode_name, self.variables)
                    mode_stack.append(mode_name)
                    block_modes.append("mode")
                else:
                    block_modes.append("other")

                pending.clear()
                continue

            # Handle block closing.
            if line == "}":
                if block_modes:
                    block_type = block_modes.pop()

                    if block_type == "mode" and len(mode_stack) > 1:
                        mode_stack.pop()

                pending.clear()
                continue

            words = split_words(line)

            if not words:
                continue

            directive = words[0]

            # Variables.
            if directive == "set" and len(words) >= 3:
                self.variables[words[1]] = " ".join(words[2:])
                continue

            # Included files.
            if directive == "include" and len(words) >= 2:
                include_value = expand_variables(words[1], self.variables)
                include_path = Path(include_value).expanduser()

                if not include_path.is_absolute():
                    include_path = path.parent / include_path

                self._parse_file(
                    include_path.resolve(),
                    inherited_mode=mode_stack[-1],
                    depth=depth + 1,
                )
                continue

            if directive not in ("bindsym", "bindcode"):
                pending.clear()
                continue

            # Parse the binding.
            options = []
            index = 1

            while index < len(words) and words[index].startswith("--"):
                options.append(words[index])
                index += 1

            if index >= len(words):
                pending.clear()
                continue

            key = words[index]
            command = " ".join(words[index + 1:])

            if not command:
                pending.clear()
                continue

            expanded_command = expand_variables(command, self.variables)
            expanded_key = expand_variables(key, self.variables)

            description, category, tags = infer_description(expanded_command)

            description = pending.get("description", description)
            category = pending.get("category", category)
            tags = pending.get("tags", tags)

            # Expand mode names for display.
            mode = mode_stack[-1]

            binding = {
                "key": normalize_key(expanded_key, {}),
                "command": command,
                "expanded_command": expanded_command,
                "description": description,
                "category": category,
                "tags": tags,
                "mode": mode,
                "type": directive,
                "options": options,
                "source": str(path),
                "line": line_number,
            }

            self.bindings.append(binding)
            pending.clear()

    @staticmethod
    def _remove_inline_comment(line: str) -> str:
        """Remove comments while respecting quotes."""

        quote = None
        escaped = False

        for index, char in enumerate(line):
            if escaped:
                escaped = False
                continue

            if char == "\\":
                escaped = True
                continue

            if quote:
                if char == quote:
                    quote = None
                continue

            if char in ('"', "'"):
                quote = char
                continue

            if char == "#":
                return line[:index].rstrip()

        return line


def main():
    cli = argparse.ArgumentParser(
        description="Extract keyboard shortcuts from an i3 configuration."
    )

    cli.add_argument(
        "config",
        nargs="?",
        default="~/.config/i3/config",
        help="Path to i3 config",
    )

    cli.add_argument(
        "-o",
        "--output",
        help="Write JSON to a file instead of stdout",
    )

    args = cli.parse_args()

    parser = I3Parser()
    bindings = parser.parse(args.config)

    result = {
        "version": 1,
        "files": sorted(str(path) for path in parser.files),
        "variables": parser.variables,
        "binding_count": len(bindings),
        "bindings": bindings,
    }

    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()

