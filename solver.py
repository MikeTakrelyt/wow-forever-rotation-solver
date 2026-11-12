"""
Phase 2: Mathematical Rotation Solver for WoW Forever (Custom Level 1-60).
Calculates DPCT, DPM, Weighted Score, Active Talent Modifiers, Frontloaded Combat Sequence
(Pre-Pull, Pull/Opener, Core Priority, 5-Second Rule / Wand Finisher), and Trainer Previews
strictly from the extracted wow_forever.db data.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from database import DEFAULT_DB_PATH, query_class_quests, query_spells, query_talents, query_wands


MODE_WEIGHTS: Dict[str, Tuple[float, float]] = {
    "burst": (0.80, 0.20),              # 80% DPCT, 20% DPM
    "leveling_balanced": (0.50, 0.50),  # 50% DPCT, 50% DPM
    "mana_saver": (0.25, 0.75),         # 25% DPCT, 75% DPM
}

RACE_OPTIONS: Dict[str, int] = {
    "Untoter (Scourge)": 16,
    "Troll": 128,
    "Mensch (Human)": 1,
    "Zwerg (Dwarf)": 4,
    "Nachtelf (Night Elf)": 8,
    "Gnom (Gnome)": 64,
    "Alle Völker anzeigen": 0xFFFF,
}


def get_recommended_wand(
    level: int,
    wand_dmg_mult: float = 1.0,
    db_path: str = DEFAULT_DB_PATH,
) -> Tuple[float, Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Look up the official WoW Forever wands available up to `level` from `wf_wands`
    (synced from the official Blizzard Game Data API) and scale DPS by `wand_dmg_mult`
    (Zauberstab-Spezialisierung: Rank 1 = +13%, Rank 2 = +25%).
    """
    wands = query_wands(max_level=level, db_path=db_path)
    if wands:
        # wands are ordered by required_level DESC, dps DESC, item_level DESC
        # Pick the highest DPS wand available at or below current_level
        best_wand = max(wands, key=lambda w: (w["dps"], w["required_level"]))
        rec = dict(best_wand)
        rec["effective_dps"] = round(rec["dps"] * wand_dmg_mult, 2)
        return rec["effective_dps"], rec, wands

    if level < 5:
        return 0.0, None, []
    base_dps = 6.5 + (level * 0.95) + ((level ** 1.25) * 0.08)
    return round(base_dps * wand_dmg_mult, 2), None, []


