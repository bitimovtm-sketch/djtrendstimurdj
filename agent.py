import os
import re
import json
import requests
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def escape_md(text):
    text = str(text)
    for ch in r"_*[]()~`>#+-=|{}.!\\":
        text = text.replace(ch, "\\" + ch)
    return text


# ---------- Spotify ----------
def get_spotify_token():
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("Spotify: credentials missing")
        return None
    try:
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        print(f"Spotify token: HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"  body: {r.text[:200]}")
            return None
        return r.json().get("access_token")
    except Exception as e:
        print(f"Spotify auth exception: {e}")
        return None


def get_spotify_tracks(token):
    if not token:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    tracks, seen = [], set()
    queries = ['genre:"house" year:2026', 'genre:"deep-house"', 'genre:"tech-house"']
    for q in queries:
        try:
            r = requests.get(
                "https://api.spotify.com/v1/search",
                headers=headers,
                params={"q": q, "type": "track", "limit": 8, "market": "US"},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"Spotify search '{q}': HTTP {r.status_code} {r.text[:120]}")
                continue
            items = r.json().get("tracks", {}).get("items", [])
            for track in items:
                if not track:
                    continue
                name = track["name"]
                artist = ", ".join(a["name"] for a in track["artists"])
                url = track["external_urls"].get("spotify", "")
                pop = track.get("popularity", 0)
                key = f"{name.lower()}|{artist.lower()}"
                if key not in seen:
                    seen.add(key)
                    tracks.append({"title": name, "artist": artist, "url": url,
                                   "source": "Spotify", "pop": pop})
        except Exception as e:
            print(f"Spotify search '{q}' exception: {e}")
    tracks.sort(key=lambda t: t["pop"], reverse=True)
    return tracks[:12]


# ---------- Deezer (public API, no key) ----------
def get_deezer_tracks():
    """Deezer public API. Pull tracks from real house/electro genre playlists
    (editorial), not text search — so only actual genre tracks come through."""
    tracks, seen = [], set()
    try:
        # Find editorial playlists that are genuinely house/electro, then read their tracks.
        # Deezer search?type=playlist returns curated playlists; we keep only on-genre ones.
        playlist_queries = ["deep house", "tech house", "house music", "afro house"]
        playlist_ids = []
        for q in playlist_queries:
            r = requests.get(
                "https://api.deezer.com/search/playlist",
                params={"q": q, "limit": 2},
                headers={"User-Agent": UA},
                timeout=15,
            )
            print(f"Deezer playlist search '{q}': HTTP {r.status_code}")
            if r.status_code != 200:
                continue
            for pl in r.json().get("data", []):
                title = (pl.get("title") or "").lower()
                # keep only playlists whose title actually signals the genre
                if "house" in title and pl.get("id"):
                    playlist_ids.append(pl["id"])

        for pid in playlist_ids[:5]:
            r = requests.get(
                f"https://api.deezer.com/playlist/{pid}/tracks",
                params={"limit": 6},
                headers={"User-Agent": UA},
                timeout=15,
            )
            if r.status_code != 200:
                continue
            data = r.json().get("data", [])
            data.sort(key=lambda t: t.get("rank", 0), reverse=True)
            for item in data[:6]:
                name = item.get("title", "")
                artist = item.get("artist", {}).get("name", "")
                url = item.get("link", "")
                key = f"{name.lower()}|{artist.lower()}"
                if name and artist and key not in seen:
                    seen.add(key)
                    tracks.append({"title": name, "artist": artist,
                                   "url": url, "source": "Deezer"})
    except Exception as e:
        print(f"Deezer exception: {e}")
    return tracks[:12]


# ---------- Bandcamp (public tag page data) ----------
def get_bandcamp_tracks():
    """Bandcamp has no clean public tracks API. We read the genre tag page
    and pull the embedded data island (most stable public method)."""
    tracks, seen = [], set()
    try:
        for tag in ["house", "deep-house", "tech-house"]:
            r = requests.get(
                f"https://bandcamp.com/tag/{tag}?tab=all_releases",
                headers={"User-Agent": UA},
                timeout=15,
            )
            print(f"Bandcamp '{tag}': HTTP {r.status_code}")
            if r.status_code != 200:
                continue
            # Bandcamp embeds JSON in a data-blob attribute
            m = re.search(r'data-blob="([^"]+)"', r.text)
            if not m:
                print(f"Bandcamp '{tag}': data-blob not found")
                continue
            import html as _html
            blob = json.loads(_html.unescape(m.group(1)))
            # Navigate to the items list (structure: hub -> dig_deeper or tabs)
            items = []
            hub = blob.get("hub", {})
            for tab in hub.get("tabs", []):
                for coll in tab.get("collections", []):
                    items.extend(coll.get("items", []))
            for item in items[:6]:
                name = item.get("title", "")
                artist = item.get("artist", "") or item.get("band_name", "")
                url = item.get("tralbum_url") or item.get("url", "")
                key = f"{name.lower()}|{artist.lower()}"
                if name and artist and key not in seen:
                    seen.add(key)
                    tracks.append({"title": name, "artist": artist,
                                   "url": url, "source": "Bandcamp"})
    except Exception as e:
        print(f"Bandcamp exception: {e}")
    return tracks[:10]


# ---------- Beatport ----------
def get_beatport_tracks():
    tracks = []
    try:
        r = requests.get("https://www.beatport.com/genre/house/5/top-100",
                         headers={"User-Agent": UA}, timeout=15)
        print(f"Beatport: HTTP {r.status_code}")
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text, re.S)
        if not m:
            print("Beatport: __NEXT_DATA__ not found")
            return []
        data = json.loads(m.group(1))
        queries = data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
        for q in queries:
            results = q.get("state", {}).get("data", {})
            if isinstance(results, dict):
                results = results.get("results") or results.get("data") or []
            if isinstance(results, list) and results:
                for item in results[:10]:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name") or item.get("mix_name") or ""
                    artists = item.get("artists", [])
                    artist = ", ".join(a.get("name", "") for a in artists) if artists else ""
                    slug, tid = item.get("slug", ""), item.get("id", "")
                    if name and artist:
                        tracks.append({"title": name, "artist": artist, "source": "Beatport",
                                       "url": f"https://www.beatport.com/track/{slug}/{tid}" if slug and tid
                                              else "https://www.beatport.com/genre/house/5/top-100"})
                if tracks:
                    break
    except Exception as e:
        print(f"Beatport exception: {e}")
    return tracks[:10]


