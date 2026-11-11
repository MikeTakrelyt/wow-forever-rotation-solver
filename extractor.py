"""
Phase 1: Data Extractor for WoW Forever (Custom Level 1-60).
Extracts all class spells, ranks, unlock levels, mana costs, cast times, cooldowns,
damage/DoT/shield values, and talent trees from CASC DB2 + DBCache.bin + Local Lua data
into wow_forever.db.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from casc_wdc5 import DEFAULT_FLAVOR_DIR, DEFAULT_WOW_ROOT, WoWForeverCASC
from database import DEFAULT_DB_PATH, get_connection, init_db


SKILL_LINE_TO_CLASS: Dict[int, str] = {
    # Priest
    56: "PRIEST",
    78: "PRIEST",
    613: "PRIEST",
    # Mage
    6: "MAGE",
    8: "MAGE",
    237: "MAGE",
    # Warlock
    354: "WARLOCK",
    355: "WARLOCK",
    593: "WARLOCK",
    # Druid
    134: "DRUID",
    573: "DRUID",
    574: "DRUID",
    # Shaman
    373: "SHAMAN",
    374: "SHAMAN",
    375: "SHAMAN",
    # Paladin
    184: "PALADIN",
    267: "PALADIN",
    594: "PALADIN",
    # Hunter
    50: "HUNTER",
    51: "HUNTER",
    163: "HUNTER",
    # Rogue
    38: "ROGUE",
    39: "ROGUE",
    253: "ROGUE",
    # Warrior
    26: "WARRIOR",
    256: "WARRIOR",
    257: "WARRIOR",
}

CLASS_MASK_TO_CLASS: Dict[int, str] = {
    1: "WARRIOR",
    2: "PALADIN",
    4: "HUNTER",
    8: "ROGUE",
    16: "PRIEST",
    64: "SHAMAN",
    128: "MAGE",
    256: "WARLOCK",
    1024: "DRUID",
}


def decode_school(school_mask: int) -> str:
    if school_mask & 2:
        return "Holy"
    if school_mask & 32:
        return "Shadow"
    if school_mask & 4:
        return "Fire"
    if school_mask & 16:
        return "Frost"
    if school_mask & 8:
        return "Nature"
    if school_mask & 64:
        return "Arcane"
    return "Physical"


def parse_rank_num(rank_str: str) -> int:
    if not rank_str:
        return 0
    m = re.search(r"(\d+)", rank_str)
    return int(m.group(1)) if m else 0


def parse_saved_trainer_lua(flavor_dir: str) -> Dict[str, Dict[int, Tuple[int, int, str]]]:
    """
    Parse WTF/Account/*/SavedVariables/LevelUpInfo.lua if present.
    Returns {class_name: {spell_id: (unlock_level, cost_copper, rank_str)}}.
    """
    result: Dict[str, Dict[int, Tuple[int, int, str]]] = {}
    wtf_account_dir = os.path.join(flavor_dir, "WTF", "Account")
    if not os.path.isdir(wtf_account_dir):
        return result

    for root, _, files in os.walk(wtf_account_dir):
        if "LevelUpInfo.lua" in files:
            p = os.path.join(root, "LevelUpInfo.lua")
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Locate ["PRIEST"] = { ["levels"] = { ... } }
            for cls_match in re.finditer(
                r'\["([A-Z]+)"\]\s*=\s*\{\s*\["levels"\]\s*=\s*\{', content
            ):
                cls_name = cls_match.group(1)
                cls_dict = result.setdefault(cls_name, {})
                pos = cls_match.end()
                # Extract level blocks
                # Match [level] = { ... }
                level_blocks = re.finditer(r"\[(\d+)\]\s*=\s*\{", content[pos:])
                cur_lvl = None
                lines = content[pos:].splitlines()
                lvl_indent = None
                cur_sid = None
                cur_rank = ""
                cur_cost = 0
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith('["covered"]'):
                        break
                    m_num = re.match(r"^\[(\d+)\]\s*=\s*\{$", stripped)
                    if m_num:
                        val = int(m_num.group(1))
                        if val <= 60 and cur_sid is None:
                            cur_lvl = val
                        elif cur_lvl is not None:
                            cur_sid = val
                            cur_rank = ""
                            cur_cost = 0
                    elif cur_sid is not None:
                        m_rk = re.match(r'^\["rank"\]\s*=\s*"([^"]*)"', stripped)
                        if m_rk:
                            cur_rank = m_rk.group(1)
                        m_cost = re.match(r'^\["cost"\]\s*=\s*(\d+)', stripped)
                        if m_cost:
                            cur_cost = int(m_cost.group(1))
                        if stripped == "}," and cur_cost > 0:
                            cls_dict[cur_sid] = (cur_lvl or 1, cur_cost, cur_rank)
                            cur_sid = None
    return result


def parse_quest_spells_lua(flavor_dir: str) -> Dict[str, Dict[int, Tuple[int, int]]]:
    """
    Parse Interface/AddOns/LevelUpInfo/Data/QuestSpells.lua for WoW Forever quest/racial spells.
    Returns {class_name: {spell_id: (unlock_level, race_mask)}}.
    """
    RACE_ID_TO_MASK = {
        1: 1,    # Human
        2: 2,    # Orc
        3: 4,    # Dwarf
        4: 8,    # NightElf
        5: 16,   # Undead / Scourge
        6: 32,   # Tauren
        7: 64,   # Gnome
        8: 128,  # Troll
    }
    result: Dict[str, Dict[int, Tuple[int, int]]] = {}
    p = os.path.join(
        flavor_dir, "Interface", "AddOns", "LevelUpInfo", "Data", "QuestSpells.lua"
    )
    if not os.path.exists(p):
        return result
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    m_forever = re.search(r"QuestSpells\.forever\s*=\s*\{(.*)\}", text, re.S)
    if not m_forever:
        return result
    block = m_forever.group(1)
    cur_class = None
    cur_lvl = None
    for line in block.splitlines():
        s = line.strip()
        m_cls = re.match(r"^([A-Z]+)\s*=\s*\{", s)
        if m_cls:
            cur_class = m_cls.group(1)
            continue
        m_lvl = re.match(r"^\[(\d+)\]\s*=\s*\{", s)
        if m_lvl and cur_class:
            cur_lvl = int(m_lvl.group(1))
            continue
        m_sp = re.search(r"\{\s*id\s*=\s*(\d+)(?:,\s*races\s*=\s*\{([^}]*)\})?\s*\}", s)
        if m_sp and cur_class and cur_lvl:
            sid = int(m_sp.group(1))
            races_str = m_sp.group(2)
            rmask = 0
            if races_str:
                for rid_s in re.findall(r"\d+", races_str):
                    rmask |= RACE_ID_TO_MASK.get(int(rid_s), 0)
            result.setdefault(cur_class, {})[sid] = (cur_lvl, rmask)
    return result


def format_tooltip_description(
    raw_desc: str,
    sid: int,
    effects_by_sid: Dict[int, Dict[int, List[Any]]],
    durations_by_sid: Dict[int, int],
) -> str:
    """Resolve $s1, $o1, $d, $t1, $<spell_id>s1 placeholders in German spell descriptions."""
    if not raw_desc:
        return ""

    def get_eff_str(target_sid: int, eff_idx: int, mode: str) -> str:
        eff = effects_by_sid.get(target_sid, {}).get(eff_idx - 1)
        if not eff:
            return "?"
        base = float(eff[22])
        variance = float(eff[19])
        period = int(eff[6])
        dur_ms = durations_by_sid.get(target_sid, 0)

        if mode in ("s", "m", "w"):
            val_min = abs(base)
            val_max = abs(base * (1.0 + variance))
            if variance > 0.001 and round(val_max) > round(val_min):
                return f"{int(round(val_min))} bis {int(round(val_max))}"
            return str(int(round(val_min)))
        elif mode == "o":
            if period > 0 and dur_ms > 0:
                ticks = max(1, dur_ms // period)
                return str(int(round(abs(base) * ticks)))
            return str(int(round(abs(base))))
        elif mode == "t":
            return f"{period / 1000.0:g}" if period > 0 else "0"
        return "?"

    def get_dur_str(target_sid: int) -> str:
        dur_ms = durations_by_sid.get(target_sid, 0)
        if dur_ms <= 0:
            return "0 Sek."
        sec = dur_ms / 1000.0
        if sec >= 60 and sec % 60 == 0:
            return f"{int(sec // 60)} Min."
        return f"{sec:g} Sek."

    out = raw_desc
    # Handle $@spelldesc<id>
    m_ref = re.match(r"^\$@spelldesc(\d+)$", out.strip())
    if m_ref:
        return out

    # Handle $/1000;s1 or $/1000;S1
    def repl_div(m: re.Match) -> str:
        div_val = float(m.group(1))
        e_idx = int(m.group(2))
        eff = effects_by_sid.get(sid, {}).get(e_idx - 1)
        if not eff:
            return "0"
        val = abs(float(eff[22])) / abs(div_val)
        return f"{val:g}"

    out = re.sub(r"\$/(-?\d+);[sSmM](\d)", repl_div, out)
    out = re.sub(
        r"\$\{\$([sSmM])(\d)/(-?\d+)\}(?:\.1)?",
        lambda m: repl_div(
            re.match(r"(.*):(.*)", f"{m.group(3)}:{m.group(2)}")  # type: ignore
        ),
        out,
    )

    # Cross-spell duration $<id>d
    out = re.sub(
        r"\$(\d+)d\b",
        lambda m: get_dur_str(int(m.group(1))),
        out,
    )
    # Cross-spell effect $<id>[sSoOmMwWtT]<idx>
    out = re.sub(
        r"\$(\d+)([sSoOmMwWtT])(\d)\b",
        lambda m: get_eff_str(int(m.group(1)), int(m.group(3)), m.group(2).lower()),
        out,
    )
    # Local duration $d
    out = re.sub(r"\$d\b", lambda _: get_dur_str(sid), out)
    # Local effect $[sSoOmMwWtT]<idx>
    out = re.sub(
        r"\$([sSoOmMwWtT])(\d)\b",
        lambda m: get_eff_str(sid, int(m.group(2)), m.group(1).lower()),
        out,
    )
    # Gender/plural $lSingular:Plural;
    out = re.sub(r"\$l([^:;]+):([^;]+);", r"\2", out)
    return out


def extract_all(
    wow_root: str = DEFAULT_WOW_ROOT,
    flavor_dir: str = DEFAULT_FLAVOR_DIR,
    db_path: str = DEFAULT_DB_PATH,
) -> Tuple[int, int]:
    """Run full extraction from WoW Forever client data into wow_forever.db."""
    print(f"[Extractor] Initialisiere CASC & DB2Meta Reader aus {flavor_dir} ...")
    casc = WoWForeverCASC(wow_root=wow_root, flavor_dir=flavor_dir)

    print("[Extractor] Lese WDC5-Tabellen & DBCache.bin Hotfixes ...")
    spell_names = casc.parse_table("SpellName")
    spells = casc.parse_table("Spell")
    spell_effects = casc.parse_table("SpellEffect")
    spell_misc = casc.parse_table("SpellMisc")
    spell_power = casc.parse_table("SpellPower")
    spell_cd = casc.parse_table("SpellCooldowns")
    spell_levels = casc.parse_table("SpellLevels")
    cast_times = casc.parse_table("SpellCastTimes")
    durations = casc.parse_table("SpellDuration")
    skill_abilities = casc.parse_table("SkillLineAbility")
    talents = casc.parse_table("Talent")
    talent_tabs = casc.parse_table("TalentTab")

    saved_trainers = parse_saved_trainer_lua(flavor_dir)
    quest_spells = parse_quest_spells_lua(flavor_dir)

    # Index records by SpellID (parent FK at v[-1])
    misc_by_sid: Dict[int, List[Any]] = {}
    for v in spell_misc.values():
        misc_by_sid[int(v[-1])] = v

    power_by_sid: Dict[int, List[Any]] = {}
    for v in spell_power.values():
        sid = int(v[-1])
        # Prefer Mana (PowerType == 0) or higher ManaCost
        if sid not in power_by_sid or (v[1] == 0 and v[2] > power_by_sid[sid][2]):
            power_by_sid[sid] = v

    cd_by_sid: Dict[int, List[Any]] = {}
    for v in spell_cd.values():
        cd_by_sid[int(v[-1])] = v

    levels_by_sid: Dict[int, List[Any]] = {}
    for v in spell_levels.values():
        levels_by_sid[int(v[-1])] = v

    effects_by_sid: Dict[int, Dict[int, List[Any]]] = {}
    for v in spell_effects.values():
        sid = int(v[-1])
        eff_idx = int(v[2])
        effects_by_sid.setdefault(sid, {})[eff_idx] = v

    durations_by_sid: Dict[int, int] = {}
    for sid, m in misc_by_sid.items():
        dur_idx = int(m[3])
        if dur_idx in durations:
            durations_by_sid[sid] = int(durations[dur_idx][0])

    # Build Talent table rows & track talent-unlocked spells
    init_db(db_path=db_path, reset=True)
    conn = get_connection(db_path)

    talent_unlocked_spells: Dict[int, Tuple[int, str, int]] = {}
    # {spell_id: (talent_id, class_name, min_char_level)}
    talent_rows: List[Tuple[Any, ...]] = []

    for tid, tv in sorted(talents.items(), key=lambda x: (x[1][4], x[1][1], x[1][3])):
        tab_id = int(tv[4])
        if tab_id not in talent_tabs:
            continue
        tab_info = talent_tabs[tab_id]
        tab_name = str(tab_info[0])
        class_mask = int(tab_info[5])
        class_name = CLASS_MASK_TO_CLASS.get(class_mask)
        if not class_name:
            continue

        tier = int(tv[1])
        col = int(tv[3])
        rank_sids = [int(s) for s in tv[11] if int(s) != 0]
        if not rank_sids:
            continue

        r0 = rank_sids[0]
        if r0 not in spell_names:
            continue
        t_name = str(spell_names[r0][0])
        max_rank = len(rank_sids)
        last_sid = rank_sids[-1]
        raw_desc = str(spells.get(r0, ["", ""])[1])
        desc_formatted = format_tooltip_description(
            raw_desc, r0, effects_by_sid, durations_by_sid
        )

        # Check if this 1-rank talent unlocks an active spell (e.g. Gedankenschinden 15407, Schattengestalt 15473)
        unlocks_sid: Optional[int] = None
        m_r0 = misc_by_sid.get(r0)
        is_passive = True
        if m_r0:
            attrs0 = int(m_r0[0][0])
            is_passive = (attrs0 & 0x40) != 0
        if not is_passive and max_rank == 1:
            unlocks_sid = r0
            min_lvl = 10 + tier * 5
            talent_unlocked_spells[r0] = (tid, class_name, min_lvl)

        # Summarize per-rank effect base values for the solver
        rank_effects_summary = []
        for r_sid in rank_sids:
            eff_map = effects_by_sid.get(r_sid, {})
            rank_effects_summary.append(
                {
                    str(idx): {
                        "aura": int(e[0]),
                        "effect": int(e[3]),
                        "base": float(e[22]),
                        "misc": e[26],
                    }
                    for idx, e in sorted(eff_map.items())
                }
            )

        prereq_tid = int(tv[12][0]) if tv[12][0] else None
        prereq_rk = int(tv[13][0]) if tv[13][0] else 0

        talent_rows.append(
            (
                tid,
                class_name,
                tab_id,
                tab_name,
                tier,
                col,
                t_name,
                max_rank,
                json.dumps(rank_sids),
                unlocks_sid,
                prereq_tid,
                prereq_rk,
                json.dumps(rank_effects_summary),
                desc_formatted,
            )
        )

    # Also propagate talent requirement to higher ranks of talent-unlocked spells (e.g. Gedankenschinden R2-R6, Heilige Nova R2-R6)
    talent_by_spell_name: Dict[Tuple[str, str], int] = {}
    for sid, (tid, cls_name, _) in list(talent_unlocked_spells.items()):
        nm = str(spell_names.get(sid, [""])[0])
        if nm:
            talent_by_spell_name[(cls_name, nm)] = tid

    # Collect candidate class spells from SkillLineAbility + QuestSpells + SavedTrainers
    # First map (skill_line_id, icon_fdid) -> canonical Rank 2+ spell name to fix Retail Rank 1 renames (e.g. 585 Heilige Pein -> Göttliche Pein)
    canonical_name_by_line_icon: Dict[Tuple[int, int], str] = {}
    for sla in skill_abilities.values():
        sl_id = int(sla[3])
        if sl_id not in SKILL_LINE_TO_CLASS:
            continue
        sid = int(sla[4])
        rk_str = str(spells.get(sid, [""])[0])
        rk_num = parse_rank_num(rk_str)
        m = misc_by_sid.get(sid)
        if rk_num == 2 and m and sid in spell_names:
            icon_fdid = int(m[10])
            if icon_fdid > 0:
                canonical_name_by_line_icon[(sl_id, icon_fdid)] = str(
                    spell_names[sid][0]
                )

    raw_candidates: List[Dict[str, Any]] = []
    seen_sids: Set[int] = set()

    for sla in skill_abilities.values():
        sl_id = int(sla[3])
        cls_name = SKILL_LINE_TO_CLASS.get(sl_id)
        if not cls_name:
            continue
        sid = int(sla[4])
        if sid in seen_sids or sid not in spell_names:
            continue
        seen_sids.add(sid)

        race_mask_arr = sla[17] if isinstance(sla[17], list) else [0, 0]
        race_mask = int(race_mask_arr[0]) if race_mask_arr[0] > 0 else 0
        raw_candidates.append(
            {
                "spell_id": sid,
                "class_name": cls_name,
                "skill_line_id": sl_id,
                "race_mask": race_mask,
            }
        )

    # Ensure all QuestSpells.lua and SavedTrainer spells are included
    # Map (class_name, spell_name) -> race_mask from QuestSpells.lua and known racial spells
    RACIAL_SPELL_MASKS: Dict[Tuple[str, str], int] = {
        ("PRIEST", "Verschlingende Seuche"): 16,      # Undead
        ("PRIEST", "Dunkles Opfer"): 16,              # Undead
        ("PRIEST", "Berührung der Schwäche"): 144,    # Undead (16) | Troll (128)
        ("PRIEST", "Verhexung der Schwäche"): 128,    # Troll
        ("PRIEST", "Schattenschild"): 128,            # Troll
        ("PRIEST", "Sternensplitter"): 8,             # Night Elf
        ("PRIEST", "Elunes Anmut"): 8,                # Night Elf
        ("PRIEST", "Züchtigung"): 4,                  # Dwarf
        ("PRIEST", "Verzweifeltes Gebet"): 5,         # Human (1) | Dwarf (4)
        ("PRIEST", "Rückkopplung"): 1,                # Human
        ("PRIEST", "Göttliche Anmut"): 1,             # Human
        ("PRIEST", "Verwirrender Lichtblitz"): 64,    # Gnome
        ("PRIEST", "Notfallplan"): 64,                # Gnome
    }
    for cls_name, q_map in quest_spells.items():
        for sid, (q_lvl, q_rmask) in q_map.items():
            if sid in spell_names and q_rmask > 0:
                nm = str(spell_names[sid][0])
                RACIAL_SPELL_MASKS[(cls_name, nm)] = (
                    RACIAL_SPELL_MASKS.get((cls_name, nm), 0) | q_rmask
                )
            if sid not in seen_sids and sid in spell_names:
                seen_sids.add(sid)
                raw_candidates.append(
                    {
                        "spell_id": sid,
                        "class_name": cls_name,
                        "skill_line_id": 56 if cls_name == "PRIEST" else 0,
                        "race_mask": q_rmask,
                    }
                )

    # Build enriched spell objects and filter out passives/dummys
    grouped_candidates: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = {}

    for cand in raw_candidates:
        sid = cand["spell_id"]
        cls_name = cand["class_name"]
        sl_id = cand["skill_line_id"]
        race_mask = cand["race_mask"]

        m = misc_by_sid.get(sid)
        if not m:
            continue
        attrs = m[0]
        attrs0 = int(attrs[0])
        attrs1 = int(attrs[1])
        # Skip passive spells
        if (attrs0 & 0x40) != 0:
            continue

        icon_fdid = int(m[10])
        raw_name = str(spell_names[sid][0])
        sp_rec = spells.get(sid, ["", "", ""])
        rank_str = str(sp_rec[0] or "").strip()
        rank_num = parse_rank_num(rank_str)

        # Normalize Rank 1 name if Rank 2 with same (skill_line_id, icon_fdid) has Classic name (e.g. Göttliche Pein)
        if rank_num == 1 and (sl_id, icon_fdid) in canonical_name_by_line_icon:
            canon_name = canonical_name_by_line_icon[(sl_id, icon_fdid)]
            if canon_name != raw_name:
                raw_name = canon_name

        if (cls_name, raw_name) in RACIAL_SPELL_MASKS:
            race_mask = RACIAL_SPELL_MASKS[(cls_name, raw_name)]

        # Determine unlock level: BaseLevel > 0 in SpellLevels.db2 (or Talent / QuestSpells / SavedTrainer)
        lvl_rec = levels_by_sid.get(sid)
        base_lvl = int(lvl_rec[3]) if lvl_rec else 0
        unlock_level = base_lvl

        # Override/confirm with QuestSpells.lua or SavedVariables/LevelUpInfo.lua
        if cls_name in quest_spells and sid in quest_spells[cls_name]:
            q_lvl, q_rmask = quest_spells[cls_name][sid]
            if unlock_level <= 0:
                unlock_level = q_lvl
            if q_rmask > 0:
                race_mask = q_rmask

        is_trainer_confirmed = 0
        trainer_cost = 0
        if cls_name in saved_trainers and sid in saved_trainers[cls_name]:
            t_lvl, t_cost, t_rk = saved_trainers[cls_name][sid]
            unlock_level = t_lvl
            is_trainer_confirmed = 1
            trainer_cost = t_cost
            if not rank_str and t_rk:
                rank_str = t_rk
                rank_num = parse_rank_num(rank_str)

        req_talent_id = talent_by_spell_name.get((cls_name, raw_name))
        if sid in talent_unlocked_spells:
            req_talent_id, _, t_min_lvl = talent_unlocked_spells[sid]
            if unlock_level <= 0:
                unlock_level = t_min_lvl

        # Skip unlearnable dummy/proc spells with unlock_level <= 0
        if unlock_level <= 0 or unlock_level > 60:
            continue

        # Cast time, duration, school, channeled
        ct_idx = int(m[2])
        cast_time_ms = int(cast_times.get(ct_idx, [0])[0])
        if cast_time_ms < 0:
            cast_time_ms = 0

        dur_ms = durations_by_sid.get(sid, 0)
        school_str = decode_school(int(m[6]))
        is_channeled = 1 if (attrs1 & 0x44) != 0 else 0

        # Power / Mana cost
        pwr = power_by_sid.get(sid)
        has_power = pwr is not None
        mana_cost = int(pwr[2]) if pwr else 0

        # Cooldown & GCD
        cd_rec = cd_by_sid.get(sid)
        cat_cd = int(cd_rec[1]) if cd_rec else 0
        rec_cd = int(cd_rec[2]) if cd_rec else 0
        cooldown_ms = max(cat_cd, rec_cd)
        gcd_ms = int(cd_rec[3]) if (cd_rec and int(cd_rec[3]) > 0) else 1500

        # Extract effects (Direct Damage, Periodic Damage, Absorb, Channel salvos, Triggered procs)
        eff_map = effects_by_sid.get(sid, {})
        direct_min = 0.0
        direct_max = 0.0
        dot_total = 0.0
        dot_dur_ms = 0
        tick_ms = 0
        absorb_val = 0.0

        raw_desc = str(sp_rec[1] or "")

        for idx, eff in sorted(eff_map.items()):
            aura_type = int(eff[0])
            eff_type = int(eff[3])
            period = int(eff[6])
            rpl = float(eff[14])
            variance = float(eff[19])
            base = float(eff[22])

            if eff_type == 2 and base > 0:  # School Damage
                d_min = base
                d_max = base * (1.0 + variance)
                direct_min += d_min
                direct_max += d_max
            elif eff_type == 6:  # Apply Aura
                if aura_type in (3, 53) and base > 0:  # Periodic Damage / Leech
                    tick_ms = period if period > 0 else 3000
                    dot_dur_ms = dur_ms if dur_ms > 0 else 18000
                    num_ticks = max(1, dot_dur_ms // tick_ms)
                    dot_total += base * num_ticks
                elif aura_type == 69 and base > 0:  # School Absorb (PW:S)
                    absorb_val += base

        # Special resolution for spells referencing sub-spell damage in description:
        # 1. Sühne (Penance): channeled salvo firing 3 bolts over 2000ms
        if raw_name == "Sühne":
            m_bolt = re.search(r"\$(\d+)s1\s+Heiligschaden", raw_desc)
            if m_bolt:
                bolt_sid = int(m_bolt.group(1))
                bolt_eff = effects_by_sid.get(bolt_sid, {}).get(0)
                if bolt_eff:
                    bolt_base = float(bolt_eff[22])
                    # Sühne channels 402261 (2000ms, 3 bolts: 0s, 1s, 2s)
                    is_channeled = 1
                    dot_dur_ms = 2000
                    tick_ms = 1000
                    dot_total = bolt_base * 3.0

        # 2. Berührung der Schwäche (Touch of Weakness): 1 charge on-hit Shadow damage
        elif raw_name == "Berührung der Schwäche":
            m_proc = re.search(r"\$(\d+)s1\s+Schattenschaden", raw_desc)
            if m_proc:
                proc_sid = int(m_proc.group(1))
                proc_eff = effects_by_sid.get(proc_sid, {}).get(0)
                if proc_eff:
                    p_base = float(proc_eff[22])
                    direct_min = p_base
                    direct_max = p_base

        # 3. Schattenschild (Shadowguard): 3 charges on-hit Shadow damage
        elif raw_name == "Schattenschild":
            m_proc = re.search(r"\$(\d+)s1\s+Punkt", raw_desc)
            if m_proc:
                proc_sid = int(m_proc.group(1))
                proc_eff = effects_by_sid.get(proc_sid, {}).get(0)
                if proc_eff:
                    p_base = float(proc_eff[22])
                    # 3 charges stored as periodic/reactive damage over fight
                    dot_total = p_base * 3.0
                    dot_dur_ms = 9000
                    tick_ms = 3000

        # Classify spell_category
        total_offensive = (direct_min + direct_max) / 2.0 + dot_total
        if absorb_val > 0:
            spell_category = "shield"
        elif raw_name in ("Berührung der Schwäche", "Schattenschild"):
            spell_category = "prepull_buff"
        elif total_offensive > 0:
            if raw_name == "Heilige Nova":
                spell_category = "aoe_damage"
            elif is_channeled:
                spell_category = "channel_damage"
            elif direct_min > 0 and dot_total > 0:
                spell_category = "hybrid_damage"
            elif dot_total > 0:
                spell_category = "dot_damage"
            else:
                spell_category = "direct_damage"
        elif raw_name in ("Dunkles Opfer", "Innerer Fokus", "Seele der Macht", "Schattengestalt"):
            spell_category = "combat_buff"
        else:
            spell_category = "utility"

        desc_formatted = format_tooltip_description(
            raw_desc, sid, effects_by_sid, durations_by_sid
        )

        item = {
            "spell_id": sid,
            "class_name": cls_name,
            "name": raw_name,
            "rank": rank_str,
            "rank_num": rank_num,
            "unlock_level": unlock_level,
            "school": school_str,
            "cast_time_ms": cast_time_ms,
            "cooldown_ms": cooldown_ms,
            "gcd_ms": gcd_ms,
            "mana_cost": mana_cost,
            "direct_dmg_min": round(direct_min, 2),
            "direct_dmg_max": round(direct_max, 2),
            "dot_dmg_total": round(dot_total, 2),
            "dot_duration_ms": dot_dur_ms,
            "tick_interval_ms": tick_ms,
            "absorb_amount": round(absorb_val, 2),
            "is_channeled": is_channeled,
            "requires_talent_id": req_talent_id,
            "race_mask": race_mask,
            "skill_line_id": sl_id,
            "icon_fdid": icon_fdid,
            "spell_category": spell_category,
            "is_trainer_confirmed": is_trainer_confirmed,
            "trainer_cost_copper": trainer_cost,
            "description_raw": desc_formatted,
            "_has_power": has_power,
        }
        grouped_candidates.setdefault((cls_name, raw_name, rank_num), []).append(item)

    # Deduplicate (class_name, name, rank_num) -> keep the real castable player spell
    final_spells: List[Dict[str, Any]] = []
    for key, group in grouped_candidates.items():
        group.sort(
            key=lambda x: (
                -x["is_trainer_confirmed"],
                -(1 if x["_has_power"] else 0),
                -(1 if x["mana_cost"] > 0 else 0),
                -(1 if (x["direct_dmg_min"] + x["dot_dmg_total"] + x["absorb_amount"]) > 0 else 0),
                x["spell_id"],
            )
        )
        final_spells.append(group[0])

    final_spells.sort(key=lambda x: (x["class_name"], x["unlock_level"], x["name"], x["rank_num"]))

    with conn:
        conn.executemany(
            """
            INSERT INTO wf_talents (
                talent_id, class_name, tab_id, tab_name, tier, col, name,
                max_rank, rank_spell_ids_json, unlocks_spell_id,
                prereq_talent_id, prereq_rank, effect_summary_json, description_raw
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            talent_rows,
        )
        conn.executemany(
            """
            INSERT INTO wf_spells (
                spell_id, class_name, name, rank, rank_num, unlock_level, school,
                cast_time_ms, cooldown_ms, gcd_ms, mana_cost,
                direct_dmg_min, direct_dmg_max, dot_dmg_total, dot_duration_ms,
                tick_interval_ms, absorb_amount, is_channeled, requires_talent_id,
                race_mask, skill_line_id, icon_fdid, spell_category,
                is_trainer_confirmed, trainer_cost_copper, description_raw
            ) VALUES (
                :spell_id, :class_name, :name, :rank, :rank_num, :unlock_level, :school,
                :cast_time_ms, :cooldown_ms, :gcd_ms, :mana_cost,
                :direct_dmg_min, :direct_dmg_max, :dot_dmg_total, :dot_duration_ms,
                :tick_interval_ms, :absorb_amount, :is_channeled, :requires_talent_id,
                :race_mask, :skill_line_id, :icon_fdid, :spell_category,
                :is_trainer_confirmed, :trainer_cost_copper, :description_raw
            )
            """,
            final_spells,
        )
    conn.close()
    print(
        f"[Extractor] Fertig! {len(final_spells)} Zauber und {len(talent_rows)} Talente in {db_path} gespeichert."
    )
    return len(final_spells), len(talent_rows)


if __name__ == "__main__":
    extract_all()
