import base64
import gzip
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CHANNEL = sys.argv[1] if len(sys.argv) > 1 else "gronkhtv"
DURATION_MIN = int(sys.argv[2]) if len(sys.argv) > 2 else 10
LOG = r"F:\recherche\Recherche\03-reproduktion\viewer_client.log"
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Firefox/142.0"
)

PROXY = None
OPENER = urllib.request.build_opener()

if len(sys.argv) > 5:
    PROXY = sys.argv[5]
    parts = PROXY.split(":")
    if len(parts) == 4:
        ip, port, user, pw = parts
        OPENER = urllib.request.build_opener(
            urllib.request.ProxyHandler(
                {
                    "http": f"http://{user}:{pw}@{ip}:{port}",
                    "https": f"http://{user}:{pw}@{ip}:{port}",
                }
            )
        )
    else:
        ip, port = parts
        OPENER = urllib.request.build_opener(
            urllib.request.ProxyHandler(
                {
                    "http": f"http://{ip}:{port}",
                    "https": f"http://{ip}:{port}",
                }
            )
        )


def _open(req, timeout):
    return OPENER.open(req, timeout=timeout)

rnd = random.Random()


def rand_hex(n):
    return "".join(rnd.choice("0123456789abcdef") for _ in range(n))


DEVICE_ID = rand_hex(32)
APP_SESSION_ID = rand_hex(16)
PAGE_SESSION_ID = rand_hex(16)
TAB_SESSION_ID = rand_hex(16)


def log(msg):
    line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def http_post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with _open(req, 15) as r:
        return json.loads(r.read().decode())


def gql(body):
    return http_post(
        "https://gql.twitch.tv/gql",
        body,
        {
            "Client-ID": CLIENT_ID,
            "Content-Type": "application/json",
            "User-Agent": UA,
            "Origin": "https://www.twitch.tv",
            "Referer": "https://www.twitch.tv/",
        },
    )


def http_get(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Origin": "https://www.twitch.tv",
            "Referer": "https://www.twitch.tv/",
        },
    )
    with _open(req, 15) as r:
        return r.read()


def get_viewers(channel):
    r = gql(
        {
            "query": f'query {{ user(login: "{channel}") {{ stream {{ viewersCount }} }} }}',
        }
    )
    return r["data"]["user"]["stream"]["viewersCount"]


def get_channel_id(channel):
    r = gql({"query": f'query {{ user(login: "{channel}") {{ id }} }}'})
    return r["data"]["user"]["id"]


def get_pat(channel):
    r = gql(
        {
            "operationName": "PlaybackAccessToken_Template",
            "query": 'query PlaybackAccessToken_Template($login: String!, $isLive: Boolean!, $vodID: ID!, $isVod: Boolean!, $playerType: String!, $platform: String!) {  streamPlaybackAccessToken(channelName: $login, params: {platform: $platform, playerBackend: "mediaplayer", playerType: $playerType}) @include(if: $isLive) {    value    signature   authorization { isForbidden forbiddenReasonCode }   __typename  }  videoPlaybackAccessToken(id: $vodID, params: {platform: $platform, playerBackend: "mediaplayer", playerType: $playerType}) @include(if: $isVod) {    value    signature   __typename  }}',
            "variables": {
                "isLive": True,
                "login": channel,
                "isVod": False,
                "vodID": "",
                "playerType": "site",
                "platform": "web",
            },
        }
    )
    return r["data"]["streamPlaybackAccessToken"]


def parse_usher(master):
    info = {}
    renditions = []
    for ln in master.splitlines():
        if ln.startswith("#EXT-X-TWITCH-INFO:"):
            for kv in ln[len("#EXT-X-TWITCH-INFO:") :].split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    info[k] = v.strip('"')
        elif ln.startswith("#EXT-X-STREAM-INF:"):
            cur = {}
            for kv in ln[len("#EXT-X-STREAM-INF:") :].split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    cur[k.strip()] = v.strip('"')
            renditions.append({"attrs": cur, "url": None})
        elif ln and not ln.startswith("#") and renditions:
            renditions[-1]["url"] = ln
    return info, renditions


