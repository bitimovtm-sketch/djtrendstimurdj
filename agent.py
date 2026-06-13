import os
import requests
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


# ---------- Spotify ----------
def get_spotify_token():
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("Spotify: no credentials, skipping")
        return None
    try:
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("access_token")
    except Exception as e:
        print(f"Spotify auth error: {e}")
        return None


def spotify_search_playlists(token, queries):
    """Find playlist IDs by search query (more robust than hardcoded IDs)."""
    headers = {"Authorization": f"Bearer {token}"}
    ids = []
    for q in queries:
        try:
            r = requests.get(
                "https://api.spotify.com/v1/search",
                headers=headers,
                params={"q": q, "type": "playlist", "limit": 1},
                timeout=15,
            )
            items = r.json().get("playlists", {}).get("items", [])
            if items and items[0]:
                ids.append(items[0]["id"])
        except Exception as e:
            print(f"Spotify search '{q}' error: {e}")
    return ids


def get_spotify_tracks(token):
    if not token:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    tracks = []
    seen = set()

    playlist_ids = spotify_search_playlists(
        token, ["Housewerk", "Dance Rising", "Tech House", "Deep House Relax"]
    )

    for pid in playlist_ids:
        try:
            r = requests.get(
                f"https://api.spotify.com/v1/playlists/{pid}/tracks",
                headers=headers,
                params={"limit": 6, "fields": "items(track(name,artists,external_urls,popularity))"},
                timeout=15,
            )
            for item in r.json().get("items", []):
                track = item.get("track")
                if not track:
                    continue
                name = track["name"]
                artist = ", ".join(a["name"] for a in track["artists"])
                url = track["external_urls"].get("spotify", "")
                key = f"{name.lower()}|{artist.lower()}"
                if key not in seen:
                    seen.add(key)
                    tracks.append({"title": name, "artist": artist, "source": "Spotify", "url": url})
        except Exception as e:
            print(f"Spotify playlist {pid} error: {e}")

    return tracks[:12]


# ---------- Beatport (via embed API) ----------
def get_beatport_tracks():
    """Beatport has a JSON API at api.beatport.com used by their site."""
    tracks = []
    try:
        # Public Next.js data endpoint for the House genre top-100 page
        r = requests.get(
            "https://www.beatport.com/genre/house/5/top-100",
            headers={"User-Agent": UA},
            timeout=15,
        )
        text = r.text
        # Beatport embeds a JSON blob in __NEXT_DATA__
        import re, json
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', text, re.S)
        if m:
            data = json.loads(m.group(1))
            # Walk to dehydrated react-query state
            queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
            for q in queries:
                state = q.get("state", {})
                d = state.get("data", {})
                results = d.get("results") or d.get("data") or []
                if isinstance(results, list):
                    for item in results[:10]:
                        name = item.get("name") or item.get("mix_name") or ""
                        artists = item.get("artists", [])
                        artist = ", ".join(a.get("name", "") for a in artists) if artists else ""
                        slug = item.get("slug", "")
                        tid = item.get("id", "")
                        if name and artist:
                            tracks.append({
                                "title": name,
                                "artist": artist,
                                "source": "Beatport",
                                "url": f"https://www.beatport.com/track/{slug}/{tid}" if slug and tid else "https://www.beatport.com/genre/house/5/top-100",
                            })
                    if tracks:
                        break
    except Exception as e:
        print(f"Beatport error: {e}")
    return tracks[:10]


# ---------- Format & send ----------
def deduplicate(all_tracks):
    seen = set()
    result = []
    for t in all_tracks:
        key = f"{t['title'].lower()[:30]}|{t['artist'].lower()[:20]}"
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def escape_md(text):
    """Escape MarkdownV2 special chars."""
    for ch in r"_*[]()~`>#+-=|{}.!\\":
        text = text.replace(ch, f"\\{ch}")
    return text


def format_message(tracks):
    week = datetime.now().strftime("%d.%m.%Y")
    lines = [f"🎵 *House Music — топ недели {escape_md(week)}*\n"]

    by_source = {}
    for t in tracks:
        by_source.setdefault(t["source"], []).append(t)

    icons = {"Beatport": "🔴", "Spotify": "🟢"}

    for source, items in by_source.items():
        if not items:
            continue
        lines.append(f"\n{icons.get(source, '▪️')} *{escape_md(source)}*")
        for i, t in enumerate(items, 1):
            title = escape_md(t["title"] or "—")
            artist = escape_md(t["artist"] or "—")
            url = t.get("url", "")
            if url:
                lines.append(f"{i}\\. [{artist} — {title}]({url})")
            else:
                lines.append(f"{i}\\. {artist} — {title}")

    lines.append("\n_Обновляется автоматически каждый понедельник_")
    return "\n".join(lines)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }, timeout=15)
    if r.status_code != 200:
        print(f"Telegram error {r.status_code}: {r.text}")
    r.raise_for_status()
    print("Sent to Telegram OK")


def main():
    print("Fetching tracks...")
    all_tracks = []

    token = get_spotify_token()
    sp = get_spotify_tracks(token)
    print(f"Spotify: {len(sp)} tracks")
    all_tracks += sp

    bp = get_beatport_tracks()
    print(f"Beatport: {len(bp)} tracks")
    all_tracks += bp

    unique = deduplicate(all_tracks)
    print(f"Total unique: {len(unique)}")

    if not unique:
        send_telegram(escape_md("⚠️ House Agent: источники не вернули треков на этой неделе. Проверьте логи Actions."))
        return

    send_telegram(format_message(unique))


if __name__ == "__main__":
    main()
