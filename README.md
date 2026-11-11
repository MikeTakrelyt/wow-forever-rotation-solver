# 🔮 WoW Forever – Dynamic Rotation Solver (1–60)

Interaktives Analyse- und Rotations-Tool (Python + SQLite + Streamlit) speziell für **WoW Forever (Custom Level 1–60)**.

Da *WoW Forever* eine modifizierte Codebasis mit eigenen Zauberwerten, Freischalt-Leveln, Manakosten, Cooldowns und Custom-Zaubern (z. B. *Sühne*, *Schattenwort: Tod*, *Gebet der Besserung*, überarbeitete *Schattengestalt* mit -50% Manakosten) nutzt, extrahiert dieses Tool alle Spieldaten direkt aus dem Client und berechnet die mathematisch optimale Rotation (DPCT, DPM, 5-Sekunden-Regel) für jedes Level (1–60).

---

## 🚀 Features

- **Schritt-für-Schritt Kampf-Sequenz:**
  - **Pre-Pull:** Schilde & reaktive Volks-Buffs (*Machtwort: Schild*, *Berührung der Schwäche*, *Schattenschild*).
  - **Pull / Opener:** Optimale Zauber mit Zauberzeit vor Kampfbeginn (*Gedankenschlag*, *Göttliche Pein*).
  - **Core / Frontload:** Prioritätenliste basierend auf gewichtetem DPCT & DPM Score.
  - **Finisher / 5-Sekunden-Regel (FSR):** Exakt berechneter Zauberstab-Wechsel, um maximale Mana-Regeneration über Willenskraft im Kampf mitzunehmen.
  - **Execute-Finisher:** Einsatz von *Schattenwort: Tod* bei Boss-/Mob-Ende.
- **Echte Spieldaten (`wow_forever.db`):** 1.491 Zauber & 194 Talente aus CASC & DBCache.bin.
- **Lehrer- & Meilenstein-Vorschau:** Zeigt, was auf dem aktuellen Level neu gelernt werden kann und was in den nächsten 1–3 Leveln ansteht.
- **Talent-Berechnung ab Level 10:** Automatische Zuweisung von 1 Punkt pro Level mit sofortiger Auswirkung auf Zauberzeit, Schaden und Manakosten.
- **Dark-Mode RPG UI:** Optimiert für Streamlit.

---

## 💻 Lokale Installation & Start

1. Repository klonen:
   ```bash
   git clone https://github.com/MikeTakrelyt/wow-forever-rotation-solver.git
   cd wow-forever-rotation-solver
   ```

2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```

3. Web-UI starten:
   ```bash
   streamlit run app.py
   ```

---

## ☁️ Streamlit Community Cloud Deployment

1. Repository auf GitHub forken oder öffnen.
2. Auf [share.streamlit.io](https://share.streamlit.io/) anmelden.
3. **New App** auswählen:
   - **Repository:** `MikeTakrelyt/wow-forever-rotation-solver`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Auf **Deploy!** klicken.
