#!/usr/bin/env python3

import hashlib
import hmac
import json
import os
import struct
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

ARTIST_ID = os.getenv("SPOTIFY_ARTIST_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
KNOWN_IDS_FILE = "known_album_ids.txt"

# Maintenance constants Spotify rotates (pulled from open.spotify.com's JS):
# update TOTP_SECRET/TOTP_VER on token 400 "totpVerExpired",
# DISCOGRAPHY_QUERY_HASH on "PersistedQueryNotFound".
TOTP_SECRET = ',7/*F("rLJ2oxaKL^f+E1xvP@N'
TOTP_VER = 61
DISCOGRAPHY_QUERY_HASH = "5e07d323febb57b4a56a42abbf781490e58764aa45feb6e3dc0591564fc56599"

WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def compute_totp(timestamp_seconds):
    # XOR each secret char by (i%33+9), join as digits = HMAC key; then TOTP.
    key = "".join(str(ord(c) ^ (i % 33 + 9)) for i, c in enumerate(TOTP_SECRET)).encode()
    counter = int(timestamp_seconds) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % 1_000_000).zfill(6)


def get_web_access_token(session):
    """Fetch an anonymous token like open.spotify.com (no API key, no login)."""
    try:
        resp = session.get("https://open.spotify.com/server-time", timeout=15)
        resp.raise_for_status()
        server_time = int(resp.json()["serverTime"])
    except Exception:
        server_time = int(time.time())

    totp = compute_totp(server_time)
    params = {
        "reason": "init",
        "productType": "web-player",
        "totp": totp,
        "totpServer": totp,
        "totpVer": TOTP_VER,
        "ts": int(time.time()),
    }
    resp = session.get("https://open.spotify.com/api/token", params=params, timeout=15)
    resp.raise_for_status()
    token = resp.json().get("accessToken")
    if not token:
        raise RuntimeError(f"No accessToken in token response: {resp.text}")
    return token


def get_all_artist_albums(artist_id, token, session):
    """Full discography via the internal pathfinder API (fresh, matches the web UI)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "app-platform": "WebPlayer",
        "content-type": "application/json;charset=UTF-8",
        "accept": "application/json",
        "User-Agent": WEB_USER_AGENT,
    }
    albums = []
    offset = 0
    limit = 100
    while True:
        variables = {
            "uri": f"spotify:artist:{artist_id}",
            "offset": offset,
            "limit": limit,
            "order": "DATE_DESC",
        }
        extensions = {
            "persistedQuery": {"version": 1, "sha256Hash": DISCOGRAPHY_QUERY_HASH}
        }
        params = {
            "operationName": "queryArtistDiscographyAll",
            "variables": json.dumps(variables),
            "extensions": json.dumps(extensions),
        }
        resp = session.get(
            "https://api-partner.spotify.com/pathfinder/v1/query",
            headers=headers,
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if "errors" in payload:
            raise RuntimeError(f"pathfinder error: {payload['errors']}")

        discography = payload["data"]["artistUnion"]["discography"]["all"]
        items = discography["items"]
        for group in items:
            for release in group["releases"]["items"]:
                albums.append(parse_release(release))

        total = discography.get("totalCount", len(albums))
        offset += limit
        if offset >= total or not items:
            break

    return albums


def parse_release(release):
    album_id = release["id"]
    date_info = release.get("date", {})
    iso = date_info.get("isoString")
    if iso:
        release_date = iso[:10]
    else:
        y, m, d = date_info.get("year"), date_info.get("month"), date_info.get("day")
        parts = [f"{p:02d}" if i else f"{p:04d}" for i, p in enumerate([y, m, d]) if p]
        release_date = "-".join(parts) or "0000"
    return {
        "id": album_id,
        "name": release.get("name", ""),
        "album_type": (release.get("type") or "album").lower(),
        "release_date": release_date,
        "external_urls": {"spotify": f"https://open.spotify.com/album/{album_id}"},
    }


def load_known_ids():
    """Set of seen album IDs, or None on first run (file absent)."""
    if not os.path.exists(KNOWN_IDS_FILE):
        return None
    with open(KNOWN_IDS_FILE, "r") as f:
        return {line.strip() for line in f if line.strip()}


def save_known_ids(albums):
    with open(KNOWN_IDS_FILE, "w") as f:
        for album in albums:
            f.write(album["id"] + "\n")


def send_discord_notification(webhook_url, new_releases):
    message = "**New releases found!**\n"
    for a in new_releases:
        message += f"- [{a['name']}]({a['external_urls']['spotify']}) ({a['album_type']}) – {a['release_date']}\n"
    requests.post(webhook_url, json={"content": message})


def main():
    utc_time = datetime.now(timezone.utc)
    ny_time = utc_time.astimezone(ZoneInfo("America/New_York"))
    nz_time = utc_time.astimezone(ZoneInfo("Pacific/Auckland"))

    print(f"Current time (UTC): {utc_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Current time (America/New_York): {ny_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Current time (Pacific/Auckland): {nz_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    known_ids = load_known_ids()

    session = requests.Session()
    session.headers.update({"User-Agent": WEB_USER_AGENT})
    try:
        token = get_web_access_token(session)
        albums = get_all_artist_albums(ARTIST_ID, token, session)
    except Exception as e:
        print(f"\n⚠️  Failed to fetch releases from Spotify web backend: {e}")
        print("Skipping this run (state left unchanged, no notification sent).")
        return

    print(f"Total releases fetched: {len(albums)}")

    # An empty / short result means a bad fetch, not that releases were deleted.
    if not albums or (known_ids is not None and len(albums) < len(known_ids)):
        print(f"\n⚠️  Implausible result ({len(albums)} vs {len(known_ids or [])} known) – skipping.")
        return

    albums_sorted = sorted(albums, key=lambda a: a["release_date"], reverse=True)
    print("\nLatest 10 releases (any type):")
    for a in albums_sorted[:10]:
        print(f"- {a['name']} ({a['album_type']}) – {a['release_date']} {a['external_urls']['spotify']}")

    if known_ids is None:
        save_known_ids(albums)
        print("\nNo previous known IDs found. Initialised known_album_ids.txt with current releases.")
        print("No notifications sent this time – future runs will detect new releases.")
        return

    new_releases = [a for a in albums if a["id"] not in known_ids]

    if new_releases:
        print(f"\n✅ {len(new_releases)} new release(s) detected!")
        if DISCORD_WEBHOOK_URL:
            send_discord_notification(DISCORD_WEBHOOK_URL, new_releases)
            print("Discord notification sent.")
        else:
            print("Discord webhook not configured – skipping notification.")
    else:
        print(f"\nNo new releases – total known IDs: {len(known_ids)}.")

    save_known_ids(albums)


if __name__ == "__main__":
    main()
