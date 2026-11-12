"""
Blizzard Battle.net Game Data API Integration for WoW Forever.
Handles OAuth2 token negotiation, caching, and media/data lookups for items and spells.
"""

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env(path: str = ENV_PATH) -> Dict[str, str]:
    """Lightweight .env parser that does not require python-dotenv."""
    env: Dict[str, str] = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("'\"")
    return env


class BlizzardAPI:
    """Client for the official Blizzard Battle.net Game Data API."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        region: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> None:
        env = load_env()
        self.client_id = client_id or os.environ.get("BLIZZARD_CLIENT_ID") or env.get("BLIZZARD_CLIENT_ID", "")
        self.client_secret = (
            client_secret or os.environ.get("BLIZZARD_CLIENT_SECRET") or env.get("BLIZZARD_CLIENT_SECRET", "")
        )
        self.region = (region or os.environ.get("BLIZZARD_REGION") or env.get("BLIZZARD_REGION", "eu")).lower()
        self.locale = locale or os.environ.get("BLIZZARD_LOCALE") or env.get("BLIZZARD_LOCALE", "de_DE")

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

        # Candidate namespaces in priority order for WoW Forever & Classic
        self.candidate_namespaces = [
            f"static-forever-{self.region}",
            f"static-wowf-{self.region}",
            f"static-classic1x-{self.region}",
            f"static-classic-{self.region}",
            f"static-{self.region}",
        ]

    @property
    def is_configured(self) -> bool:
        """Returns True if client credentials are present."""
        return bool(self.client_id.strip() and self.client_secret.strip())

    def get_token(self) -> Optional[str]:
        """Fetches or reuses a cached OAuth2 access token."""
        if not self.is_configured:
            return None

        # Reuse valid token if >60s remaining
        if self._token and time.time() < (self._token_expires_at - 60):
            return self._token

        token_url = "https://oauth.battle.net/token"
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded_cred = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

        headers = {
            "Authorization": f"Basic {encoded_cred}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "WoW-Forever-Solver/1.0",
        }
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")

        try:
            req = urllib.request.Request(token_url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                self._token = res_json.get("access_token")
                expires_in = res_json.get("expires_in", 86400)
                self._token_expires_at = time.time() + float(expires_in)
                return self._token
        except Exception as e:
            print(f"[BlizzardAPI] OAuth token request failed: {e}")
            return None

    def query(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Makes an authenticated GET request to Blizzard Game Data API with automatic namespace fallback."""
        token = self.get_token()
        if not token:
            return None

        base_params = {"locale": self.locale}
        if params:
            base_params.update(params)

        for ns in self.candidate_namespaces:
            req_params = dict(base_params)
            req_params["namespace"] = ns
            url = f"https://{self.region}.api.blizzard.com{path}?{urllib.parse.urlencode(req_params)}"

            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "WoW-Forever-Solver/1.0",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                if err.code in (404, 403):
                    continue  # Try next candidate namespace
                print(f"[BlizzardAPI] HTTP Error {err.code} for {url}")
            except Exception as e:
                print(f"[BlizzardAPI] Request failed for {url}: {e}")

        return None

    def get_spell_media(self, spell_id: int) -> Optional[str]:
        """Returns the high-res icon image URL for a spell ID, or None."""
        data = self.query(f"/data/wow/media/spell/{spell_id}")
        if data and "assets" in data:
            for asset in data["assets"]:
                if asset.get("key") == "icon":
                    return asset.get("value")
        return None

    def get_item_media(self, item_id: int) -> Optional[str]:
        """Returns the high-res icon image URL for an item ID, or None."""
        data = self.query(f"/data/wow/media/item/{item_id}")
        if data and "assets" in data:
            for asset in data["assets"]:
                if asset.get("key") == "icon":
                    return asset.get("value")
        return None

    def get_item_data(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Returns official item data (name, quality, level, stats) for an item ID."""
        return self.query(f"/data/wow/item/{item_id}")
