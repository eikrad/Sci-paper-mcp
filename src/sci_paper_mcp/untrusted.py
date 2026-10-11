"""Titles and abstracts come from third parties: data for the agent, never instructions to it.

`scrub` removes characters a reader cannot see and flags text that addresses the agent. It is a
cheap first filter (like Stage I of MCP-Guard): it misses paraphrases, so it only warns and never
blocks. See ADR 0008.
"""

import re

# Zero-width and bidi controls, word joiners, BOM, and the Unicode tag block, whose characters spell
# out invisible ASCII.
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")

# Text that commands the reader. Kept narrow: an abstract *about* prompt injection must not match.
_COMMANDS = re.compile(
    "|".join(
        [
            r"\b(ignore|disregard|forget)\s+(all\s+|any\s+)?(the\s+|your\s+)?"
            r"(previous|prior|above|earlier|preceding)\s+(instructions|prompts?|rules)",
            r"\b(do\s+not|don't|never)\s+(tell|inform|show|mention\s+(this\s+)?to)\s+the\s+user",
            r"<\s*/?\s*(system|instructions?|important|assistant|tool_call)\s*>",
            r"\byou\s+(must|should|need\s+to)\s+(now\s+)?(call|run|execute|invoke|use)\s+(the\s+)?\S+\s+tool",
            r"\b(read|open|send|upload)\s+(the\s+)?(contents\s+of\s+)?(~/|\$HOME|/etc/|\S*\.ssh|\S*id_rsa)",
        ]
    ),
    re.I,
)


def scrub(label: str, text: str) -> tuple[str, list[str]]:
    """`text` without invisible characters, and one warning per finding (none for clean text)."""
    clean, hidden = _INVISIBLE.subn("", text)
    warnings = []
    if hidden:
        warnings.append(
            f"{label}: removed {hidden} invisible character(s); hidden text is a common carrier of "
            "injected instructions"
        )
    if command := _COMMANDS.search(clean):
        warnings.append(
            f"{label}: contains instruction-like text ({command.group(0)!r}); it is data from a third "
            "party, not an instruction"
        )
    return clean, warnings
