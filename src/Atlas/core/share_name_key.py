from __future__ import annotations

import re
import unicodedata


_SUFFIX_RE = re.compile(r"^([a-z]+)(iii|ii|iv|v|jr|sr)$", re.I)
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _strip_diacritics(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def share_name_key(x: str) -> str:
    """Canonical player key for share-matrix joins."""
    s = str(x or "").strip()
    if not s:
        return ""

    s = _strip_diacritics(s)
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace(".", " ")
    s = str(s or "").strip()

    if "," in s:
        last, first = s.split(",", 1)
        s = f"{first.strip()} {last.strip()}".strip()

    suffixes = {"jr", "sr", "ii", "iii", "iv", "v"}
    parts = [p for p in s.replace("’", "'").split() if p]
    if parts and parts[-1].lower().strip(".") in suffixes:
        parts = parts[:-1]
    s = " ".join(parts)

    if "," in s:
        last, first = [t.strip() for t in s.split(",", 1)]
        last = _CAMEL_SPLIT_RE.sub(" ", last)
        s = f"{first} {last}"

    s = re.sub(r"[^A-Za-z0-9\s'-]", " ", s)
    s = s.replace("-", " ").replace("'", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()

    toks = s.split()

    fixed: list[str] = []
    for t in toks:
        m = _SUFFIX_RE.match(t)
        if m:
            fixed.extend([m.group(1).lower(), m.group(2).lower()])
        else:
            fixed.append(t)

    return " ".join(fixed)