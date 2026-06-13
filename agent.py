import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")


def get_beatport_top10():
    """Scrape Beatport House Top 10"""
    tracks = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get("https://www.beatport.com/genre/house/5/top-100", headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        # Beatport renders via JS, so we grab what's in the static HTML meta/title tags
        # and fall back to their chart page title data
        items = soup.select("li.bucket-item")[:10]
        for item in items:
            title_el = item.select_one(".buk-track-title")
            artist_el = item.select_one(".buk-track-artists")
            if title_el and artist_el:
                tracks.append({
                    "title": title_el.get_text(strip=True),
                    "artist": artist_el.get_text(strip=True),
                    "source": "Beatport",
                    "url": "https://www.beatport.com/genre/house/5/top-100"
                })
    except Exception as e:
        print(f"Beatport error: {e}")
    return tracks


def get_spotify_token():
    """Get Spotify access token via client credentials"""
    if not SPOTIFY_CLIENT_ID:
        return None
    try:
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
            timeout=10
        )
        return r.json().get("access_token")
    except Exception as e:
        print(f"Spotify auth error: {e}")
        return None


def get_spotify_tracks(token):
    """Fetch tracks from Spotify editorial house playlists"""
    tracks = []
    if not token:
        return tracks

    # Spotify editorial house playlists (public, stable IDs)
    playlist_ids = [
        "37i9dQZF1DX6J5NfMJS675",  # Dance Rising
        "37i9dQZF1DXa8NOjJkEOQL",  # House music lives here (ANOTR curated)
    ]

    headers = {"Authorization": f"Bearer {token}"}
    seen = set()

    for pid in playlist_ids:
        try:
            r = requests.get(
                f"https://api.spotify.com/v1/playlists/{pid}/tracks",
                headers=headers,
                params={"limit": 5, "fields": "items(track(name,artists,external_urls))"},
                timeout=10
            )
            for item in r.json().get("items", []):
                track = item.get("track")
                if not track:
                    continue
                name = track["name"]
                artist = ", ".join(a["name"] for a in track["artists"])
                url = track["external_urls"].get("spotify", "")
                key = f"{name}|{artist}"
                if key not in seen:
                    seen.add(key)
                    tracks.append({"title": name, "artist": artist, "source": "Spotify", "url": url})
        except Exception as e:
            print(f"Spotify playlist {pid} error: {e}")

    return tracks[:10]


def get_1001tracklists():
    """Scrape 1001tracklists trending house tracks"""
    tracks = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get("https://www.1001tracklists.com/genre/house/", headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select(".tlpItem")[:10]
        for item in items:
            title_el = item.select_one(".trackValue")
            artist_el = item.select_one(".artistName")
            if title_el:
                tracks.append({
                    "title": title_el.get_text(strip=True),
                    "artist": artist_el.get_text(strip=True) if artist_el else "",
                    "source": "1001Tracklists",
                    "url": "https://www.1001tracklists.com/genre/house/"
                })
    except Exception as e:
        print(f"1001tracklists error: {e}")
    return tracks


def get_ra_charts():
    """Scrape Resident Advisor top tracks"""
    tracks = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get("https://ra.co/tracks", headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        # RA renders via Next.js; grab __NEXT_DATA__ JSON
        import json, re
        script = soup.find("script", id="__NEXT_DATA__")
        if script:
            data = json.loads(script.string)
            # Navigate to tracks list — path may vary by RA version
            try:
                items = data["props"]["pageProps"]["data"]["topTracks"]["data"][:5]
                for item in items:
                    tracks.append({
                        "title": item.get("title", ""),
                        "artist": item.get("artists", [{}])[0].get("name", ""),
                        "source": "Resident Advisor",
                        "url": f"https://ra.co/tracks/{item.get('id', '')}"
                    })
            except (KeyError, TypeError):
                pass
    except Exception as e:
        print(f"RA error: {e}")
    return tracks


def deduplicate(all_tracks):
    """Remove duplicates by title+artist similarity"""
    seen = set()
    result = []
    for t in all_tracks:
        key = f"{t['title'].lower()[:30]}|{t['artist'].lower()[:20]}"
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def format_message(tracks):
    week = datetime.now().strftime("%-d %B %Y")
    lines = [f"🎵 *House Music — топ треков недели {week}*\n"]

    by_source = {}
    for t in tracks:
        by_source.setdefault(t["source"], []).append(t)

    icons = {"Beatport": "🔴", "Spotify": "🟢", "1001Tracklists": "🔵", "Resident Advisor": "🟡"}

    for source, items in by_source.items():
        if not items:
            continue
        lines.append(f"\n{icons.get(source, '▪️')} *{source}*")
        for i, t in enumerate(items, 1):
            title = t["title"] or "—"
            artist = t["artist"] or "—"
            url = t.get("url", "")
            if url:
                lines.append(f"{i}\\. [{artist} — {title}]({url})")
            else:
                lines.append(f"{i}\\. {artist} — {title}")

    lines.append("\n_Обновляется каждый понедельник автоматически_")
    return "\n".join(lines)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True
    }, timeout=10)
    r.raise_for_status()
    print(f"Sent to Telegram: {r.status_code}")


def main():
    print("Fetching tracks...")

    spotify_token = get_spotify_token()

    all_tracks = []
    all_tracks += get_beatport_top10()
    all_tracks += get_spotify_tracks(spotify_token)
    all_tracks += get_1001tracklists()
    all_tracks += get_ra_charts()

    unique = deduplicate(all_tracks)
    print(f"Total unique tracks: {len(unique)}")

    if not unique:
        send_telegram("⚠️ House Agent: не удалось получить треки на этой неделе\\. Проверьте логи\\.")
        return

    msg = format_message(unique)
    send_telegram(msg)


if __name__ == "__main__":
    main()
