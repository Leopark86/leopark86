"""
네이버 항공 내부 JSON API 스크래퍼

Playwright(브라우저) 없이 requests만으로 네이버 항공 내부 API를 호출합니다.
네이버 항공 SPA가 서버에서 받아오는 JSON 엔드포인트를 직접 호출하는 방식입니다.
"""
import logging
import re
import time
from datetime import datetime, timedelta
from typing import List, Optional

import pytz
import requests

from src.config import RouteConfig, ScraperConfig
from src.models import Flight

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")

AIRLINE_NAMES = {
    "KE": "대한항공", "OZ": "아시아나", "7C": "제주항공",
    "LJ": "진에어",   "BX": "에어부산", "TW": "티웨이항공",
    "RS": "에어서울", "ZE": "이스타항공",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://flight.naver.com/",
    "Origin": "https://flight.naver.com",
}


class NaverFlightScraper:

    def __init__(self, config: ScraperConfig):
        self.config = config

    def fetch_flights(self, route: RouteConfig, date: datetime) -> List[Flight]:
        date_str = date.strftime("%Y%m%d")
        for attempt in range(1, self.config.retry_count + 1):
            try:
                flights = self._fetch(route, date)
                filtered = [
                    f for f in flights
                    if route.time_range.contains(f.departure_time.strftime("%H:%M"))
                ]
                result = sorted(filtered, key=lambda f: f.price)
                logger.info("[%s %s→%s] 시간범위(%s~%s) 내 항공편 %d건",
                            date_str, route.from_airport, route.to_airport,
                            route.time_range.start, route.time_range.end, len(result))
                return result
            except Exception as exc:
                logger.warning("[%s→%s %s] 시도 %d 실패: %s",
                               route.from_airport, route.to_airport, date_str, attempt, exc)
                if attempt < self.config.retry_count:
                    time.sleep(2 ** attempt)
        return []

    # ── 메인 로직 ──────────────────────────────────────────────────────

    def _fetch(self, route: RouteConfig, date: datetime) -> List[Flight]:
        session = requests.Session()
        session.headers.update(HEADERS)

        dep  = route.from_airport
        arr  = route.to_airport
        date_str = date.strftime("%Y%m%d")

        # ── 시도 1: 네이버 항공 내부 REST API (v1) ──────────────────────
        for endpoint in [
            f"https://flight.naver.com/api/v1/fares"
            f"?departureAirport={dep}&arrivalAirport={arr}&departureDate={date_str}"
            f"&adults=1&children=0&infants=0&fareType=Y",

            f"https://flight.naver.com/api/v1/domestic/oneway"
            f"?from={dep}&to={arr}&date={date_str}&adults=1",

            f"https://flight.naver.com/api/v1/schedules"
            f"?dep={dep}&arr={arr}&date={date_str}&cnt=1",
        ]:
            try:
                resp = session.get(endpoint, timeout=15)
                if resp.status_code == 200 and "json" in resp.headers.get("content-type", ""):
                    flights = self._parse_json(resp.json(), dep, arr, date)
                    if flights:
                        logger.info("네이버 API v1 성공: %d건", len(flights))
                        return flights
            except Exception as e:
                logger.debug("API 시도 실패(%s): %s", endpoint[:60], e)

        # ── 시도 2: 페이지 HTML에서 __INITIAL_STATE__ 추출 ──────────────
        try:
            page_url = (
                f"https://flight.naver.com/flights/domestic/"
                f"{dep}-{arr}-{date_str}?adult=1&fareType=Y"
            )
            # 먼저 메인 페이지로 세션/쿠키 획득
            session.get("https://flight.naver.com/", timeout=10)
            resp = session.get(page_url, timeout=20)

            # HTML 내 JSON 데이터 추출 시도
            flights = self._extract_from_html(resp.text, dep, arr, date)
            if flights:
                logger.info("HTML 내 JSON 추출 성공: %d건", len(flights))
                return flights
        except Exception as e:
            logger.debug("HTML 파싱 실패: %s", e)

        # ── 시도 3: 네이버 항공 API v2 (모바일 엔드포인트) ──────────────
        mobile_headers = {**HEADERS,
                          "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"}
        for endpoint in [
            f"https://m.flight.naver.com/api/flights"
            f"?dep={dep}&arr={arr}&date={date_str}&adults=1",

            f"https://flight.naver.com/api/v2/domestic"
            f"?departureAirport={dep}&arrivalAirport={arr}&date={date_str}&adults=1",
        ]:
            try:
                resp = requests.get(endpoint, headers=mobile_headers, timeout=15)
                if resp.status_code == 200 and "json" in resp.headers.get("content-type", ""):
                    flights = self._parse_json(resp.json(), dep, arr, date)
                    if flights:
                        logger.info("모바일 API 성공: %d건", len(flights))
                        return flights
            except Exception as e:
                logger.debug("모바일 API 실패: %s", e)

        logger.warning("[%s→%s %s] 모든 API 시도 실패 — 응답 내용을 확인하세요.",
                       dep, arr, date_str)
        return []

    # ── 파서 ───────────────────────────────────────────────────────────

    def _extract_from_html(self, html: str, dep, arr, date) -> List[Flight]:
        """HTML 내 JSON 데이터 블록 탐색"""
        patterns = [
            r"window\.__INITIAL_STATE__\s*=\s*({.+?});\s*</script>",
            r"window\.__data__\s*=\s*({.+?});\s*</script>",
            r"window\.__APP_STATE__\s*=\s*({.+?});\s*</script>",
            r'<script[^>]+type="application/json"[^>]*>({.+?})</script>',
        ]
        import json
        for pat in patterns:
            for m in re.finditer(pat, html, re.DOTALL):
                try:
                    data = json.loads(m.group(1))
                    flights = self._parse_json(data, dep, arr, date)
                    if flights:
                        return flights
                except Exception:
                    continue
        return []

    def _parse_json(self, obj, dep, arr, date, depth=0) -> List[Flight]:
        """JSON 객체를 재귀 탐색하여 항공편 리스트 추출"""
        if depth > 12:
            return []
        results = []

        if isinstance(obj, list):
            # 항공편 배열로 보이는 경우
            if obj and isinstance(obj[0], dict):
                keys = set(obj[0].keys())
                time_keys = {"depTime","arrTime","departureTime","arrivalTime",
                             "std","sta","depDt","arrDt"}
                if keys & time_keys:
                    for item in obj:
                        f = self._dict_to_flight(item, dep, arr, date)
                        if f:
                            results.append(f)
                    if results:
                        return results
            for item in obj:
                results.extend(self._parse_json(item, dep, arr, date, depth + 1))

        elif isinstance(obj, dict):
            f = self._dict_to_flight(obj, dep, arr, date)
            if f:
                return [f]
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    sub = self._parse_json(v, dep, arr, date, depth + 1)
                    results.extend(sub)

        return results

    def _dict_to_flight(self, d: dict, dep, arr, date) -> Optional[Flight]:
        """딕셔너리에서 Flight 객체 생성 시도"""
        try:
            # 출발시간
            dep_s = None
            for k in ("depTime","departureTime","std","depDt","etd","departAt",
                      "dep_time","departure_time"):
                if d.get(k):
                    dep_s = str(d[k]); break

            # 도착시간
            arr_s = None
            for k in ("arrTime","arrivalTime","sta","arrDt","eta","arriveAt",
                      "arr_time","arrival_time"):
                if d.get(k):
                    arr_s = str(d[k]); break

            # 가격
            price = None
            for k in ("fare","price","amount","lowestFare","salePrice",
                      "adultFare","totalFare","normalFare","chargeAmt","fee"):
                v = d.get(k)
                if v is not None:
                    cleaned = int(re.sub(r"[^\d]", "", str(v)) or 0)
                    if 5_000 <= cleaned <= 3_000_000:
                        price = cleaned; break

            if not dep_s or not arr_s or not price:
                return None

            dep_t = _parse_time(dep_s)
            arr_t = _parse_time(arr_s)
            if not dep_t or not arr_t:
                return None

            dep_dt = KST.localize(datetime.combine(date.date(), dep_t))
            arr_dt = KST.localize(datetime.combine(date.date(), arr_t))
            if arr_dt < dep_dt:
                arr_dt += timedelta(days=1)

            # 항공사
            airline_code = "??"
            for k in ("airlineCode","carrier","carrierCode","airline","airlineId"):
                if d.get(k):
                    airline_code = str(d[k]).strip().upper()[:2]; break

            fn = str(d.get("flightNo") or d.get("flightNumber") or d.get("flight") or airline_code)

            return Flight(
                airline=airline_code,
                airline_name=AIRLINE_NAMES.get(airline_code, airline_code),
                flight_number=fn,
                from_airport=dep, to_airport=arr,
                departure_time=dep_dt, arrival_time=arr_dt,
                price=price,
            )
        except Exception:
            return None


def _parse_time(s: str) -> Optional[datetime.time]:
    s = str(s).strip()
    # ISO: 2026-05-16T12:25:00
    m = re.search(r"T(\d{2}):(\d{2})", s)
    if m:
        from datetime import time
        return time(int(m.group(1)), int(m.group(2)))
    # HH:MM
    m = re.search(r"\b(\d{2}):(\d{2})\b", s)
    if m:
        from datetime import time
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return time(h, mi)
    # HHMM
    m = re.fullmatch(r"(\d{2})(\d{2})", s)
    if m:
        from datetime import time
        return time(int(m.group(1)), int(m.group(2)))
    return None
