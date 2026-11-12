"""
Phase 3: Interactive Dark-Mode Web-UI (Streamlit) for WoW Forever (Custom Level 1-60).
Displays step-by-step optimal rotation cards (with exact rank & mana cost),
raw spell metrics comparison table (DPCT, DPM, total damage), and Trainer / Milestone previews.
"""

import os
import pandas as pd
import streamlit as st

from database import DEFAULT_DB_PATH
from extractor import extract_all
from solver import RACE_OPTIONS, get_optimal_rotation


st.set_page_config(
    page_title="WoW Forever – Dynamic Rotation Solver (1–60)",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Dark-Mode RPG Styling
st.markdown(
    """
    <style>
    .stApp {
        background-color: #0d1017;
        color: #e6edf3;
    }
    .rot-card {
        background: linear-gradient(135deg, #171c28 0%, #121620 100%);
        border: 1px solid #2b3448;
        border-left: 5px solid #a335ee;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 12px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
    }
    .rot-card-prepull { border-left-color: #38bdf8; }
    .rot-card-opener  { border-left-color: #f59e0b; }
    .rot-card-core    { border-left-color: #a335ee; }
    .rot-card-fsr     { border-left-color: #10b981; }
    .rot-card-exec    { border-left-color: #ef4444; }
    .phase-badge {
        display: inline-block;
        padding: 2px 9px;
        border-radius: 12px;
        font-size: 0.76rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 6px;
    }
    .badge-prepull { background-color: rgba(56, 189, 248, 0.18); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.4); }
    .badge-opener  { background-color: rgba(245, 158, 11, 0.18); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.4); }
    .badge-core    { background-color: rgba(163, 53, 238, 0.22); color: #d8b4fe; border: 1px solid rgba(163, 53, 238, 0.45); }
    .badge-fsr     { background-color: rgba(16, 185, 129, 0.18); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.4); }
    .badge-exec    { background-color: rgba(239, 68, 68, 0.20); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.45); }
    .spell-title {
        font-size: 1.18rem;
        font-weight: 700;
        color: #ffffff;
        margin: 2px 0 6px 0;
    }
    .spell-meta {
        font-size: 0.88rem;
        color: #9ca3af;
        margin-bottom: 6px;
    }
    .spell-reason {
        font-size: 0.86rem;
        color: #cbd5e1;
        background-color: rgba(255, 255, 255, 0.03);
        padding: 6px 10px;
        border-radius: 6px;
    }
    .milestone-box {
        background-color: #161b26;
        border: 1px solid #2d3748;
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# Known Quest-unlocked spells (especially Level 10/20 Priest racial spells)
KNOWN_QUEST_SPELLS: dict[int, str] = {
    2652: "Level-10-Klassenquest 'Im Schatten' (In Tenebris): Startet bei deinem Priesterlehrer in Brill (Pater Lankester); führt dich nach Unterstadt (Kriegerviertel) zur Banshee Aelthalyste.",
    9035: "Level-10-Klassenquest für Trolle: Startet beim Priesterlehrer im Dorf Sen'jin / Durotar; führt nach Orgrimmar.",
    10797: "Level-10-Klassenquest für Nachtelfen: Startet im Tempel des Mondes / Dolanaar.",
    13908: "Level-10-Klassenquest für Menschen/Zwerge: Startet bei deinem Priesterlehrer in Goldhain/Kharanos; führt in die Kathedrale des Lichts (Sturmwind) bzw. Eisenschmiede.",
}


def format_copper(copper: int) -> str:
    if copper <= 0:
        return ""
    g = copper // 10000
    s = (copper % 10000) // 100
    c = copper % 100
    parts = []
    if g > 0:
        parts.append(f"{g}g")
    if s > 0:
        parts.append(f"{s}s")
    if c > 0:
        parts.append(f"{c}k")
    return " ".join(parts)


# Ensure database exists
if not os.path.exists(DEFAULT_DB_PATH):
    if os.path.exists(r"D:\World of Warcraft\_forever_"):
        with st.spinner("Extrahiere Spieldaten aus D:\\World of Warcraft\\_forever_ ..."):
            extract_all()
    else:
        st.error(
            "Datenbank 'wow_forever.db' nicht gefunden und lokales WoW Forever Verzeichnis "
            "nicht verfügbar. Bitte 'wow_forever.db' im Repository bereitstellen."
        )

# Session state for Level slider & "+1 Level Up" button
if "char_level" not in st.session_state:
    st.session_state.char_level = 10


def _level_up() -> None:
    if st.session_state.char_level < 60:
        st.session_state.char_level += 1


def _level_down() -> None:
    if st.session_state.char_level > 1:
        st.session_state.char_level -= 1


# --- SIDEBAR CONTROLS ---
with st.sidebar:
    st.markdown("## ⚙️ WoW Forever Steuerung")
    st.caption("Datenquelle: `D:\\World of Warcraft\\_forever_` (Build `1.60.1.70888`)")

    class_options = {
        "Priester (Priest) ⭐": "PRIEST",
        "Magier (Mage)": "MAGE",
        "Hexenmeister (Warlock)": "WARLOCK",
        "Druide (Druid)": "DRUID",
        "Schamane (Shaman)": "SHAMAN",
        "Paladin": "PALADIN",
        "Jäger (Hunter)": "HUNTER",
        "Schurke (Rogue)": "ROGUE",
        "Krieger (Warrior)": "WARRIOR",
    }
    selected_class_label = st.selectbox(
        "Klasse", list(class_options.keys()), index=0
    )
    selected_class = class_options[selected_class_label]

    selected_race_label = st.selectbox(
        "Volk (für Volkszauber)", list(RACE_OPTIONS.keys()), index=0
    )
    selected_race_mask = RACE_OPTIONS[selected_race_label]

    st.markdown("---")
    st.markdown("### 📈 Charakter-Level (1–60)")
    col_btn1, col_btn2 = st.columns([1, 2])
    with col_btn1:
        st.button("➖ 1", on_click=_level_down, use_container_width=True)
    with col_btn2:
        st.button("⬆️ +1 Level Up", on_click=_level_up, type="primary", use_container_width=True)

    current_level = st.slider(
        "Aktuelles Level",
        min_value=1,
        max_value=60,
        key="char_level",
    )

    st.markdown("---")
    st.markdown("### ⚔️ Kampf- & Solver-Parameter")
    fight_duration_sec = st.slider(
        "Durchschnittliche Kampfdauer (Sek.)",
        min_value=5,
        max_value=40,
        value=15,
        step=1,
        help="Deckelt DoT-Schaden auf die reale Lebensdauer des Gegners und steuert das 5-Sekunden-Regel-Zeitfenster.",
    )

    mode_labels = {
        "Leveling Balanced (50% DPCT / 50% DPM)": "leveling_balanced",
        "Mana Saver / Grind (25% DPCT / 75% DPM)": "mana_saver",
        "Max Burst / Elite (80% DPCT / 20% DPM)": "burst",
        "Benutzerdefinierte Mana-Gewichtung": "custom",
    }
    selected_mode_label = st.selectbox(
        "Optimierungs-Modus", list(mode_labels.keys()), index=0
    )
    selected_mode = mode_labels[selected_mode_label]

    custom_mana_weight = None
    if selected_mode == "custom":
        custom_mana_weight = st.slider(
            "Mana-Gewichtung (DPM vs. DPCT)",
            min_value=0.0,
            max_value=1.0,
            value=0.50,
            step=0.05,
        )
        solver_mode = "leveling_balanced"
    else:
        solver_mode = selected_mode

    spec_labels = {
        "Automatisch (Optimal für Level)": "auto",
        "Schatten (Mind Flay / Shadowform)": "shadow_leveling",
        "Heilig / Disziplin (Smite / Holy Fire)": "holy_smite",
    }
    selected_spec_label = st.selectbox(
        "Talent-Profil (ab Level 10)", list(spec_labels.keys()), index=0
    )
    selected_spec = spec_labels[selected_spec_label]

    use_custom_wand = st.checkbox("Eigene Zauberstab-DPS angeben", value=False)
    wand_override = None
    if use_custom_wand:
        wand_override = st.slider(
            "Zauberstab-DPS (inkl. Spez.)", min_value=0.0, max_value=120.0, value=25.0, step=1.0
        )

    if os.path.exists(r"D:\World of Warcraft\_forever_"):
        st.markdown("---")
        if st.button("🔄 Spieldaten neu aus CASC extrahieren", use_container_width=True):
            with st.spinner("Lese WDC5-DB2 & DBCache.bin aus D:\\World of Warcraft\\_forever_ ..."):
                n_sp, n_tal = extract_all()
            st.success(f"{n_sp} Zauber & {n_tal} Talente aktualisiert!")


# --- RUN SOLVER ---
result = get_optimal_rotation(
    class_name=selected_class,
    current_level=current_level,
    fight_duration_sec=float(fight_duration_sec),
    mode=solver_mode,
    race_mask=selected_race_mask,
    spec_profile=selected_spec,
    wand_dps_override=wand_override,
    custom_mana_weight=custom_mana_weight,
)

summary = result["summary"]
talents_info = result["talents"]
mods = talents_info["modifiers"]

# --- HEADER & KPI METRICS ---
st.markdown(
    f"## 🔮 WoW Forever Dynamic Rotation Solver — **{selected_class_label.split('(')[0].strip()} Level {current_level}**"
)
st.caption(
    f"Berechnet aus den echten lokalen Spieldaten (`wow_forever.db`) | "
    f"Gewichtung: **{int(result['weights']['dpct']*100)}% DPCT** / **{int(result['weights']['dpm']*100)}% DPM** | "
    f"Kampfdauer: **{fight_duration_sec} Sek.**"
)

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric(
    "Erwarteter Gesamtschaden",
    f"{summary['total_expected_damage']:.0f} Dmg",
    f"{summary['total_expected_damage'] / fight_duration_sec:.1f} Eff. DPS",
)
kpi2.metric(
    "Manakosten (Rotation)",
    f"{summary['total_mana_used']} Mana",
    f"{summary['overall_dpm']:.2f} Gesamt-DPM",
)
kpi3.metric(
    "Zauberstab-Wechsel (FSR)",
    f"ab t = {summary['fsr_switch_sec']:.1f} s",
    f"{summary['wand_duration_sec']:.1f} s Zauberstab ({result['wand_dps']:.1f} DPS)",
)
kpi4.metric(
    "5-Sek.-Regel Manareg.",
    f"{summary['fsr_regen_sec']:.1f} Sek.",
    "Volle Spirit-Regeneration im Kampf" if summary["fsr_regen_sec"] > 0 else "Kurzes Fenster",
)
kpi5.metric(
    "Aktive Talentpunkte",
    f"{talents_info['points_spent']} / 51",
    "Schattengestalt aktiv (-50% Mana!)" if mods["shadowform_active"] else f"Ab Lv 10 ({max(0, current_level-9)} Pkt.)",
)

st.markdown("---")

# --- MAIN LAYOUT: ROTATION CARDS (LEFT) & TRAINER / MILESTONES (RIGHT) ---
col_rot, col_side = st.columns([1.65, 1.0], gap="large")

with col_rot:
    st.markdown("### 🎯 Optimale Kampf-Sequenz (Schritt-für-Schritt)")
    if not result["sequence"]:
        st.warning("Keine aktiven Kampfzauber für diese Auswahl gefunden.")
    else:
        for step in result["sequence"]:
            phase = step["phase"]
            if "Pre-Pull" in phase:
                card_cls, badge_cls = "rot-card-prepull", "badge-prepull"
            elif "Opener" in phase:
                card_cls, badge_cls = "rot-card-opener", "badge-opener"
            elif "FSR" in phase or "Finisher" in phase and "Execute" not in phase:
                card_cls, badge_cls = "rot-card-fsr", "badge-fsr"
            elif "Execute" in phase:
                card_cls, badge_cls = "rot-card-exec", "badge-exec"
            else:
                card_cls, badge_cls = "rot-card-core", "badge-core"

            t_str = (
                f"t = {step['timestamp_sec']:+.1f}s"
                if step["timestamp_sec"] < 0
                else f"t = {step['timestamp_sec']:.1f}s"
            )
            dmg_or_abs = (
                f"🛡️ <b>{step['absorb']:.0f} Absorb</b>"
                if step["absorb"] > 0
                else f"💥 <b>{step['expected_dmg']:.0f} Schaden</b>"
            )
            metrics_pill = (
                f" | ⚡ DPCT: <b>{step['dpct']:.1f}</b> | 💧 DPM: <b>{step['dpm']:.2f}</b> | ⭐ Score: <b>{step['score']:.1f}</b>"
                if step["score"] > 0 and step["mana_cost"] > 0
                else ""
            )

            st.markdown(
                f"""
                <div class="rot-card {card_cls}">
                    <span class="phase-badge {badge_cls}">Schritt {step['step']} • {phase} ({t_str})</span>
                    <div class="spell-title">{step['display_name']}</div>
                    <div class="spell-meta">
                        💧 <b>{step['mana_cost']} Mana</b> &nbsp;|&nbsp;
                        ⏱️ <b>{step['exec_time_sec']:.1f}s</b> Dauer &nbsp;|&nbsp;
                        {dmg_or_abs}{metrics_pill}
                    </div>
                    <div class="spell-reason">💡 {step['reason']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

with col_side:
    # 1. New at Trainer / Quest on THIS level
    st.markdown(f"### 🎓 Neu freigeschaltet auf Level {current_level}")
    new_spells = result["new_at_current_level"]
    if not new_spells:
        st.markdown(
            f"""
            <div class="milestone-box">
                <span style="color:#9ca3af;">Auf <b>Level {current_level}</b> werden keine neuen Klassen-Zauberränge freigeschaltet.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        for sp in new_spells:
            rk_badge = f" — <b>{sp['rank']}</b>" if sp["rank"] else ""
            sp_id = sp.get("spell_id", 0)
            quest_info = KNOWN_QUEST_SPELLS.get(sp_id)

            if quest_info:
                source_badge = " • 📜 <b style='color:#f59e0b;'>Klassen-Quest</b>"
            elif sp.get("is_trainer_confirmed") or sp.get("trainer_cost_copper", 0) > 0:
                cost_str = format_copper(sp["trainer_cost_copper"])
                source_badge = f" • 💰 Lehrer: `{cost_str}`" if cost_str else " • 🎓 Lehrer"
            elif sp.get("requires_talent_id"):
                source_badge = " • 🌿 *Talent*"
            else:
                source_badge = " • 📜 *Quest / Spezial*"

            quest_box_html = (
                f"""<div style="font-size:0.83rem;color:#f59e0b;background:rgba(245,158,11,0.12);padding:6px 10px;border-radius:6px;margin-top:6px;border-left:3px solid #f59e0b;line-height:1.35;">
                    📜 <b>Klassenquest:</b> {quest_info}
                </div>"""
                if quest_info
                else ""
            )

            st.markdown(
                f"""
                <div class="milestone-box">
                    <div style="font-size:1.05rem;font-weight:700;color:#fcd34d;">
                        ✨ {sp['name']}{rk_badge}
                    </div>
                    <div style="font-size:0.84rem;color:#9ca3af;margin:4px 0;">
                        💧 {sp['mana_cost']} Mana • ⏱️ {sp['cast_time_ms']/1000.0:.1f}s Cast • Schule: {sp['school']}{source_badge}
                    </div>
                    <div style="font-size:0.85rem;color:#e2e8f0;">
                        {sp['description_raw']}
                    </div>
                    {quest_box_html}
                </div>
                """,
                unsafe_allow_html=True,
            )

    # 2. Next Milestones (Level +1 to +3)
    st.markdown(
        f"### 🚀 Nächster Meilenstein (Level {min(60, current_level+1)}–{min(60, current_level+3)})"
    )
    upcoming = result["upcoming_milestones"]
    if upcoming:
        for sp in upcoming:
            rk_badge = f" — <b>{sp['rank']}</b>" if sp["rank"] else ""
            sp_id = sp.get("spell_id", 0)
            quest_info = KNOWN_QUEST_SPELLS.get(sp_id)
            if quest_info:
                source_badge = " • 📜 Klassenquest"
            elif sp.get("trainer_cost_copper", 0) > 0:
                cost_str = format_copper(sp["trainer_cost_copper"])
                source_badge = f" • 💰 {cost_str}"
            else:
                source_badge = ""

            st.markdown(
                f"""
                <div class="milestone-box">
                    <div style="font-size:0.98rem;font-weight:700;color:#7dd3fc;">
                        🔓 Level {sp['unlock_level']}: {sp['name']}{rk_badge}
                    </div>
                    <div style="font-size:0.82rem;color:#9ca3af;margin:3px 0;">
                        💧 {sp['mana_cost']} Mana • ⏱️ {sp['cast_time_ms']/1000.0:.1f}s Cast{source_badge}
                    </div>
                    <div style="font-size:0.83rem;color:#cbd5e1;">
                        {sp['description_raw']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    elif result["next_major_milestone"]:
        nxt = result["next_major_milestone"]
        nxt_lvl = nxt[0]["unlock_level"]
        st.info(
            f"Keine neuen Zauber auf Level {current_level+1}–{current_level+3}. "
            f"Nächste Freischaltung auf **Level {nxt_lvl}**: "
            + ", ".join(f"**{s['name']} ({s['rank']})**" for s in nxt)
        )
    else:
        st.success("Maximales Level (60) erreicht – alle Ränge freigeschaltet!")

    # 3. Active Talents Summary
    with st.expander(
        f"🌿 Aktive WoW Forever Talente auf Level {current_level} ({talents_info['points_spent']} Punkte)",
        expanded=True,
    ):
        if not mods["active_talents_list"]:
            st.caption("Talente werden ab Level 10 freigeschaltet (1 Punkt pro Level).")
        else:
            for t in mods["active_talents_list"]:
                st.markdown(
                    f"- **{t['name']} ({t['rank']}/{t['max_rank']})** *[{t['tab_name']}]*: {t['description']}"
                )

st.markdown("---")

# --- RAW METRICS COMPARISON TABLE ---
st.markdown(
    f"### 📊 Roh-Metriken aller verfügbaren Zauber auf Level {current_level} (Höchster Rang)"
)
st.caption(
    "Direkter mathematischer Vergleich (inkl. aktiver WoW Forever Talent-Modifikatoren und DoT-Deckelung auf die eingestellte Kampfdauer)."
)

table_rows = []
for sp in result["spells_table"]:
    if sp["spell_category"] == "utility" and sp["avg_dmg"] == 0 and sp["effective_absorb"] == 0:
        continue
    table_rows.append(
        {
            "Zauber": sp["name"],
            "Rang": sp["rank"] or "—",
            "Unlock Lv": sp["unlock_level"],
            "Kategorie": sp["spell_category"],
            "Schule": sp["school"],
            "Mana (Eff.)": sp["effective_mana_cost"],
            "Exec-Zeit (s)": sp["exec_time_sec"],
            "CD (s)": round(sp["effective_cooldown_ms"] / 1000.0, 1),
            "Ø Direkt-Dmg": sp["avg_direct_dmg"],
            "Eff. DoT-Dmg": sp["effective_dot_dmg"],
            "Gesamt-Dmg": sp["avg_dmg"],
            "Absorb": sp["effective_absorb"],
            "DPCT (Dmg/s)": sp["dpct"],
            "DPM (Dmg/Mana)": sp["dpm"],
            "Solver-Score": sp["score"],
            "WoW Forever Beschreibung": sp["description_raw"],
        }
    )

if table_rows:
    df = pd.DataFrame(table_rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Solver-Score": st.column_config.ProgressColumn(
                "Solver-Score",
                help="Gewichteter Effizienz-Score (0–100) aus DPCT und DPM",
                format="%.1f",
                min_value=0,
                max_value=100,
            ),
            "DPCT (Dmg/s)": st.column_config.NumberColumn(format="%.1f"),
            "DPM (Dmg/Mana)": st.column_config.NumberColumn(format="%.2f"),
            "Gesamt-Dmg": st.column_config.NumberColumn(format="%.1f"),
        },
    )
else:
    st.info("Keine Zauber für diese Filterung vorhanden.")
