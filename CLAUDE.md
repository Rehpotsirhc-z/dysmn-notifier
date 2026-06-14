# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A single-file Python script (`main.py`) that checks a Spotify artist's full discography and posts a Discord webhook message when new releases appear. It is designed to run as a cron job inside Docker, hourly.

## Architecture

Everything lives in `main.py`. The flow in `main()`:

1. Get an **anonymous web access token** the way `open.spotify.com` does (`get_web_access_token`) — no developer API key and no login. It signs the request with a TOTP (`compute_totp`) and hits `https://open.spotify.com/api/token`.
2. Fetch the artist's full discography (`get_all_artist_albums`) via Spotify's **internal pathfinder GraphQL API** (`api-partner.spotify.com`, `queryArtistDiscographyAll`), paginating by offset. Each release node is normalized by `parse_release` into the public-Web-API object shape (`id`, `name`, `album_type`, `release_date`, `external_urls`) so the rest of the code is source-agnostic.
3. Diff against `known_album_ids.txt` to find releases whose IDs aren't yet known.
4. Notify Discord (`send_discord_notification`) and then overwrite the known-IDs file with the current full set.

**Why pathfinder and not the public developer API:** the documented `GET /v1/artists/{id}/albums` endpoint is served from a catalog index that lags brand-new releases by many hours (observed ~16h for one release). The pathfinder backend is what the web player renders, so it reflects a release as soon as you can see it in the web UI — which is the whole point of this bot. Tradeoff: it's unofficial and depends on the rotating constants below.

**First-run behavior is deliberate and important:** if `known_album_ids.txt` does not exist, `load_known_ids()` returns `None`. The script then seeds the file with all current releases and sends **no** notification — this prevents a flood of alerts for the entire back catalog on first launch. Only an existing-but-changed file triggers notifications. Preserve this `None`-vs-empty-set distinction in any refactor.

**Empty/short-result guard:** because the data source is unofficial, `main()` bails (no notify, no save) if the fetch fails, returns nothing, or returns *fewer* albums than are already known. This stops a transient API blip from wiping state or spamming false "new release" alerts.

State is a flat newline-delimited list of Spotify album IDs in `known_album_ids.txt` (gitignored, mounted as a Docker volume so it survives container restarts).

## Rotating constants (the maintenance points)

Two constants near the top of `main.py` are scraped from the live web player and **Spotify rotates them**, which is what breaks this bot:

- `TOTP_SECRET` / `TOTP_VER` — if the token request returns `400` with `"totpVerExpired"`, they're stale.
- `DISCOGRAPHY_QUERY_HASH` — if pathfinder returns `"PersistedQueryNotFound"`, it's stale.

To refresh, pull the current web player JS and grep it:

1. `GET https://open.spotify.com/` → find the `web-player.<hash>.js` bundle URL.
2. In that JS, the secret/version live in an array like `[{secret:'…',version:61},…]` (highest version is current); the query hash is in `new …("queryArtistDiscographyAll","query","<64-hex-hash>")`.
3. Note the TOTP secret is now a **string** XOR'd by char code (`ord(c) ^ (i%33+9)`), joined into a digit string whose UTF-8 bytes are the HMAC key (`compute_totp` already does this).

## Configuration

All config is via environment variables (read at module load in `main.py`):

- `SPOTIFY_ARTIST_ID` — the artist to watch
- `DISCORD_WEBHOOK_URL` — if unset, the script runs but skips notifications

No Spotify API key is needed (the bot uses the keyless web-player token flow). `docker-compose.yml` reads `ARTIST_ID` from `.env` and maps it to `SPOTIFY_ARTIST_ID`. A local `.env` (gitignored) supplies that plus the gluetun VPN vars; the old `CLIENT_ID`/`CLIENT_SECRET` entries are now unused.

The bot egresses through the **Auckland (NZ) gluetun VPN**, so the anonymous token + NZ IP return the NZ regional catalog — matching what you'd see in the web UI through that VPN, where this artist's releases appear at NZ midnight.

## Running

Run locally (requires the env vars set):

```bash
pip install requests
python main.py
```

Run via Docker (the intended deployment):

```bash
docker compose up --build
```

The container traffic is routed through a **gluetun** ProtonVPN/WireGuard sidecar (`network_mode: "service:gluetun-dysmn"`), so the notifier has no direct network stack of its own — it depends on the gluetun container being up.

## Scheduling

There is no internal scheduler. The `Dockerfile` installs `cron` and registers a job that runs `main.py` at **1 minute past every hour**. To change the cadence, edit the cron line in the `Dockerfile`. Cron logs are redirected to PID 1's stdout so they surface via `docker logs`.