def send_spade(events):
    payload = base64.b64encode(gzip.compress(json.dumps(events).encode())).decode()
    r = gql(
        {
            "operationName": "SendEvents",
            "query": "mutation SendEvents($input: SendSpadeEventsInput!) {\n  sendSpadeEvents(input: $input) {\n    statusCode\n  }\n}",
            "variables": {"input": {"data": payload}},
        }
    )
    try:
        return r["data"]["sendSpadeEvents"]["statusCode"]
    except Exception:
        return json.dumps(r)[:200]


def minute_watched(channel, channel_id, broadcast_id, cluster, manifest_cluster, manifest_node, bitrate, fps):
    now = datetime.now(timezone.utc)
    props = {
        "app_session_id": APP_SESSION_ID,
        "app_version": "c6b6c202-3601-40c8-a0e4-fa2595fc7394",
        "batch_time": int(time.time()),
        "client_time": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "device_id": DEVICE_ID,
        "domain": "www.twitch.tv",
        "host": "www.twitch.tv",
        "location": "channel",
        "os_name": "mac",
        "os_version": "10.15",
        "platform": "web",
        "preferred_language": "en-US",
        "referrer_host": "",
        "referrer_url": "",
        "tab_session_id": TAB_SESSION_ID,
        "url": f"https://www.twitch.tv/{channel}",
        "benchmark_server_id": rand_hex(32),
        "bornuser": False,
        "browser": UA.replace("Mozilla/", ""),
        "browser_family": "firefox",
        "browser_version": "142.0",
        "collapse_right": False,
        "collapse_left": False,
        "localstorage_device_id": rand_hex(32),
        "page_session_id": PAGE_SESSION_ID,
        "referrer": "",
        "referrer_domain": "",
        "session_device_id": DEVICE_ID,
        "theme": "light",
        "viewport_height": 900,
        "viewport_width": 1440,
        "channel": channel,
        "channel_id": str(channel_id),
        "is_following": False,
        "is_live": True,
        "language": "en",
        "game": "",
        "category_id": "",
        "audio_codec": "mp4a.40.2",
        "backend": "mediaplayer",
        "battery_percent": 60,
        "broadcast_id": broadcast_id,
        "buffer_empty_count": 0,
        "buffered_position": 60.0,
        "build_dist_id": "npm",
        "catch_up_mode": "speedup",
        "client_app": "twilight",
        "cluster": cluster,
        "content_mode": "live",
        "core_version": "1.56.0-rc.1",
        "current_bitrate": bitrate,
        "current_fps": fps,
        "decoded_frames": 1560,
        "device_manufacturer": "",
        "device_model": "",
        "dropped_frames": 0,
        "estimated_bandwidth": 5417769,
        "gap_skip_count": 0,
        "gap_skip_duration": 0.0,
        "gl_renderer": "ANGLE (Microsoft, Microsoft Basic Render Driver (0x00008C) Direct3D11 vs_5_0 ps_5_0)",
        "gl_vendor": "Google Inc. (Microsoft)",
        "hidden": False,
        "initial_buffer_duration": 1000,
        "live": True,
        "low_latency": True,
        "manifest_cluster": manifest_cluster,
        "manifest_node": manifest_node,
        "video_height": 360,
        "video_width": 640,
        "muted": False,
        "player_height": 271,
        "player_width": 482,
        "playtime": 60.0,
        "render_delay": 0.0,
        "seconds_of_ad_and_content": 60.0,
        "seconds_of_ad_content": 0,
        "seconds_of_content": 60.0,
        "session_device_id": DEVICE_ID,
        "stream_id": broadcast_id,
        "supplier": "cloudfront_hls",
        "system_ram": "16",
        "visible": True,
        "vod_offset": None,
        "watch_session_id": rand_hex(16),
    }
    return [{"event": "minute-watched", "properties": props}]


