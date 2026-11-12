"""
SQLite Database Schema & Access Layer for WoW Forever (wow_forever.db).
"""

import os
import sqlite3
from typing import Any, Dict, List, Optional


DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wow_forever.db")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wf_spells (
    spell_id INTEGER PRIMARY KEY,
    class_name TEXT NOT NULL,
    name TEXT NOT NULL,
    rank TEXT DEFAULT '',
    rank_num INTEGER DEFAULT 0,
    unlock_level INTEGER NOT NULL DEFAULT 1,
    school TEXT NOT NULL DEFAULT 'Physical',
    cast_time_ms INTEGER NOT NULL DEFAULT 0,
    cooldown_ms INTEGER NOT NULL DEFAULT 0,
    gcd_ms INTEGER NOT NULL DEFAULT 1500,
    mana_cost INTEGER NOT NULL DEFAULT 0,
    direct_dmg_min REAL NOT NULL DEFAULT 0.0,
    direct_dmg_max REAL NOT NULL DEFAULT 0.0,
    dot_dmg_total REAL NOT NULL DEFAULT 0.0,
    dot_duration_ms INTEGER NOT NULL DEFAULT 0,
    tick_interval_ms INTEGER NOT NULL DEFAULT 0,
    absorb_amount REAL NOT NULL DEFAULT 0.0,
    is_channeled INTEGER NOT NULL DEFAULT 0,
    requires_talent_id INTEGER,
    race_mask INTEGER NOT NULL DEFAULT 0,
    skill_line_id INTEGER NOT NULL DEFAULT 0,
    icon_fdid INTEGER NOT NULL DEFAULT 0,
    spell_category TEXT NOT NULL DEFAULT 'utility',
    is_trainer_confirmed INTEGER NOT NULL DEFAULT 0,
    trainer_cost_copper INTEGER NOT NULL DEFAULT 0,
    description_raw TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_wf_spells_class_level
    ON wf_spells(class_name, unlock_level);

CREATE INDEX IF NOT EXISTS idx_wf_spells_class_name
    ON wf_spells(class_name, name);

CREATE TABLE IF NOT EXISTS wf_talents (
    talent_id INTEGER PRIMARY KEY,
    class_name TEXT NOT NULL,
    tab_id INTEGER NOT NULL,
    tab_name TEXT NOT NULL,
    tier INTEGER NOT NULL,
    col INTEGER NOT NULL,
    name TEXT NOT NULL,
    max_rank INTEGER NOT NULL,
    rank_spell_ids_json TEXT NOT NULL,
    unlocks_spell_id INTEGER,
    prereq_talent_id INTEGER,
    prereq_rank INTEGER DEFAULT 0,
    effect_summary_json TEXT DEFAULT '{}',
    description_raw TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_wf_talents_class_tab
    ON wf_talents(class_name, tab_id, tier, col);

CREATE TABLE IF NOT EXISTS wf_wowhead_cache (
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    locale TEXT NOT NULL DEFAULT 'de',
    name TEXT NOT NULL,
    zone_name TEXT DEFAULT '',
    coords_str TEXT DEFAULT '',
    tooltip_html TEXT DEFAULT '',
    wowhead_url TEXT NOT NULL,
    last_updated INTEGER NOT NULL,
    PRIMARY KEY (entity_type, entity_id, locale)
);
"""


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH, reset: bool = False) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            if reset:
                conn.execute("DROP TABLE IF EXISTS wf_spells;")
                conn.execute("DROP TABLE IF EXISTS wf_talents;")
            conn.executescript(SCHEMA_SQL)
    finally:
        conn.close()


def query_spells(
    class_name: str,
    max_level: Optional[int] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        if max_level is not None:
            cur = conn.execute(
                """
                SELECT * FROM wf_spells
                WHERE UPPER(class_name) = UPPER(?)
                  AND unlock_level <= ?
                  AND unlock_level >= 1
                ORDER BY unlock_level ASC, name ASC, rank_num ASC, spell_id ASC
                """,
                (class_name, max_level),
            )
        else:
            cur = conn.execute(
                """
                SELECT * FROM wf_spells
                WHERE UPPER(class_name) = UPPER(?)
                  AND unlock_level >= 1
                ORDER BY unlock_level ASC, name ASC, rank_num ASC, spell_id ASC
                """,
                (class_name,),
            )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def query_talents(
    class_name: str,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """
            SELECT * FROM wf_talents
            WHERE UPPER(class_name) = UPPER(?)
            ORDER BY tab_id ASC, tier ASC, col ASC
            """,
            (class_name,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
