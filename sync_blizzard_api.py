"""
Official Blizzard Battle.net Game Data API Synchronizer for WoW Forever (static-forever-eu).
Synchronizes:
1. All 9 Class Talent Trees (/data/wow/talent-tree/) -> wf_talents + wf_spells.requires_talent_id
2. All Equippable Wands (/data/wow/search/item & /data/wow/item/) -> wf_wands
3. Priest Class Quests (/data/wow/quest/category/262) -> wf_class_quests
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from blizzard_api import BlizzardAPI
from database import DEFAULT_DB_PATH, get_connection, init_db


DE_CLASS_NAME_TO_KEY: Dict[str, str] = {
    "Priester": "PRIEST",
    "Magier": "MAGE",
    "Hexenmeister": "WARLOCK",
    "Druide": "DRUID",
    "Schamane": "SHAMAN",
    "Paladin": "PALADIN",
    "Jäger": "HUNTER",
    "Schurke": "ROGUE",
    "Krieger": "WARRIOR",
}

RACE_ID_TO_MASK: Dict[int, int] = {
    1: 1,    # Mensch
    2: 2,    # Orc
    3: 4,    # Zwerg
    4: 8,    # Nachtelf
    5: 16,   # Untoter
    6: 32,   # Tauren
    7: 64,   # Gnom
    8: 128,  # Troll
}

CRAFTED_WAND_HINTS: Dict[int, str] = {
    247789: "Startgebiet / Händler (Ab Stufe 1)",
    11287: "Verzauberkunst (Skill 10) / Auktionshaus",
    11288: "Verzauberkunst (Skill 70) / Auktionshaus",
    11289: "Verzauberkunst (Skill 155) / Auktionshaus",
    217287: "Verzauberkunst (Skill 175) / Auktionshaus",
    249232: "Verzauberkunst (WoW Forever Rezept) / Auktionshaus",
    249237: "Verzauberkunst (WoW Forever Rezept) / Auktionshaus",
    249385: "Verzauberkunst (WoW Forever Rezept - Selten) / Auktionshaus",
}


def sync_talent_trees(blizz: BlizzardAPI, db_path: str = DEFAULT_DB_PATH) -> int:
    print("[Sync] Lade Talentbaum-Index von Blizzard API (static-forever-eu) ...")
    idx = blizz.query("/data/wow/talent-tree/index")
    if not idx or "spec_talent_trees" not in idx:
        raise RuntimeError("Konnte /data/wow/talent-tree/index nicht abrufen.")

    talent_rows: List[Tuple[Any, ...]] = []
    unlocked_spells_by_name: Dict[Tuple[str, str], int] = {}

    for entry in idx["spec_talent_trees"]:
        href = entry.get("key", {}).get("href", "")
        m = re.search(r"/data/wow/talent-tree/(\d+)/playable-specialization/(\d+)", href)
        if not m:
            continue
        tree_id, spec_id = int(m.group(1)), int(m.group(2))

        spec_data = blizz.query(f"/data/wow/talent-tree/{tree_id}/playable-specialization/{spec_id}")
        if not spec_data:
            continue

        de_cls = spec_data.get("playable_class", {}).get("name", "")
        cls_key = DE_CLASS_NAME_TO_KEY.get(de_cls)
        if not cls_key:
            continue

        spec_name = spec_data.get("name", "")
        if cls_key == "PRIEST" and spec_name == "Schattenmagie":
            spec_name = "Schatten"

        nodes = spec_data.get("spec_talent_nodes", [])
        for node in nodes:
            row_idx = int(node.get("display_row", 99))
            col_idx = int(node.get("display_col", 0))
            ranks = node.get("ranks", [])
            if not ranks or row_idx < 1 or row_idx > 10:
                continue

            node_id = int(node["id"])
            tier = row_idx - 1
            max_rank = len(ranks)

            r0_tt = ranks[0].get("tooltip", {})
            t_name = r0_tt.get("talent", {}).get("name", "")
            if not t_name:
                continue

            rank_sids: List[int] = []
            rank_summaries: List[Dict[str, Any]] = []
            for r in ranks:
                rk_num = int(r.get("rank", 1))
                sp_tt = r.get("tooltip", {}).get("spell_tooltip", {})
                sp_id = int(sp_tt.get("spell", {}).get("id", 0))
                desc = str(sp_tt.get("description", "")).strip()
                cast_str = str(sp_tt.get("cast_time", "Passiv"))
                rank_sids.append(sp_id)
                rank_summaries.append(
                    {
                        "rank": rk_num,
                        "spell_id": sp_id,
                        "description": desc,
                        "cast_time": cast_str,
                    }
                )

            last_desc = rank_summaries[-1]["description"] if rank_summaries else ""
            first_cast = rank_summaries[0]["cast_time"] if rank_summaries else "Passiv"

            unlocks_sid: Optional[int] = None
            if max_rank == 1 and first_cast != "Passiv" and rank_sids[0] > 0:
                unlocks_sid = rank_sids[0]
                unlocked_spells_by_name[(cls_key, t_name)] = node_id

            locked_by = node.get("locked_by", [])
            prereq_tid = int(locked_by[0]) if locked_by else None

            talent_rows.append(
                (
                    node_id,
                    cls_key,
                    spec_id,
                    spec_name,
                    tier,
                    col_idx,
                    t_name,
                    max_rank,
                    json.dumps(rank_sids),
                    unlocks_sid,
                    prereq_tid,
                    0,
                    json.dumps(rank_summaries, ensure_ascii=False),
                    last_desc,
                )
            )

    conn = get_connection(db_path)
    with conn:
        conn.execute("DELETE FROM wf_talents;")
        conn.executemany(
            """
            INSERT OR REPLACE INTO wf_talents (
                talent_id, class_name, tab_id, tab_name, tier, col, name,
                max_rank, rank_spell_ids_json, unlocks_spell_id,
                prereq_talent_id, prereq_rank, effect_summary_json, description_raw
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            talent_rows,
        )

        # Update requires_talent_id on wf_spells to match official Blizzard API talent nodes
        conn.execute("UPDATE wf_spells SET requires_talent_id = NULL;")
        for (cls_key, sp_name), tid in unlocked_spells_by_name.items():
            conn.execute(
                "UPDATE wf_spells SET requires_talent_id = ? WHERE class_name = ? AND name = ?",
                (tid, cls_key, sp_name),
            )
    conn.close()
    print(f"[Sync] {len(talent_rows)} offizielle Talent-Knoten in wf_talents gespeichert.")
    return len(talent_rows)