def main():
    global LOG
    if len(sys.argv) > 3:
        LOG = sys.argv[3]
    noplayback = len(sys.argv) > 4 and sys.argv[4] == "noplayback"
    open(LOG, "w").close()
    log(f"device_id={DEVICE_ID} page_session={PAGE_SESSION_ID} noplayback={noplayback}")
    if PROXY:
        try:
            egress = (
                OPENER.open("https://api.ipify.org?format=json", timeout=15).read().decode()
            )
            log(f"proxy egress: {egress}")
        except Exception as e:
            log(f"proxy egress check failed: {e}")
    baseline = get_viewers(CHANNEL)
    log(f"baseline viewers: {baseline}")

    if noplayback:
        log("skipping playback (spade-only test)")
        channel_id = get_channel_id(CHANNEL)
        broadcast_id = ""
        cluster = ""
        manifest_cluster = ""
        manifest_node = ""
        bitrate = 230000
        fps = 30.0
    else:
        pat = get_pat(CHANNEL)
        value, sig = pat["value"], pat["signature"]
        tv = json.loads(value)
        channel_id = tv["channel_id"]
        log(f"pat ok: channel_id={channel_id} expires={tv['expires']} forbidden={pat['authorization']['isForbidden']}")

        q = urllib.parse.urlencode({"sig": sig, "token": value, "allow_source": "true", "fast_bread": "true"})
        master = http_get(f"https://usher.ttvnw.net/api/channel/hls/{CHANNEL}.m3u8?{q}").decode()
        info, renditions = parse_usher(master)
        broadcast_id = info.get("BROADCAST-ID", "")
        cluster = info.get("CLUSTER", "")
        manifest_cluster = info.get("MANIFEST-CLUSTER", "")
        manifest_node = info.get("MANIFEST-NODE", "")
        log(f"usher ok: renditions={len(renditions)} cluster={cluster} broadcast_id={broadcast_id}")

        rend = min(renditions, key=lambda r: int(r["attrs"].get("BANDWIDTH", "0")))
        log(f"rendition: {rend['attrs'].get('VIDEO')} bw={rend['attrs'].get('BANDWIDTH')}")
        bitrate = int(rend["attrs"].get("BANDWIDTH", "230000"))
        fps = float(rend["attrs"].get("FRAME-RATE", "30.0"))

    seen_segments = set()
    start = time.time()
    next_minute = start + 60
    next_check = start + 30
    while time.time() - start < DURATION_MIN * 60:
        if not noplayback:
            try:
                pl = http_get(rend["url"]).decode()
            except Exception as e:
                log(f"playlist err: {type(e).__name__} {e}")
                time.sleep(2)
                continue
            segs = [ln for ln in pl.splitlines() if ln and not ln.startswith("#")]
            new = [s for s in segs if s not in seen_segments]
            try:
                for s in new:
                    seen_segments.add(s)
                    http_get(s)
            except Exception as e:
                log(f"segment err: {type(e).__name__} {e}")
            if new:
                log(f"playlist ok: {len(segs)} total, fetched {len(new)}")
            else:
                log("playlist ok: no new segments")

        now = time.time()
        if now >= next_minute:
            next_minute += 60
            try:
                code = send_spade(
                    [
                        minute_watched(
                            CHANNEL,
                            channel_id,
                            broadcast_id,
                            cluster,
                            manifest_cluster,
                            manifest_node,
                            bitrate,
                            fps,
                        )
                    ]
                )
                log(f"minute-watched sent: statusCode={code}")
            except Exception as e:
                log(f"spade err: {type(e).__name__} {e}")
        if now >= next_check:
            next_check += 30
            try:
                v = get_viewers(CHANNEL)
                log(f"viewers: {v}")
            except Exception as e:
                log(f"viewers err: {e}")
        time.sleep(2)

    try:
        v = get_viewers(CHANNEL)
        log(f"final viewers: {v}")
    except Exception:
        pass
    log("done")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        raise
