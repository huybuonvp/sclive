#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, time, argparse
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests


# =========================================================
# DATA CLASS
# =========================================================
@dataclass
class StreamInfo:
    room_id: str
    streamer: str
    host_name: str
    guest_name: str
    match_name: str
    category: str
    kickoff: Optional[str] = None
    host_logo: Optional[str] = None
    guest_logo: Optional[str] = None
    flv: Optional[str] = None
    hd_flv: Optional[str] = None
    m3u8: Optional[str] = None
    hd_m3u8: Optional[str] = None


# =========================================================
# SCRAPER
# =========================================================
class SocoliveScraper:
    BASE_URL = "https://json.vnres.co"
    MATCHES_ENDPOINT = "/match/matches_{date}.json"
    ROOM_ENDPOINT = "/room/{room_id}/detail.json"

    def __init__(self):
        proxy_url = "http://ZalMQa:BRQrEd@14.250.212.38:36428"
        self.session = requests.Session(impersonate="chrome136")
        self.session.proxies = {"http": proxy_url, "https": proxy_url}
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/136.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Referer": "https://tructiepbongda.com/",
            "Origin": "https://tructiepbongda.com",
        })
        self.room_cache = {}

    @staticmethod
    def clean_url(url: Optional[str]) -> Optional[str]:
        return None if not url else url.replace("\\/", "/").replace("\\u003d", "=").replace("\\u0026", "&").strip()

    def _fetch_jsonp(self, url: str) -> dict:
        callback = f"jsonp_{int(time.time()*1000)}"
        url = f"{url}?callback={callback}"
        for _ in range(3):
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code != 200:
                    print(f"[HTTP {resp.status_code}] {url}")
                    time.sleep(2); continue
                text = resp.text.strip()
                start, end = text.find("("), text.rfind(")")
                if start != -1 and end != -1:
                    text = text[start+1:end]
                return json.loads(text)
            except Exception as e:
                print(f"[ERROR] {e}"); time.sleep(2)
        raise Exception(f"Failed: {url}")

    def get_matches(self, date: Optional[datetime] = None) -> List[dict]:
        date_str = (date or datetime.now()).strftime("%Y%m%d")
        return self._fetch_jsonp(f"{self.BASE_URL}{self.MATCHES_ENDPOINT.format(date=date_str)}").get("data", [])

    def get_room_detail(self, room_id: str) -> dict:
        if room_id not in self.room_cache:
            self.room_cache[room_id] = self._fetch_jsonp(f"{self.BASE_URL}{self.ROOM_ENDPOINT.format(room_id=room_id)}").get("data", {})
        return self.room_cache[room_id]

    def get_all_streams(self, date: Optional[datetime] = None) -> List[StreamInfo]:
        matches, jobs, seen_rooms = self.get_matches(date), [], set()
        print(f"[INFO] MATCHES: {len(matches)}")

        for match in matches:
            host, guest = match.get("hostName", "Unknown Home"), match.get("guestName", "Unknown Away")
            match_name = f"{host} vs {guest}"
            category = match.get("subCateName") or match.get("categoryName") or "Unknown"
            kickoff = "N/A"
            ts = match.get("matchTime") or match.get("startTime")
            if ts:
                try: kickoff = datetime.fromtimestamp(int(ts)/1000).strftime("%H:%M")
                except: pass

            for anchor in match.get("anchors", []):
                room_id = anchor.get("anchor", {}).get("roomNum") or str(anchor.get("uid", ""))
                if not room_id or room_id in seen_rooms: continue
                seen_rooms.add(room_id)
                jobs.append({
                    "room_id": room_id, "streamer": anchor.get("nickName", "Unknown"),
                    "host_name": host, "guest_name": guest, "match_name": match_name,
                    "category": category, "kickoff": kickoff,
                    "host_logo": match.get("hostIcon", ""), "guest_logo": match.get("guestIcon", "")
                })

        print(f"[INFO] ROOMS: {len(jobs)}")
        streams = []
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_map = {executor.submit(self.get_room_detail, job["room_id"]): job for job in jobs}
            for future in as_completed(future_map):
                job = future_map[future]
                try:
                    detail = future.result()
                    stream_data = detail.get("stream", {})
                    stream = StreamInfo(
                        room_id=job["room_id"], streamer=job["streamer"],
                        host_name=job["host_name"], guest_name=job["guest_name"],
                        match_name=job["match_name"], category=job["category"],
                        kickoff=job["kickoff"], host_logo=job["host_logo"], guest_logo=job["guest_logo"],
                        flv=self.clean_url(stream_data.get("flv")),
                        hd_flv=self.clean_url(stream_data.get("hdFlv")),
                        m3u8=self.clean_url(stream_data.get("m3u8")),
                        hd_m3u8=self.clean_url(stream_data.get("hdM3u8")),
                    )
                    if stream.hd_m3u8 or stream.m3u8 or stream.hd_flv or stream.flv:
                        streams.append(stream)
                        print(f"[+] {stream.room_id} | {stream.match_name}")
                except Exception as e:
                    print(f"[-] {job['room_id']} -> {e}")
        return streams


# =========================================================
# MAIN
# =========================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--date", type=str)
    parser.add_argument("-f", "--format", default="m3u8")
    parser.add_argument("-o", "--output", default="streams.json")
    args = parser.parse_args()

    scraper = SocoliveScraper()
    date = datetime.strptime(args.date, "%Y%m%d") if args.date else None
    streams = scraper.get_all_streams(date)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in streams], f, indent=2, ensure_ascii=False)
    print("[+] JSON saved")

    with open("streams.m3u8", "w", encoding="utf-8") as mf:
        mf.write("#EXTM3U\n\n")
        for s in streams:
            best_stream = s.hd_m3u8 or s.m3u8 or s.hd_flv or s.flv
            if not best_stream: continue
            title = f"[{s.kickoff}] {s.match_name} | {s.streamer}"
            mf.write("#KODIPROP:http-user-agent=Mozilla/5.0\n")
            mf.write("#EXTVLCOPT:http-user-agent=Mozilla/5.0\n")
            mf.write(f'#EXTINF:-1 tvg-id="{s.room_id}" tvg-name="{title}" '
                     f'tvg-logo="{s.host_logo}" group-title="{s.category}",{title}\n')
            mf.write(best_stream + "\n\n")
    print("[+] M3U saved")


if __name__ == "__main__":
    main()
