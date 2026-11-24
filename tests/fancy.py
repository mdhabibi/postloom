# ruff: noqa: RUF001  (look-alike letters are the point of this module)
"""Write text the way LinkedIn "fancy text" converters do, without typing those characters."""

from __future__ import annotations

from collections.abc import Callable

SMALL_CAPS = "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"


def _alphabet(capital: int, small: int, digit: int | None = None) -> Callable[[str], str]:
    def convert(text: str) -> str:
        out: list[str] = []
        for char in text:
            if "A" <= char <= "Z":
                out.append(chr(capital + ord(char) - ord("A")))
            elif "a" <= char <= "z":
                out.append(chr(small + ord(char) - ord("a")))
            elif digit is not None and "0" <= char <= "9":
                out.append(chr(digit + ord(char) - ord("0")))
            else:
                out.append(char)
        return "".join(out)

    return convert


bold = _alphabet(0x1D400, 0x1D41A, 0x1D7CE)
italic = _alphabet(0x1D434, 0x1D44E)
sans_bold = _alphabet(0x1D5D4, 0x1D5EE, 0x1D7EC)
sans_italic = _alphabet(0x1D608, 0x1D622)
bold_script = _alphabet(0x1D4D0, 0x1D4EA)
monospace = _alphabet(0x1D670, 0x1D68A, 0x1D7F6)
fullwidth = _alphabet(0xFF21, 0xFF41, 0xFF10)
circled = _alphabet(0x24B6, 0x24D0)
negative_squared = _alphabet(0x1F170, 0x1F170)


def double_struck(text: str) -> str:
    holes = {"C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ",
             "R": "ℝ", "Z": "ℤ"}  # fmt: skip
    return "".join(holes.get(c) or _alphabet(0x1D538, 0x1D552, 0x1D7D8)(c) for c in text)


def small_caps(text: str) -> str:
    return "".join(SMALL_CAPS[ord(c) - ord("a")] if "a" <= c <= "z" else c for c in text)


def struck(text: str) -> str:
    return "".join(c + "̶" if c.strip() else c for c in text)


def underlined(text: str) -> str:
    return "".join(c + "̲" if c.strip() else c for c in text)


Style = Callable[[str], str]