# ---------- Format & send ----------
def deduplicate(all_tracks):
    seen, result = set(), []
    for t in all_tracks:
        key = f"{t['title'].lower()[:30]}|{t['artist'].lower()[:20]}"
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def format_message(tracks):
    week = datetime.now().strftime("%d.%m.%Y")
    lines = ["🎵 *House Music — топ недели " + escape_md(week) + "*\n"]
    by_source = {}
    for t in tracks:
        by_source.setdefault(t["source"], []).append(t)
    icons = {"Beatport": "🔴", "Spotify": "🟢", "Deezer": "🟣", "Bandcamp": "🔵"}
    for source, items in by_source.items():
        if not items:
            continue
        lines.append("\n" + icons.get(source, "▪️") + " *" + escape_md(source) + "*")
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
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
              "parse_mode": "MarkdownV2", "disable_web_page_preview": True},
        timeout=15,
    )
    if r.status_code != 200:
        print(f"Telegram error {r.status_code}: {r.text}")
        plain = re.sub(r"\\(.)", r"\1", text)
        plain = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 — \2", plain).replace("*", "")
        r2 = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": plain, "disable_web_page_preview": True},
            timeout=15,
        )
        print(f"Telegram plain fallback: HTTP {r2.status_code}")
        return
    print("Telegram: sent OK")


def main():
    print("Fetching tracks...")
    all_tracks = []

    token = get_spotify_token()
    sp = get_spotify_tracks(token)
    print(f"=> Spotify: {len(sp)}")
    all_tracks += sp

    dz = get_deezer_tracks()
    print(f"=> Deezer: {len(dz)}")
    all_tracks += dz

    bc = get_bandcamp_tracks()
    print(f"=> Bandcamp: {len(bc)}")
    all_tracks += bc

    bp = get_beatport_tracks()
    print(f"=> Beatport: {len(bp)}")
    all_tracks += bp

    unique = deduplicate(all_tracks)
    print(f"=> Total unique: {len(unique)}")

    if not unique:
        send_telegram(escape_md("⚠️ House Agent: источники недоступны на этой неделе. Загляните в логи GitHub Actions."))
        return

    send_telegram(format_message(unique))


if __name__ == "__main__":
    main()
