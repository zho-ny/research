import gzip
import json
import random
import sys
import time
import urllib.request
from base64 import b64encode
from datetime import datetime, timezone

CHANNEL = sys.argv[1] if len(sys.argv) > 1 else "akiiimoto"
DURATION_MIN = float(sys.argv[2]) if len(sys.argv) > 2 else 6
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
rnd = random.Random()
DEVICE_ID = "".join(rnd.choice("0123456789abcdef") for _ in range(32))
APP_SESSION = "".join(rnd.choice("0123456789abcdef") for _ in range(32))
PAGE_SESSION = "".join(rnd.choice("0123456789abcdef") for _ in range(32))
TAB_SESSION = "".join(rnd.choice("0123456789abcdef") for _ in range(32))


def ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def post(url, body, headers):
    req = urllib.request.Request(url, data=body.encode() if isinstance(body, str) else body, headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=15).read().decode()


def gql(payload):
    r = post(
        "https://gql.twitch.tv/gql",
        json.dumps(payload),
        {"Client-Id": CLIENT_ID, "User-Agent": UA, "Content-Type": "application/json"},
    )
    return json.loads(r)


def get_viewers(ch):
    d = gql({"query": '{ user(login: "%s") { stream { viewersCount } } }' % ch})
    return d["data"]["user"]["stream"]["viewersCount"]


def get_pat(ch):
    d = gql(
        {
            "operationName": "PlaybackAccessToken_Template",
            "query": 'query PlaybackAccessToken_Template($login: String!, $isLive: Boolean!, $vodID: ID!, $isVod: Boolean!, $playerType: String!, $platform: String!) {  streamPlaybackAccessToken(channelName: $login, params: {platform: $platform, playerBackend: "mediaplayer", playerType: $playerType}) @include(if: $isLive) {    value    signature   authorization { isForbidden forbiddenReasonCode }   __typename  }  videoPlaybackAccessToken(id: $vodID, params: {platform: $platform, playerBackend: "mediaplayer", playerType: $playerType}) @include(if: $isVod) {    value    signature   __typename  }}',
            "variables": {"isLive": True, "login": ch, "isVod": False, "vodID": "", "playerType": "site", "platform": "web"},
        }
    )
    at = d["data"]["streamPlaybackAccessToken"]
    return at["value"], at["signature"]


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=15).read()


def send_spade(events):
    raw = json.dumps({"events": events}).encode()
    payload = b64encode(gzip.compress(raw)).decode()
    body = "data=" + urllib.parse.quote(payload)
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql",
        data=body.encode(),
        headers={"Client-Id": CLIENT_ID, "User-Agent": UA, "Content-Type": "text/plain"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=15).read().decode()


import urllib.parse


def minute_watched(channel, channel_id, broadcast_id, cluster, manifest_cluster, manifest_node, bitrate, fps):
    now = datetime.now(timezone.utc)
    return {
        "event": "minute-watched",
        "properties": {
            "broadcast_id": broadcast_id,
            "channel": channel,
            "channel_id": channel_id,
            "cluster": cluster,
            "device_id": DEVICE_ID,
            "user_id": "",
            "app_session_id": APP_SESSION,
            "page_session_id": PAGE_SESSION,
            "tab_session_id": TAB_SESSION,
            "player": "site",
            "statio": "twitch",
            "server_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sequence": 1,
            "signed_in": False,
            "vod": False,
            "live": True,
            "bitrate_kbps": bitrate,
            "fps": fps,
            "viewing_session_id": APP_SESSION,
            "content_type": "live",
            "video_codec": "h264",
            "audio_codec": "aac",
            "rendering_surface": "html5 video",
            "manifest_cluster": manifest_cluster,
            "manifest_node": manifest_node,
        },
    }


def main():
    baseline = get_viewers(CHANNEL)
    print(f"[{ts()}] baseline viewers: {baseline}", flush=True)
    value, sig = get_pat(CHANNEL)
    tv = json.loads(value)
    channel_id = tv["channel_id"]
    print(f"[{ts()}] pat ok: channel_id={channel_id}", flush=True)
    q = urllib.parse.urlencode({"sig": sig, "token": value, "allow_source": "true", "fast_bread": "true"})
    master = http_get(f"https://usher.ttvnw.net/api/channel/hls/{CHANNEL}.m3u8?{q}").decode()
    info = {}
    rends = []
    attrs = None
    for ln in master.splitlines():
        if ln.startswith("#EXT-X-TWITCH-INFO:"):
            for part in ln.split(":", 1)[1].split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    info[k.strip('"')] = v.strip('"')
        elif ln.startswith("#EXT-X-STREAM-INF:"):
            attrs = dict(p.split("=", 1) for p in ln.split(":", 1)[1].split(",") if "=" in p)
        elif ln and not ln.startswith("#"):
            rends.append({"url": ln, "attrs": attrs})
    broadcast_id = info.get("BROADCAST-ID", "")
    cluster = info.get("CLUSTER", "")
    manifest_cluster = info.get("MANIFEST-CLUSTER", "")
    manifest_node = info.get("MANIFEST-NODE", "")
    rend = min(rends, key=lambda r: int(r["attrs"].get("BANDWIDTH", "0")))
    bitrate = int(rend["attrs"].get("BANDWIDTH", "230000"))
    fps = float(rend["attrs"].get("FRAME-RATE", "30.0"))
    print(f"[{ts()}] usher ok: broadcast_id={broadcast_id} cluster={cluster} renditions={len(rends)}", flush=True)

    seen = set()
    start = time.time()
    next_minute = start + 60
    next_check = start + 30
    while time.time() - start < DURATION_MIN * 60:
        try:
            pl = http_get(rend["url"]).decode()
            segs = [ln for ln in pl.splitlines() if ln and not ln.startswith("#")]
            new = [s for s in segs if s not in seen]
            for s in new:
                seen.add(s)
                try:
                    http_get(s)
                except Exception:
                    pass
            if new:
                print(f"[{ts()}] playlist ok: {len(segs)} total, fetched {len(new)}", flush=True)
        except Exception as e:
            print(f"[{ts()}] playlist err: {type(e).__name__}", flush=True)
            time.sleep(2)
            continue
        now = time.time()
        if now >= next_minute:
            next_minute += 60
            try:
                code = send_spade(
                    [minute_watched(CHANNEL, channel_id, broadcast_id, cluster, manifest_cluster, manifest_node, bitrate, fps)]
                )
                print(f"[{ts()}] minute-watched: {code[:80]}", flush=True)
            except Exception as e:
                print(f"[{ts()}] spade err: {type(e).__name__}", flush=True)
        if now >= next_check:
            next_check += 30
            try:
                print(f"[{ts()}] viewers: {get_viewers(CHANNEL)}", flush=True)
            except Exception as e:
                print(f"[{ts()}] viewers err: {type(e).__name__}", flush=True)
        time.sleep(2)
    print(f"[{ts()}] final viewers: {get_viewers(CHANNEL)}", flush=True)
    print(f"[{ts()}] done", flush=True)


if __name__ == "__main__":
    main()
