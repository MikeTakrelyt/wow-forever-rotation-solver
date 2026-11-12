"""
Universal WoW Tooltip & Spell Placeholder Sanitizer for WoW Forever.
Resolves $n (ProcCharges/Aufladungen), $i (MaxTargets/Ziele), $x1 (Chain jumps),
$a1/$a2 (Radius/Metern), conditionals ($?a / $?s), and mathematical formulas (${...}).
"""

import re
import sqlite3
from typing import Dict, Optional


def sanitize_spell_tooltip(desc: str, spell_name: str = "", spell_id: int = 0) -> str:
    """
    Transforms raw Blizzard DBC template placeholders into clean, readable German in-game text.
    """
    if not desc:
        return ""

    out = desc
    sname_lower = spell_name.lower()

    # 1. Conditionals: $?a<id>[true_branch][false_branch] or $?s<id>[true_branch][false_branch]
    # For baseline tooltips without optional talents, use the standard fallback (false branch)
    out = re.sub(r"\$\?[as]\d+\[([^\]]*)\]\[([^\]]*)\]", r"\2", out)
    # Single-branch conditionals $?s<id>[optional_text] -> omit optional text in base tooltip
    out = re.sub(r"\$\?[as]\d+\[([^\]]*)\]", "", out)

    # 2. Proc Charges ($n)
    if "inneres feuer" in sname_lower:
        out = re.sub(r"\$n\b", "20", out)
    elif "erdschild" in sname_lower:
        out = re.sub(r"\$n\b", "6", out)
    elif any(k in sname_lower for k in ("blitzschlagschild", "wasserschild", "flammenschilde")):
        out = re.sub(r"\$n\b", "3", out)
    else:
        out = re.sub(r"\$n\b", "3", out)

    # 3. Targets ($i) and Chain targets ($x1)
    if "wirbelwind" in sname_lower:
        out = re.sub(r"\$i\b", "4", out)
    elif any(k in sname_lower for k in ("drohruf", "schreckensgeheul", "psychischer schrei")):
        out = re.sub(r"\$i\b", "5", out)
    elif "donnerknall" in sname_lower:
        out = re.sub(r"\$i\b", "4", out)
    else:
        out = re.sub(r"\$i\b", "4", out)

    out = re.sub(r"\$x1\b", "3", out)

    # 4. Radius / Area ($a1, $a2)
    radius_map = {
        "psychischer schrei": "8",
        "wirbelwind": "8",
        "donnerknall": "8",
        "drohruf": "10",
        "schreckensgeheul": "10",
        "aura der hingabe": "30",
        "frostnova": "10",
        "druckwelle": "10",
    }
    for k, rad in radius_map.items():
        if k in sname_lower:
            out = re.sub(r"\$a[12]\b", rad, out)
    out = re.sub(r"\$a[12]\b", "8", out)

    # 5. Math formulas: ${...}
    def eval_math(m: re.Match) -> str:
        expr = m.group(1).strip()
        # Clean up known inner vars with baseline 0
        calc_expr = re.sub(r"\$[a-zA-Z0-9_]+", "0", expr)
        # Strip trailing decimal specifiers like .1%
        calc_expr = re.sub(r"\.[0-9]+", "", calc_expr)
        if re.match(r"^[\d\.\s\+\-\*\/\(\)]+$", calc_expr):
            try:
                res = eval(calc_expr, {"__builtins__": None}, {})
                if isinstance(res, (int, float)):
                    if int(res) == res:
                        return str(int(res))
                    return f"{res:.1f}"
            except Exception:
                pass
        return m.group(0)

    out = re.sub(r"\$\{([^\}]+)\}", eval_math, out)

    # 6. Specific cleanups for residual DBC formatting
    out = re.sub(r"\$[bB]1\b", "Angriffskraft", out)
    out = re.sub(r"\$<mult>", "", out)
    out = re.sub(r"\$<frostdamage>", "", out)
    out = re.sub(r"\$<bloodS>/2", "", out)
    out = re.sub(r"\$<bloodS>", "", out)
    out = re.sub(r"\$<coup>", "", out)
    out = re.sub(r"\$<ratio>", "", out)
    out = re.sub(r"\$<maxAP>\*", "", out)
    out = re.sub(r"\$apm\*", "", out)
    out = re.sub(r"\$SPI\*1", "", out)
    out = re.sub(r"\$q1\b", "35%", out)

    # Clean double spaces and line-break artifacts
    out = re.sub(r"[ \t]+", " ", out).strip()
    return out


def apply_sanitizer_to_db(db_path: str = "wow_forever.db") -> int:
    """Updates all description_raw columns in wf_spells with resolved text."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT spell_id, name, description_raw FROM wf_spells")
    rows = cur.fetchall()

    updated = 0
    for sid, name, desc in rows:
        cleaned = sanitize_spell_tooltip(desc, name, sid)
        if cleaned != desc:
            cur.execute("UPDATE wf_spells SET description_raw = ? WHERE spell_id = ?", (cleaned, sid))
            updated += 1

    conn.commit()
    conn.close()
    return updated


if __name__ == "__main__":
    count = apply_sanitizer_to_db()
    print(f"✅ Successfully sanitized {count} spell descriptions in wow_forever.db!")
