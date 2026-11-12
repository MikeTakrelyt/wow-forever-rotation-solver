"""
Wowhead Forever Integration & SQLite Caching Layer.
Fetches verified NPC coordinates, zone locations, tooltips, and URLs from Wowhead Forever.
"""

import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from database import DEFAULT_DB_PATH, get_connection


WOWHEAD_FOREVER_BASE = "https://www.wowhead.com/forever/de"
NETHER_API_BASE = "https://nether.wowhead.com/forever/tooltip"


def get_wowhead_url(entity_type: str, entity_id: int, slug: str = "") -> str:
    """Returns direct user-facing URL on Wowhead Forever."""
    slug_part = f"/{slug}" if slug else ""
    return f"{WOWHEAD_FOREVER_BASE}/{entity_type}={entity_id}{slug_part}"


def fetch_npc_info(
    npc_id: int, db_path: str = DEFAULT_DB_PATH, refresh: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Fetches NPC name, zone, and map coordinates from Wowhead Forever (with local SQLite caching).
    """
    conn = get_connection(db_path)
    cur = conn.cursor()

    if not refresh:
        cur.execute(
            "SELECT * FROM wf_wowhead_cache WHERE entity_type='npc' AND entity_id=? AND locale='de'",
            (npc_id,),
        )
        row = cur.fetchone()
        if row:
            conn.close()
            return {
                "npc_id": npc_id,
                "name": row["name"],
                "zone_name": row["zone_name"],
                "coords_str": row["coords_str"],
                "wowhead_url": row["wowhead_url"],
            }

    # Fetch from Wowhead Nether API
    url = f"{NETHER_API_BASE}/npc/{npc_id}?dataEnv=1&locale=3"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WoW-Forever-Solver/1.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[Wowhead] Failed to fetch NPC {npc_id}: {e}")
        conn.close()
        return None

    name = data.get("name", f"NPC {npc_id}")
    tooltip = data.get("tooltip", "")

    # Extract zone name from tooltip HTML (typically <tr><td>Unterstadt</td></tr>)
    zone_name = ""
    zone_matches = re.findall(r"<tr><td>([^<]+)</td></tr>", tooltip)
    if zone_matches:
        for z in reversed(zone_matches):
            if not any(k in z.lower() for k in ["stufe", "humanoid", "untot", "elite", "boss", "lehrer"]):
                zone_name = z.strip()
                break

    # Extract primary coordinates from map object
    coords_str = ""
    map_data = data.get("map", {})
    coords_dict = map_data.get("coords", {})
    if coords_dict:
        # Take first coordinate list
        for _, coord_list in coords_dict.items():
            if coord_list and len(coord_list) > 0:
                # Format median or first coordinate: e.g. "49.4, 14.4"
                c = coord_list[len(coord_list) // 2]
                coords_str = f"{c[0]:.1f}, {c[1]:.1f}"
                break

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    wowhead_url = get_wowhead_url("npc", npc_id, slug)

    now = int(time.time())
    cur.execute(
        """
        INSERT OR REPLACE INTO wf_wowhead_cache
        (entity_type, entity_id, locale, name, zone_name, coords_str, tooltip_html, wowhead_url, last_updated)
        VALUES (?, ?, 'de', ?, ?, ?, ?, ?, ?)
        """,
        ("npc", npc_id, name, zone_name, coords_str, tooltip, wowhead_url, now),
    )
    conn.commit()
    conn.close()

    return {
        "npc_id": npc_id,
        "name": name,
        "zone_name": zone_name,
        "coords_str": coords_str,
        "wowhead_url": wowhead_url,
    }