def allocate_talents_for_level(
    class_name: str,
    current_level: int,
    spec_profile: str = "auto",
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Allocate available talent points (1 point per level starting at Level 10, up to 51 points at Level 60)
    using the official Blizzard API talent trees stored in wf_talents (`static-forever-eu`).
    Returns active talent ranks, unlocked spell IDs, and numerical modifiers.
    """
    total_points = max(0, min(60, current_level) - 9)
    all_talents = query_talents(class_name, db_path=db_path)
    talent_by_id = {t["talent_id"]: t for t in all_talents}

    allocated: Dict[int, int] = {}  # talent_id -> rank
    points_left = total_points

    if class_name.upper() == "PRIEST" and total_points > 0:
        # Official Blizzard API Node IDs for WoW Forever Priest (/data/wow/talent-tree/1114):
        if spec_profile == "holy_smite":
            # Discipline Wand Spec 2/2 (105850) + Macht im Licht (110853) + Göttlicher Furor (105863) + Sühne (105834)
            priority_order = [
                (105850, 2),  # T0 Disc: Zauberstab-Spezialisierung 2/2 (+13% / +25% Wand dmg)
                (110853, 3),  # T0 Disc: Macht im Licht 3/5 (+6% Smite & Penance dmg)
                (105863, 5),  # T1 Holy: Göttlicher Furor 5/5 (-0.5s Smite/Holy Fire cast time)
                (110855, 5),  # T0 Holy: Heiligspezialisierung 5/5 (+5% Holy crit)
                (105862, 1),  # T1 Holy: Heilige Nova 1/1 (AoE unlock)
                (105858, 3),  # T2 Holy: Verbesserte Heilung 3/3 (-15% mana on heals & Penance)
                (105857, 2),  # T2 Holy: Sengendes Licht 2/2 (+5% Holy dmg)
                (105859, 2),  # T2 Holy: Heilige Reichweite 2/2 (+20% Holy range)
                (105849, 3),  # T0 Disc: Zwillingsdisziplinen 3/5 (+3% Instant dmg/heal)
                (105846, 3),  # T1 Disc: Verbessertes Machtwort: Schild 3/3 (+20% Absorb)
                (105842, 3),  # T1 Disc: Mentale Beweglichkeit 3/3 (-10% Mana on Smite, Holy Fire, Instants)
                (105843, 3),  # T2 Disc: Meditation 3/3 (50% mana regen while casting)
                (105844, 1),  # T2 Disc: Innerer Fokus 1/1
                (105839, 1),  # T3 Disc: Seelenwehr 1/1 (-4s CD & -15% Mana on PW:S)
                (110853, 5),  # T0 Disc: Finish Macht im Licht 5/5 (+10% Smite & Penance dmg)
                (105834, 1),  # T4 Disc: Sühne 1/1 (Unlocks Penance 402174!)
                (105853, 5),  # T4 Holy: Geistige Führung 5/5
                (105837, 5),  # T1 Disc: Mentale Stärke 5/5 (+10% Intellect)
                (105836, 1),  # T6 Disc: Seele der Macht 1/1
            ]
        else:
            # Default 'auto' / 'shadow_leveling' using official WoW Forever node IDs:
            # Zauberstab-Spezialisierung (105850) has max_rank=2 (+13% / +25% Wand dmg)!
            if current_level >= 40:
                # At Level 40+, 30 points in Shadow + 31st point in Schattengestalt (105817) (-50% Shadow mana & +10% Shadow dmg!)
                priority_order = [
                    (105833, 5),  # T0 Shadow: Willensentzug 5/5 (5 pts)
                    (105830, 2),  # T1 Shadow: Verbessertes Schattenwort: Schmerz 2/2 (7 pts)
                    (105831, 3),  # T1 Shadow: Verbesserter Gedankenschlag 3/5 (10 pts)
                    (105826, 1),  # T2 Shadow: Gedankenschinden 1/1 (11 pts)
                    (105825, 2),  # T2 Shadow: Verbessertes Gedankenschinden 2/2 (13 pts)
                    (105829, 2),  # T1 Shadow: Schattenreichweite 2/2 (15 pts)
                    (105820, 1),  # T3 Shadow: Vampirumarmung 1/1 (16 pts)
                    (105821, 3),  # T3 Shadow: Schattenwirken 3/3 (19 pts)
                    (105831, 5),  # T1 Shadow: Finish Verbesserter Gedankenschlag 5/5 (21 pts)
                    (105819, 2),  # T4 Shadow: Verschlingende Ansteckung 2/2 (23 pts)
                    (110854, 2),  # T4 Shadow: Vorzeitiges Ableben 2/2 (25 pts)
                    (105818, 5),  # T5 Shadow: Dunkelheit 5/5 (30 pts)
                    (105817, 1),  # T6 Shadow: Schattengestalt 1/1 (31 pts -> Unlocked at Level 40!)
                    # Remaining points (Lv 41-60) into Discipline:
                    (105850, 2),  # T0 Disc: Zauberstab-Spezialisierung 2/2 (+25% Wand dmg)
                    (105849, 5),  # T0 Disc: Zwillingsdisziplinen 5/5 (+5% Instant dmg/heal)
                    (105846, 3),  # T1 Disc: Verbessertes Machtwort: Schild 3/3 (+20% Absorb)
                    (105842, 3),  # T1 Disc: Mentale Beweglichkeit 3/3 (-10% Instant/Smite/HF mana)
                    (105843, 3),  # T2 Disc: Meditation 3/3 (50% Spirit regen while casting)
                    (105844, 1),  # T2 Disc: Innerer Fokus 1/1
                    (105839, 1),  # T3 Disc: Seelenwehr 1/1 (-4s CD & -15% Mana on PW:S)
                    (105837, 2),  # T1 Disc: Mentale Stärke 2/5
                ]
            else:
                # Lv 10-39 Optimal Leveling Progression:
                # Lv 10-11: Zauberstab-Spezialisierung 2/2 (+13% / +25% Wand dmg)
                # Lv 12-16: Willensentzug 5/5
                # Lv 17-18: Verbessertes Schattenwort: Schmerz 2/2
                # Lv 19-21: Verbesserter Gedankenschlag 3/5
                # Lv 22:    Gedankenschinden 1/1
                # Lv 23-24: Verbessertes Gedankenschinden 2/2
                # Lv 25-26: Schattenreichweite 2/2
                # Lv 27:    Vampirumarmung 1/1
                # Lv 28-30: Schattenwirken 3/3
                # Lv 31-32: Verbesserter Gedankenschlag 5/5
                # Lv 33-34: Verschlingende Ansteckung 2/2
                # Lv 35-39: Dunkelheit 5/5
                priority_order = [
                    (105850, 2),  # T0 Disc: Zauberstab-Spezialisierung 2/2 (Lv 10-11)
                    (105833, 5),  # T0 Shadow: Willensentzug 5/5 (Lv 12-16)
                    (105830, 2),  # T1 Shadow: Verbessertes Schattenwort: Schmerz 2/2 (Lv 17-18)
                    (105831, 3),  # T1 Shadow: Verbesserter Gedankenschlag 3/5 (Lv 19-21)
                    (105826, 1),  # T2 Shadow: Gedankenschinden 1/1 (Lv 22)
                    (105825, 2),  # T2 Shadow: Verbessertes Gedankenschinden 2/2 (Lv 23-24)
                    (105829, 2),  # T1 Shadow: Schattenreichweite 2/2 (Lv 25-26)
                    (105820, 1),  # T3 Shadow: Vampirumarmung 1/1 (Lv 27)
                    (105821, 3),  # T3 Shadow: Schattenwirken 3/3 (Lv 28-30)
                    (105831, 5),  # T1 Shadow: Finish Verbesserter Gedankenschlag 5/5 (Lv 31-32)
                    (105819, 2),  # T4 Shadow: Verschlingende Ansteckung 2/2 (Lv 33-34)
                    (105818, 5),  # T5 Shadow: Dunkelheit 5/5 (Lv 35-39)
                ]

        for tid, target_rk in priority_order:
            if points_left <= 0:
                break
            if tid not in talent_by_id:
                continue
            max_rk = talent_by_id[tid]["max_rank"]
            cur_rk = allocated.get(tid, 0)
            needed = min(max_rk, target_rk) - cur_rk
            if needed > 0:
                spend = min(points_left, needed)
                allocated[tid] = cur_rk + spend
                points_left -= spend

    # Compute exact modifiers from allocated official Blizzard API talents
    mods: Dict[str, Any] = {
        "wand_dmg_mult": 1.0,
        "shadow_dmg_mult": 1.0,
        "holy_dmg_mult": 1.0,
        "instant_dmg_mult": 1.0,
        "smite_penance_dmg_mult": 1.0,
        "mind_flay_dmg_mult": 1.0,
        "swp_extra_duration_ms": 0,
        "mind_blast_cd_reduction_ms": 0,
        "smite_hf_cast_reduction_ms": 0,
        "shadow_mana_mult": 1.0,
        "instant_mana_mult": 1.0,
        "smite_hf_mana_mult": 1.0,
        "penance_mana_mult": 1.0,
        "devouring_plague_mana_mult": 1.0,
        "pws_mana_mult": 1.0,
        "pws_absorb_mult": 1.0,
        "shadowform_active": False,
        "spirit_tap_active": False,
        "meditation_regen_pct": 0.0,
        "unlocked_talent_ids": set(allocated.keys()),
        "active_talents_list": [],
    }

    for tid, rk in allocated.items():
        if rk <= 0 or tid not in talent_by_id:
            continue
        t = talent_by_id[tid]
        eff_list = json.loads(t["effect_summary_json"]) if t.get("effect_summary_json") else []
        rk_desc = t["description_raw"]
        if isinstance(eff_list, list) and eff_list:
            rk_entry = eff_list[min(rk - 1, len(eff_list) - 1)]
            if isinstance(rk_entry, dict) and rk_entry.get("description"):
                rk_desc = rk_entry["description"]

        mods["active_talents_list"].append(
            {
                "talent_id": tid,
                "name": t["name"],
                "tab_name": t["tab_name"],
                "rank": rk,
                "max_rank": t["max_rank"],
                "description": rk_desc,
            }
        )

        # Official WoW Forever talent modifiers (verified from /data/wow/talent-tree/1114)
        if tid == 105850:  # Zauberstab-Spezialisierung (2/2: Rank 1 = +13%, Rank 2 = +25%)
            mods["wand_dmg_mult"] += 0.13 if rk == 1 else 0.25
        elif tid == 110853:  # Macht im Licht (5/5: +2%/4%/6%/8%/10% Smite & Penance dmg)
            mods["smite_penance_dmg_mult"] *= 1.0 + (0.02 * rk)
        elif tid == 105849:  # Zwillingsdisziplinen (5/5: +1%..+5% Instant dmg & healing)
            mods["instant_dmg_mult"] *= 1.0 + (0.01 * rk)
            mods["pws_absorb_mult"] *= 1.0 + (0.01 * rk)
        elif tid == 105846:  # Verbessertes Machtwort: Schild (3/3: +7% / +13% / +20% Absorb)
            pws_bonus = {1: 0.07, 2: 0.13, 3: 0.20}.get(rk, 0.07 * rk)
            mods["pws_absorb_mult"] *= 1.0 + pws_bonus
        elif tid == 105842:  # Mentale Beweglichkeit (3/3: -3% / -6% / -10% Mana on Smite, Holy Fire, Instants)
            red = {1: 0.03, 2: 0.06, 3: 0.10}.get(rk, 0.03 * rk)
            mods["instant_mana_mult"] *= 1.0 - red
            mods["smite_hf_mana_mult"] *= 1.0 - red
        elif tid == 105843:  # Meditation (3/3: 17% / 33% / 50% Spirit regen while casting)
            mods["meditation_regen_pct"] += {1: 17.0, 2: 33.0, 3: 50.0}.get(rk, 17.0 * rk)
        elif tid == 105839:  # Seelenwehr (1/1: -4s CD & -15% Mana on PW:S)
            mods["pws_mana_mult"] *= 0.85
        elif tid == 105863:  # Göttlicher Furor (5/5: -100ms per rank on Smite/Holy Fire)
            mods["smite_hf_cast_reduction_ms"] += 100 * rk
        elif tid == 105858:  # Verbesserte Heilung (3/3: -5%/-10%/-15% Mana on heals & Penance)
            mods["penance_mana_mult"] *= 1.0 - (0.05 * rk)
        elif tid == 105857:  # Sengendes Licht (2/2: +3% / +5% Holy dmg)
            mods["holy_dmg_mult"] *= 1.0 + ({1: 0.03, 2: 0.05}.get(rk, 0.03 * rk))
        elif tid == 105833:  # Willensentzug (5/5)
            mods["spirit_tap_active"] = True
        elif tid == 105830:  # Verbessertes Schattenwort: Schmerz (2/2: +3000ms / +6000ms)
            mods["swp_extra_duration_ms"] += 3000 * rk
        elif tid == 105831:  # Verbesserter Gedankenschlag (5/5: -500ms per rank)
            mods["mind_blast_cd_reduction_ms"] += 500 * rk
        elif tid == 105825:  # Verbessertes Gedankenschinden (2/2: +10% / +20% per subsequent tick -> +10% / +20% avg dmg)
            mods["mind_flay_dmg_mult"] *= 1.0 + (0.10 * rk)
        elif tid == 105821:  # Schattenwirken (3/3: 33%/66%/100% chance for +2% Shadow dmg up to 5 stacks = +10%)
            proc_chance = {1: 0.33, 2: 0.66, 3: 1.00}.get(rk, 0.33 * rk)
            mods["shadow_dmg_mult"] *= 1.0 + (0.08 * proc_chance)
        elif tid == 105819:  # Verschlingende Ansteckung (2/2: -25% / -50% Mana on Devouring Plague)
            mods["devouring_plague_mana_mult"] *= 1.0 - (0.25 * rk)
        elif tid == 105818:  # Dunkelheit (5/5: +2% per rank Shadow dmg)
            mods["shadow_dmg_mult"] *= 1.0 + (0.02 * rk)
        elif tid == 105817:  # Schattengestalt (1/1: +10% Shadow dmg, -50% Shadow mana, +100% crit dmg bonus)
            mods["shadow_dmg_mult"] *= 1.10
            mods["shadow_mana_mult"] *= 0.50
            mods["shadowform_active"] = True

    return {
        "total_points": total_points,
        "points_spent": total_points - points_left,
        "allocated": allocated,
        "modifiers": mods,
    }


def get_optimal_rotation(
    class_name: str = "PRIEST",
    current_level: int = 1,
    fight_duration_sec: float = 15.0,
    mode: str = "leveling_balanced",
    race_mask: int = 16,
    spec_profile: str = "auto",
    wand_dps_override: Optional[float] = None,
    custom_mana_weight: Optional[float] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Phase 2 Core Engine:
    1. Filter spells by class, unlock_level <= current_level, race_mask, and active talents.
    2. Select highest available rank per spell name.
    3. Apply WoW Forever talent modifiers and compute avg_dmg, exec_time, DPCT, DPM, and Score.
    4. Build Pre-Pull, Pull/Opener, Core Priority List, and 5-Second-Rule (FSR) Wand Finisher.
    5. Generate Trainer & Next-Level (+1 to +3) previews.
    """
    current_level = max(1, min(60, int(current_level)))
    fight_duration_sec = max(4.0, float(fight_duration_sec))

    # Determine DPCT vs DPM weights
    if custom_mana_weight is not None:
        w_dpm = max(0.0, min(1.0, float(custom_mana_weight)))
        w_dpct = 1.0 - w_dpm
    else:
        w_dpct, w_dpm = MODE_WEIGHTS.get(mode, (0.50, 0.50))

    talent_state = allocate_talents_for_level(
        class_name=class_name,
        current_level=current_level,
        spec_profile=spec_profile,
        db_path=db_path,
    )
    mods = talent_state["modifiers"]
    unlocked_tids = mods["unlocked_talent_ids"]

    all_class_spells = query_spells(class_name, db_path=db_path)

    # Filter available spells at current_level
    available_spells: List[Dict[str, Any]] = []
    for sp in all_class_spells:
        if sp["unlock_level"] > current_level:
            continue
        if sp["race_mask"] != 0 and (sp["race_mask"] & race_mask) == 0:
            continue
        req_tid = sp["requires_talent_id"]
        if req_tid is not None and req_tid not in unlocked_tids:
            continue
        available_spells.append(sp)

    # Group by spell name and pick highest rank available at current_level
    highest_rank_by_name: Dict[str, Dict[str, Any]] = {}
    for sp in available_spells:
        nm = sp["name"]
        if (
            nm not in highest_rank_by_name
            or sp["rank_num"] > highest_rank_by_name[nm]["rank_num"]
            or (
                sp["rank_num"] == highest_rank_by_name[nm]["rank_num"]
                and sp["unlock_level"] > highest_rank_by_name[nm]["unlock_level"]
            )
        ):
            highest_rank_by_name[nm] = dict(sp)

    # Compute talent-modified metrics for each highest-rank spell
    evaluated_spells: List[Dict[str, Any]] = []
    for nm, sp in highest_rank_by_name.items():
        cast_ms = int(sp["cast_time_ms"])
        cd_ms = int(sp["cooldown_ms"])
        gcd_ms = int(sp["gcd_ms"])
        mana = float(sp["mana_cost"])
        dir_min = float(sp["direct_dmg_min"])
        dir_max = float(sp["direct_dmg_max"])
        dot_total = float(sp["dot_dmg_total"])
        dot_dur_ms = int(sp["dot_duration_ms"])
        tick_ms = int(sp["tick_interval_ms"])
        absorb = float(sp["absorb_amount"])
        is_chan = bool(sp["is_channeled"])
        school = sp["school"]
        cat = sp["spell_category"]

        # Apply WoW Forever talent modifiers
        if nm in ("Göttliche Pein", "Heiliges Feuer"):
            cast_ms = max(0, cast_ms - mods["smite_hf_cast_reduction_ms"])
            mana *= mods["smite_hf_mana_mult"]
        elif cast_ms == 0 and not is_chan:
            mana *= mods["instant_mana_mult"]

        if nm == "Sühne":
            mana *= mods["penance_mana_mult"]
        elif nm == "Verschlingende Seuche":
            mana *= mods["devouring_plague_mana_mult"]
        elif nm == "Machtwort: Schild":
            mana *= mods["pws_mana_mult"]

        if nm == "Gedankenschlag":
            cd_ms = max(0, cd_ms - mods["mind_blast_cd_reduction_ms"])

        if nm == "Schattenwort: Schmerz" and mods["swp_extra_duration_ms"] > 0 and dot_dur_ms > 0:
            base_tick = dot_total / max(1, dot_dur_ms // (tick_ms or 3000))
            dot_dur_ms += mods["swp_extra_duration_ms"]
            dot_total = base_tick * (dot_dur_ms // (tick_ms or 3000))

        if school == "Shadow":
            mana *= mods["shadow_mana_mult"]
            dmg_mult = mods["shadow_dmg_mult"]
        elif school == "Holy":
            dmg_mult = mods["holy_dmg_mult"]
        else:
            dmg_mult = 1.0

        if cast_ms == 0 and not is_chan:
            dmg_mult *= mods["instant_dmg_mult"]
        if nm in ("Göttliche Pein", "Sühne"):
            dmg_mult *= mods["smite_penance_dmg_mult"]
        if nm == "Gedankenschinden":
            dmg_mult *= mods["mind_flay_dmg_mult"]

        if nm == "Machtwort: Schild":
            absorb *= mods["pws_absorb_mult"]

        eff_mana = max(0, int(round(mana)))
        avg_direct = ((dir_min + dir_max) / 2.0) * dmg_mult

        # Cap DoT damage to fight_duration_sec
        if dot_total > 0 and dot_dur_ms > 0:
            if is_chan:
                # Channeled damage happens during the channel itself
                eff_dot = dot_total * dmg_mult
            else:
                active_window_ms = min(dot_dur_ms, int(fight_duration_sec * 1000))
                if tick_ms > 0:
                    eff_ticks = active_window_ms // tick_ms
                    total_ticks = max(1, dot_dur_ms // tick_ms)
                    eff_dot = (dot_total * (eff_ticks / total_ticks)) * dmg_mult
                else:
                    eff_dot = (dot_total * (active_window_ms / dot_dur_ms)) * dmg_mult
        else:
            eff_dot = 0.0

        avg_dmg = round(avg_direct + eff_dot, 2)
        full_uncapped_dmg = round(avg_direct + (dot_total * dmg_mult), 2)

        # Execution time in seconds: for channeled spells, the channel duration is the cast time
        if is_chan and dot_dur_ms > 0:
            exec_time = max(dot_dur_ms, gcd_ms) / 1000.0
        else:
            exec_time = max(cast_ms, gcd_ms) / 1000.0

        dpct = round(avg_dmg / exec_time, 2) if exec_time > 0 else 0.0
        dpm = round(avg_dmg / eff_mana, 2) if eff_mana > 0 else 0.0

        sp_eval = dict(sp)
        sp_eval.update(
            {
                "display_name": f"{nm} - {sp['rank']}" if sp["rank"] else nm,
                "effective_cast_time_ms": cast_ms,
                "effective_cooldown_ms": cd_ms,
                "effective_mana_cost": eff_mana,
                "avg_direct_dmg": round(avg_direct, 2),
                "effective_dot_dmg": round(eff_dot, 2),
                "avg_dmg": avg_dmg,
                "uncapped_dmg": full_uncapped_dmg,
                "effective_dot_duration_ms": dot_dur_ms,
                "effective_absorb": round(absorb, 2),
                "exec_time_sec": round(exec_time, 2),
                "dpct": dpct,
                "dpm": dpm,
            }
        )
        evaluated_spells.append(sp_eval)

    # Normalize DPCT & DPM across offensive spells to compute weighted Score (0-100 scale)
    offensive_spells = [
        s
        for s in evaluated_spells
        if s["avg_dmg"] > 0
        and s["spell_category"]
        in ("direct_damage", "dot_damage", "hybrid_damage", "channel_damage", "aoe_damage")
    ]
    max_dpct = max((s["dpct"] for s in offensive_spells), default=1.0) or 1.0
    max_dpm = max((s["dpm"] for s in offensive_spells), default=1.0) or 1.0

    for s in evaluated_spells:
        if s in offensive_spells:
            norm_dpct = s["dpct"] / max_dpct
            norm_dpm = s["dpm"] / max_dpm
            raw_score = (w_dpct * norm_dpct + w_dpm * norm_dpm) * 100.0
            # Penalize AoE spells (Heilige Nova) in single-target rotation scoring
            if s["spell_category"] == "aoe_damage":
                raw_score *= 0.35
            s["score"] = round(raw_score, 1)
        else:
            s["score"] = 0.0

    offensive_spells.sort(key=lambda x: (-x["score"], -x["dpct"]))

    # Calculate Wand metrics from official Blizzard API items (wf_wands) & Finisher phase
    wand_ranks = talent_state["allocated"].get(105850, 0)
    wand_spec_pct = 13 if wand_ranks == 1 else (25 if wand_ranks >= 2 else 0)
    db_wand_dps, recommended_wand, available_wands = get_recommended_wand(
        current_level, mods["wand_dmg_mult"], db_path=db_path
    )
    wand_dps = wand_dps_override if wand_dps_override is not None else db_wand_dps

    # 3. Build Combat Sequence (Pre-Pull -> Opener -> Core Frontload -> FSR / Wand Finisher)
    sequence: List[Dict[str, Any]] = []
    combat_time_sec = 0.0
    total_mana_used = 0
    total_expected_damage = 0.0

    # --- Phase A: Pre-Pull ---
    pws = next((s for s in evaluated_spells if s["name"] == "Machtwort: Schild"), None)
    if pws and not (mods["shadowform_active"] and mode == "mana_saver"):
        sequence.append(
            {
                "phase": "Pre-Pull",
                "step": len(sequence) + 1,
                "timestamp_sec": -1.5,
                "spell_id": pws["spell_id"],
                "display_name": pws["display_name"],
                "name": pws["name"],
                "rank": pws["rank"],
                "mana_cost": pws["effective_mana_cost"],
                "exec_time_sec": pws["exec_time_sec"],
                "expected_dmg": 0.0,
                "absorb": pws["effective_absorb"],
                "dpct": 0.0,
                "dpm": 0.0,
                "score": 0.0,
                "reason": (
                    f"Absorbiert {pws['effective_absorb']:.0f} Schaden vor Kampfbeginn "
                    f"(verhindert Cast-Pushback beim Pull; Manaregeneration startet sofort)."
                ),
            }
        )
        total_mana_used += pws["effective_mana_cost"]

    prepull_buff = next(
        (
            s
            for s in evaluated_spells
            if s["spell_category"] == "prepull_buff"
            and s["dpm"] >= 0.3
            and mode != "mana_saver"
        ),
        None,
    )
    if prepull_buff:
        sequence.append(
            {
                "phase": "Pre-Pull (Optional)",
                "step": len(sequence) + 1,
                "timestamp_sec": -3.0,
                "spell_id": prepull_buff["spell_id"],
                "display_name": prepull_buff["display_name"],
                "name": prepull_buff["name"],
                "rank": prepull_buff["rank"],
                "mana_cost": prepull_buff["effective_mana_cost"],
                "exec_time_sec": prepull_buff["exec_time_sec"],
                "expected_dmg": prepull_buff["avg_dmg"],
                "absorb": 0.0,
                "dpct": prepull_buff["dpct"],
                "dpm": prepull_buff["dpm"],
                "score": prepull_buff["score"],
                "reason": (
                    f"Reaktiver Volks-Buff ({prepull_buff['avg_dmg']:.0f} Schattenschaden bei Treffer)."
                    + (
                        " (Freischaltung über Level-10-Klassenquest 'Im Schatten': Vater Lankester ➔ Aelthalyste im Kriegerviertel von Unterstadt!)"
                        if prepull_buff.get("spell_id") == 2652
                        else ""
                    )
                ),
            }
        )

    # --- Phase B: Pull / Opener (cast_time_ms > 0 with highest Score) ---
    # Note: In Shadowform (Lv40+), Holy spells cannot be cast unless outside Shadowform;
    # wait: in WoW Forever, Shadowform says "Ihr könnt in dieser Gestalt jedoch keine Heilzauber wirken"
    # (only healing spells are blocked, or if Shadow Priest prefers Mind Blast!).
    cast_openers = [
        s
        for s in offensive_spells
        if s["effective_cast_time_ms"] > 0
        and not (mods["shadowform_active"] and s["school"] == "Holy")
    ]
    opener = cast_openers[0] if cast_openers else None
    if opener:
        sequence.append(
            {
                "phase": "Pull / Opener",
                "step": len(sequence) + 1,
                "timestamp_sec": 0.0,
                "spell_id": opener["spell_id"],
                "display_name": opener["display_name"],
                "name": opener["name"],
                "rank": opener["rank"],
                "mana_cost": opener["effective_mana_cost"],
                "exec_time_sec": opener["exec_time_sec"],
                "expected_dmg": opener["avg_dmg"],
                "absorb": 0.0,
                "dpct": opener["dpct"],
                "dpm": opener["dpm"],
                "score": opener["score"],
                "reason": (
                    f"Höchster Opener-Score ({opener['score']:.1f}): "
                    f"{opener['effective_cast_time_ms']/1000.0:.1f}s Castzeit läuft vor Kampfbeginn ab "
                    f"({opener['avg_dmg']:.0f} Ø Schaden, {opener['dpm']:.2f} DPM)."
                ),
            }
        )
        total_mana_used += opener["effective_mana_cost"]
        total_expected_damage += opener["avg_dmg"]
        # After a pre-cast opener lands at t=0.0, GCD is already ready!

    # --- Phase C: Core / Priority List (Frontloading before 5-Second-Rule cutoff) ---
    # Target frontload window: bundle all mana-spending spells in the first ~35-50% of fight_duration_sec
    # (or longer in 'burst' mode) so the 5-Second Rule triggers during the Wand phase.
    frontload_budget_sec = (
        fight_duration_sec * 0.75
        if mode == "burst"
        else (fight_duration_sec * 0.35 if mode == "mana_saver" else fight_duration_sec * 0.50)
    )
    if current_level < 5 or wand_dps <= 0:
        frontload_budget_sec = fight_duration_sec

    active_dots: Dict[str, float] = {}  # spell_name -> expires_at_sec
    cooldown_ready: Dict[str, float] = {}  # spell_name -> ready_at_sec
    if opener:
        if opener["effective_cooldown_ms"] > 0:
            cooldown_ready[opener["name"]] = opener["effective_cooldown_ms"] / 1000.0
        if opener["effective_dot_duration_ms"] > 0:
            active_dots[opener["name"]] = opener["effective_dot_duration_ms"] / 1000.0

    while combat_time_sec + 1.5 <= frontload_budget_sec:
        rem_fight = fight_duration_sec - combat_time_sec
        best_cand = None
        best_cand_score = -1.0
        best_cand_dmg = 0.0

        for s in offensive_spells:
            nm = s["name"]
            if s["spell_category"] == "aoe_damage":
                continue
            if mods["shadowform_active"] and s["school"] == "Holy":
                continue
            # Reserve Shadow Word: Death for Finisher unless in pure burst mode
            if nm == "Schattenwort: Tod" and mode != "burst":
                continue
            if cooldown_ready.get(nm, 0.0) > combat_time_sec + 0.01:
                continue
            if active_dots.get(nm, 0.0) > combat_time_sec + 1.0:
                continue

            # Check if DoT has enough remaining fight time to tick meaningfully (at least 60% of duration or >= 9s)
            if s["spell_category"] == "dot_damage":
                min_needed = min(12.0, (s["effective_dot_duration_ms"] / 1000.0) * 0.6)
                if rem_fight < min_needed:
                    continue
                # In mana_saver mode, skip very expensive secondary DoTs (like Verschlingende Seuche) if DPM < 0.9
                if mode == "mana_saver" and s["dpm"] < 0.95 and nm != "Schattenwort: Schmerz":
                    continue

            # If Wand is available and stronger DPCT than filler cast in leveling/mana_saver, stop frontloading filler casts
            if (
                wand_dps > 0
                and mode != "burst"
                and s["spell_category"] == "direct_damage"
                and s["effective_cooldown_ms"] == 0
                and combat_time_sec >= 1.5
                and s["dpct"] < wand_dps * 1.15
            ):
                continue

            if s["score"] > best_cand_score:
                best_cand = s
                best_cand_score = s["score"]
                best_cand_dmg = s["avg_dmg"]

        if not best_cand:
            break

        nm = best_cand["name"]
        exec_t = best_cand["exec_time_sec"]
        if (
            sequence
            and sequence[-1]["phase"] == "Core / Frontload"
            and sequence[-1]["spell_id"] == best_cand["spell_id"]
        ):
            prev = sequence[-1]
            prev["cast_count"] = prev.get("cast_count", 1) + 1
            cnt = prev["cast_count"]
            prev["display_name"] = f"{cnt}x {best_cand['display_name']}"
            prev["mana_cost"] += best_cand["effective_mana_cost"]
            prev["exec_time_sec"] = round(prev["exec_time_sec"] + exec_t, 1)
            prev["expected_dmg"] = round(prev["expected_dmg"] + best_cand_dmg, 1)
            prev["reason"] = (
                f"{cnt}x hintereinander gewirkt (Score {best_cand['score']:.1f}) | "
                f"DPCT: {best_cand['dpct']:.1f} | DPM: {best_cand['dpm']:.2f}"
            )
        else:
            sequence.append(
                {
                    "phase": "Core / Frontload",
                    "step": len(sequence) + 1,
                    "timestamp_sec": round(combat_time_sec, 1),
                    "spell_id": best_cand["spell_id"],
                    "display_name": best_cand["display_name"],
                    "name": nm,
                    "rank": best_cand["rank"],
                    "cast_count": 1,
                    "mana_cost": best_cand["effective_mana_cost"],
                    "exec_time_sec": exec_t,
                    "expected_dmg": best_cand_dmg,
                    "absorb": 0.0,
                    "dpct": best_cand["dpct"],
                    "dpm": best_cand["dpm"],
                    "score": best_cand["score"],
                    "reason": (
                        f"Priorität nach Score ({best_cand['score']:.1f}) | "
                        f"DPCT: {best_cand['dpct']:.1f} | DPM: {best_cand['dpm']:.2f}"
                    ),
                }
            )
        combat_time_sec += exec_t
        total_mana_used += best_cand["effective_mana_cost"]
        total_expected_damage += best_cand_dmg

        if best_cand["effective_cooldown_ms"] > 0:
            cooldown_ready[nm] = combat_time_sec + (best_cand["effective_cooldown_ms"] / 1000.0)
        if best_cand["effective_dot_duration_ms"] > 0 and not best_cand["is_channeled"]:
            active_dots[nm] = combat_time_sec + (best_cand["effective_dot_duration_ms"] / 1000.0)

    # --- Phase D: Finisher / 5-Second-Rule (FSR) Wand Phase ---
    fsr_switch_sec = round(combat_time_sec, 1)
    rem_wand_sec = max(0.0, round(fight_duration_sec - fsr_switch_sec, 1))
    fsr_regen_window_sec = max(0.0, round(rem_wand_sec - 5.0, 1))

    if rem_wand_sec > 0:
        if wand_dps > 0:
            wand_total_dmg = round(wand_dps * rem_wand_sec, 1)
            total_expected_damage += wand_total_dmg
            wand_label = (
                f"Zauberstab: {recommended_wand['name']}"
                if recommended_wand and wand_dps_override is None
                else "Zauberstab (Wand)"
            )
            if wand_spec_pct > 0:
                wand_label += f" (+{wand_spec_pct}% Spez.)"
            sequence.append(
                {
                    "phase": "Finisher / 5-Sek.-Regel (FSR)",
                    "step": len(sequence) + 1,
                    "timestamp_sec": fsr_switch_sec,
                    "spell_id": 5019,
                    "display_name": wand_label,
                    "name": "Zauberstab",
                    "rank": f"{wand_dps:.1f} DPS",
                    "mana_cost": 0,
                    "exec_time_sec": rem_wand_sec,
                    "expected_dmg": wand_total_dmg,
                    "absorb": 0.0,
                    "dpct": wand_dps,
                    "dpm": 0.0,
                    "score": 100.0,
                    "custom_icon_url": (
                        recommended_wand.get("icon_url", "")
                        if recommended_wand
                        else ""
                    ),
                    "reason": (
                        f"Zauber-Stopp ab t={fsr_switch_sec:.1f}s für {rem_wand_sec:.1f}s Zauberstab-Phase "
                        f"({wand_total_dmg:.0f} Schaden für 0 Mana). "
                        f"Ab t={fsr_switch_sec + 5.0:.1f}s ({fsr_regen_window_sec:.1f}s lang) "
                        f"100% Willenskraft-Manaregeneration (FSR)!"
                    ),
                }
            )
        else:
            # Level 1-4 before wands are available: continue casting Smite or Melee finisher
            smite = next((s for s in offensive_spells if s["name"] == "Göttliche Pein"), None)
            if smite:
                extra_casts = int(rem_wand_sec // smite["exec_time_sec"])
                if extra_casts > 0:
                    extra_dmg = round(smite["avg_dmg"] * extra_casts, 1)
                    extra_mana = smite["effective_mana_cost"] * extra_casts
                    total_expected_damage += extra_dmg
                    total_mana_used += extra_mana
                    sequence.append(
                        {
                            "phase": "Filler / Finisher (Vor Zauberstab Lv 5)",
                            "step": len(sequence) + 1,
                            "timestamp_sec": fsr_switch_sec,
                            "spell_id": smite["spell_id"],
                            "display_name": f"{extra_casts}x {smite['display_name']}",
                            "name": smite["name"],
                            "rank": smite["rank"],
                            "mana_cost": extra_mana,
                            "exec_time_sec": round(extra_casts * smite["exec_time_sec"], 1),
                            "expected_dmg": extra_dmg,
                            "absorb": 0.0,
                            "dpct": smite["dpct"],
                            "dpm": smite["dpm"],
                            "score": smite["score"],
                            "reason": "Vor Level 5 noch kein Zauberstab verfügbar – Füller bis Mob-Tod.",
                        }
                    )

    # Optional Execute Finisher note if Schattenwort: Tod is unlocked (Lv 32+)
    swd = next((s for s in offensive_spells if s["name"] == "Schattenwort: Tod"), None)
    if swd and mode != "burst":
        sequence.append(
            {
                "phase": "Execute-Finisher (Bei Tod des Ziels)",
                "step": len(sequence) + 1,
                "timestamp_sec": round(fight_duration_sec - 1.0, 1),
                "spell_id": swd["spell_id"],
                "display_name": swd["display_name"],
                "name": swd["name"],
                "rank": swd["rank"],
                "mana_cost": swd["effective_mana_cost"],
                "exec_time_sec": swd["exec_time_sec"],
                "expected_dmg": swd["avg_dmg"],
                "absorb": 0.0,
                "dpct": swd["dpct"],
                "dpm": swd["dpm"],
                "score": swd["score"],
                "reason": (
                    f"WoW Forever Custom-Zauber: Sofort {swd['avg_dmg']:.0f} Schattenschaden als tödlicher Finisher "
                    f"(kein Rückstoßschaden, wenn das Ziel daran stirbt; am Kampfende stört es die FSR nicht!)."
                ),
            }
        )

    # Enrich sequence steps with official Blizzard CDN icon URLs
    fdid_by_spell_id = {sp["spell_id"]: sp.get("icon_fdid", 0) for sp in all_class_spells}
    for step in sequence:
        sid = step.get("spell_id", 0)
        fdid = fdid_by_spell_id.get(sid, 135139 if sid == 5019 else 0)
        step["icon_fdid"] = fdid
        step["icon_url"] = step.get("custom_icon_url") or (
            f"https://render.worldofwarcraft.com/eu/icons/56/{fdid}.jpg" if fdid > 0 else ""
        )

    # 4. Trainer & Next-Level Preview (current_level and +1 to +3)
    new_at_current_level = [
        sp
        for sp in all_class_spells
        if sp["unlock_level"] == current_level
        and (sp["race_mask"] == 0 or (sp["race_mask"] & race_mask) != 0)
    ]

    upcoming_milestones = [
        sp
        for sp in all_class_spells
        if current_level + 1 <= sp["unlock_level"] <= current_level + 3
        and (sp["race_mask"] == 0 or (sp["race_mask"] & race_mask) != 0)
    ]

    next_major_milestone = None
    if not upcoming_milestones and current_level < 60:
        future_spells = [
            sp
            for sp in all_class_spells
            if sp["unlock_level"] > current_level
            and (sp["race_mask"] == 0 or (sp["race_mask"] & race_mask) != 0)
        ]
        if future_spells:
            next_lvl = future_spells[0]["unlock_level"]
            next_major_milestone = [
                sp for sp in future_spells if sp["unlock_level"] == next_lvl
            ]

    return {
        "class_name": class_name,
        "current_level": current_level,
        "fight_duration_sec": fight_duration_sec,
        "mode": mode,
        "weights": {"dpct": round(w_dpct, 2), "dpm": round(w_dpm, 2)},
        "wand_dps": wand_dps,
        "recommended_wand": recommended_wand,
        "available_wands": available_wands,
        "talents": talent_state,
        "sequence": sequence,
        "summary": {
            "total_mana_used": total_mana_used,
            "total_expected_damage": round(total_expected_damage, 1),
            "overall_dpm": (
                round(total_expected_damage / total_mana_used, 2)
                if total_mana_used > 0
                else 0.0
            ),
            "fsr_switch_sec": fsr_switch_sec,
            "wand_duration_sec": rem_wand_sec,
            "fsr_regen_sec": fsr_regen_window_sec,
        },
        "spells_table": sorted(
            evaluated_spells,
            key=lambda x: (-x["score"], -x["dpct"], x["name"]),
        ),
        "new_at_current_level": new_at_current_level,
        "upcoming_milestones": upcoming_milestones,
        "next_major_milestone": next_major_milestone,
    }


if __name__ == "__main__":
    for test_lvl in (1, 4, 6, 10, 20, 30, 32, 40, 50, 60):
        res = get_optimal_rotation("PRIEST", test_lvl, fight_duration_sec=15, mode="leveling_balanced")
        steps_str = " -> ".join(
            f"[{st['phase']}] {st['display_name']} ({st['mana_cost']}M)"
            for st in res["sequence"]
        )
        print(
            f"Level {test_lvl:2d} (Talente={res['talents']['points_spent']:2d}, "
            f"TotalDmg={res['summary']['total_expected_damage']:6.1f}, "
            f"Mana={res['summary']['total_mana_used']:3d}, "
            f"FSR-Regen={res['summary']['fsr_regen_sec']:4.1f}s): {steps_str}"
        )
