"""
Verification and Test Script for Blizzard Game Data API and Wowhead Forever.
"""

from blizzard_api import BlizzardAPI
import wowhead


def test_wowhead():
    print("--- 1. Testing Wowhead Forever (NPC Locations & Coordinates) ---")
    npc_lankester = wowhead.fetch_npc_info(4607)
    npc_aelthalyste = wowhead.fetch_npc_info(4606)

    print("NPC 4607:", npc_lankester)
    print("NPC 4606:", npc_aelthalyste)

    assert npc_lankester is not None, "Failed to fetch Vater Lankester"
    assert "Unterstadt" in npc_lankester["zone_name"], "Incorrect zone for Vater Lankester"
    assert npc_aelthalyste is not None, "Failed to fetch Aelthalyste"
    assert "Unterstadt" in npc_aelthalyste["zone_name"], "Incorrect zone for Aelthalyste"
    print("✅ Wowhead Forever integration verified successfully!\n")


def test_blizzard():
    print("--- 2. Testing Official Blizzard Battle.net Game Data API ---")
    blizz = BlizzardAPI()
    if not blizz.is_configured:
        print("ℹ️ Blizzard API credentials not yet configured in .env.")
        print("👉 Trage deine Client-ID und dein Client-Secret in '.env' ein:")
        print("   BLIZZARD_CLIENT_ID=...")
        print("   BLIZZARD_CLIENT_SECRET=...\n")
        return

    print(f"Configured Client ID: {blizz.client_id[:6]}... (Region: {blizz.region})")
    token = blizz.get_token()
    if token:
        print("✅ OAuth2 Access Token successfully acquired!")
        # Test fetching a spell media (e.g. Mind Blast ID 8092 or Smite ID 585)
        icon_url = blizz.get_spell_media(8092)
        print(f"Spell 8092 Icon: {icon_url}")
    else:
        print("❌ Could not obtain OAuth2 token. Please verify Client ID and Secret.")


if __name__ == "__main__":
    test_wowhead()
    test_blizzard()
