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


# ---------- Bandcamp (Discover API - verified structure) ----------
def get_bandcamp_tracks():
    """POST to the same endpoint the /discover/house page uses.
    Verified response shape: {"results": [{"title","band_name","item_url",
    "band_genre_id","featured_track":{...}}]}. genre_id 10 = electronic."""
    tracks, seen = [], set()
    url = "https://bandcamp.com/api/discover/1/discover_web"
    # Try a few payload shapes; the site sends a discover_spec describing the genre.
    payloads = [
        {"tag_norm_names": ["house"], "category_id": 0, "geoname_id": 0,
         "slice": "top", "time_facet_id": None, "cursor": "*", "size": 60,
         "include_result_types": ["a", "t"]},
        {"slug": "house", "category_id": 0, "size": 60, "cursor": "*"},
        {"genre_id": 10, "tag_norm_names": ["house"], "size": 60, "cursor": "*"},
    ]
    for payload in payloads:
        try:
            r = requests.post(url, json=payload,
                             headers={"User-Agent": UA,
                                      "Content-Type": "application/json",
                                      "Accept": "application/json",
                                      "Referer": "https://bandcamp.com/discover/house"},
                             timeout=15)
            print(f"Bandcamp discover_web: HTTP {r.status_code}")
            if r.status_code != 200:
                continue
            try:
                data = r.json()
            except Exception:
                print(f"Bandcamp: non-JSON for payload keys {list(payload.keys())}")
                continue
            results = data.get("results", [])
            if not results:
                continue
            for item in results:
                if not isinstance(item, dict):
                    continue
                # prefer the featured track title if present, else album title
                ft = item.get("featured_track") or {}
                name = (ft.get("title") if isinstance(ft, dict) else None) or item.get("title", "")
                artist = item.get("band_name") or item.get("album_artist") or ""
                bc_url = item.get("item_url", "")
                if bc_url:
                    bc_url = bc_url.split("?")[0]  # strip ?from=discover_page
                name, artist = str(name).strip(), str(artist).strip()
                key = f"{name.lower()}|{artist.lower()}"
                if name and artist and key not in seen:
                    seen.add(key)
                    tracks.append({"title": name, "artist": artist,
                                   "url": bc_url, "source": "Bandcamp"})
            if tracks:
                break
        except Exception as e:
            print(f"Bandcamp discover_web exception: {e}")
    if not tracks:
        print("Bandcamp: no items from Discover API")
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


def escape_html(text):
    """HTML parse_mode needs only these three escaped."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def format_message(tracks):
    week = datetime.now().strftime("%d.%m.%Y")
    lines = ["🎵 <b>House Music — топ недели " + escape_html(week) + "</b>\n"]
    by_source = {}
    for t in tracks:
        by_source.setdefault(t["source"], []).append(t)
    icons = {"Beatport": "🔴", "Spotify": "🟢", "Deezer": "🟣", "Bandcamp": "🔵"}
    for source, items in by_source.items():
        if not items:
            continue
        lines.append("\n" + icons.get(source, "▪️") + " <b>" + escape_html(source) + "</b>")
        for i, t in enumerate(items, 1):
            title = escape_html(t["title"] or "—")
            artist = escape_html(t["artist"] or "—")
            url = escape_html(t.get("url", ""))
            if url:
                lines.append(f'{i}. <a href="{url}">{artist} — {title}</a>')
            else:
                lines.append(f"{i}. {artist} — {title}")
    lines.append("\n<i>Обновляется автоматически каждый понедельник</i>")
    return "\n".join(lines)


def send_telegram(text, html=True):
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text,
               "disable_web_page_preview": True}
    if html:
        payload["parse_mode"] = "HTML"
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json=payload, timeout=15,
    )
    if r.status_code != 200:
        print(f"Telegram error {r.status_code}: {r.text}")
        # Fallback: strip tags, send plain
        plain = re.sub(r"<a href=\"([^\"]+)\">([^<]+)</a>", r"\2 — \1", text)
        plain = re.sub(r"</?[^>]+>", "", plain)
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
        send_telegram("⚠️ House Agent: источники недоступны на этой неделе. Загляните в логи GitHub Actions.", html=False)
        return

    send_telegram(format_message(unique))


if __name__ == "__main__":
    main()