def sync_wands(blizz: BlizzardAPI, db_path: str = DEFAULT_DB_PATH) -> int:
    print("[Sync] Suche Zauberstäbe über Blizzard Item Search API ...")
    res = blizz.query(
        "/data/wow/search/item",
        {"item_class.id": 2, "item_subclass.id": 19, "_pageSize": 100, "_page": 1},
    )
    if not res or "results" not in res:
        print("[Sync] Keine Zauberstäbe gefunden.")
        return 0

    wand_rows: List[Tuple[Any, ...]] = []
    for r in res["results"]:
        idata = r.get("data", {})
        item_id = int(idata.get("id", 0))
        de_name = idata.get("name", {}).get("de_DE")
        if not item_id or not de_name:
            continue

        full = blizz.get_item_data(item_id)
        if not full or "preview_item" not in full:
            continue

        prev = full["preview_item"]
        wpn = prev.get("weapon")
        if not wpn:
            continue

        dps_val = float(wpn.get("dps", {}).get("value", 0.0))
        if dps_val <= 0:
            continue

        dmg_info = wpn.get("damage", {})
        min_dmg = float(dmg_info.get("min_value", 0.0))
        max_dmg = float(dmg_info.get("max_value", 0.0))
        school_de = dmg_info.get("damage_class", {}).get("name", "Physisch")
        speed_ms = int(wpn.get("attack_speed", {}).get("value", 1500))

        req_lvl = int(prev.get("requirements", {}).get("level", {}).get("value", full.get("required_level", 1)))
        if req_lvl <= 0:
            req_lvl = 1
        ilvl = int(full.get("level", 1))
        qual = full.get("quality", {}).get("type", "COMMON")
        binding_de = prev.get("binding", {}).get("name", "")

        # Skip broken/junk test items at ReqLv 1 with high item level or scaling DPS
        if qual == "POOR" or (req_lvl == 1 and (ilvl > 10 or dps_val > 10.0)):
            continue

        stats_list = []
        for st in prev.get("stats", []):
            disp = st.get("display", {}).get("display_string")
            if disp:
                stats_list.append(disp)
        bonus_stats_str = ", ".join(stats_list)

        icon_url = blizz.get_item_media(item_id) or ""
        hint = CRAFTED_WAND_HINTS.get(item_id, "Quest / Dungeon / Welt-Drop")

        wand_rows.append(
            (
                item_id,
                de_name,
                qual,
                req_lvl,
                ilvl,
                round(dps_val, 2),
                min_dmg,
                max_dmg,
                speed_ms,
                school_de,
                bonus_stats_str,
                binding_de,
                icon_url,
                hint,
            )
        )

    conn = get_connection(db_path)
    with conn:
        conn.execute("DELETE FROM wf_wands;")
        conn.executemany(
            """
            INSERT OR REPLACE INTO wf_wands (
                item_id, name, quality, required_level, item_level,
                dps, min_dmg, max_dmg, speed_ms, damage_school,
                bonus_stats, binding, icon_url, source_hint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            wand_rows,
        )
    conn.close()
    print(f"[Sync] {len(wand_rows)} Zauberstäbe aus Blizzard API in wf_wands gespeichert.")
    return len(wand_rows)


CLASS_QUEST_CATEGORIES: Dict[str, int] = {
    "WARLOCK": 61,
    "WARRIOR": 81,
    "SHAMAN": 82,
    "PALADIN": 141,
    "MAGE": 161,
    "ROGUE": 162,
    "HUNTER": 261,
    "PRIEST": 262,
    "DRUID": 263,
}


def sync_all_class_quests(blizz: BlizzardAPI, db_path: str = DEFAULT_DB_PATH) -> int:
    """
    Sync official class quests for all 9 classes from Blizzard API (/data/wow/quest/category/{id}).
    """
    total_quests = 0
    conn = get_connection(db_path)
    with conn:
        conn.execute("DELETE FROM wf_class_quests;")

    for cls_name, cat_id in CLASS_QUEST_CATEGORIES.items():
        print(f"[Sync] Lade {cls_name}-Klassenquests (/data/wow/quest/category/{cat_id}) ...")
        cat = blizz.query(f"/data/wow/quest/category/{cat_id}")
        if not cat or "quests" not in cat:
            continue

        quest_rows: List[Tuple[Any, ...]] = []
        for q_ref in cat["quests"]:
            qid = int(q_ref.get("id", 0))
            qname = q_ref.get("name")
            if not qid or not qname:
                continue

            qdata = blizz.query(f"/data/wow/quest/{qid}")
            if not qdata:
                continue

            title = qdata.get("title", qname)
            desc = qdata.get("description", "")
            rew_spell = qdata.get("rewards", {}).get("spell", {})
            rew_sid = int(rew_spell.get("id", 0)) if rew_spell else 0
            rew_sname = rew_spell.get("name", "") if rew_spell else ""

            races = qdata.get("requirements", {}).get("races", [])
            race_names = [r.get("name", "") for r in races]
            rmask = 0
            for r in races:
                rmask |= RACE_ID_TO_MASK.get(int(r.get("id", 0)), 0)

            quest_rows.append(
                (
                    qid,
                    cls_name,
                    title,
                    desc,
                    rew_sid,
                    rew_sname,
                    ", ".join(race_names),
                    rmask,
                )
            )

        with conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO wf_class_quests (
                    quest_id, class_name, title, description,
                    reward_spell_id, reward_spell_name, race_name, race_mask
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                quest_rows,
            )
        print(f"[Sync] {len(quest_rows)} {cls_name}-Klassenquests gespeichert.")
        total_quests += len(quest_rows)

    conn.close()
    print(f"[Sync] Insgesamt {total_quests} Klassenquests für alle 9 Klassen in wf_class_quests gespeichert.")
    return total_quests


if __name__ == "__main__":
    init_db()
    api = BlizzardAPI()
    if not api.is_configured:
        raise RuntimeError("Blizzard API Credentials fehlen in .env!")
    sync_talent_trees(api)
    sync_wands(api)
    sync_all_class_quests(api)
    print("✅ Vollständige Blizzard API Synchronisation abgeschlossen!")
