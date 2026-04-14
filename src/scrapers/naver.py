"""
항공사 직접 API 스크래퍼

GitHub Actions 데이터센터 IP에서 네이버가 차단되는 문제를 우회하기 위해
각 항공사 예약 사이트의 API를 직접 호출합니다.
Playwright/브라우저 없이 requests 라이브러리만 사용합니다.

지원 항공사:
  - 제주항공 (7C)
  - 진에어 (LJ)
  - 티웨이항공 (TW)
  - 에어서울 (RS)
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

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


# ──────────────────────────────────────────────────────────────
# 제주항공 (7C)
# ──────────────────────────────────────────────────────────────
class JejuAirScraper:
    NAME = "제주항공"
    CODE = "7C"

    def search(self, dep: str, arr: str, date: datetime) -> List[Flight]:
        date_str = date.strftime("%Y%m%d")
        url = "https://api.jejuair.net/v1/fares/schedule"
        params = {
            "tripType": "OW",
            "depAirportCode": dep,
            "arrAirportCode": arr,
            "depDt": date_str,
            "adtCnt": 1,
            "chdCnt": 0,
            "infCnt": 0,
            "currency": "KRW",
        }
        headers = {**COMMON_HEADERS, "Referer": "https://www.jejuair.net/"}
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=20)
            resp.raise_for_status()
            return self._parse(resp.json(), dep, arr, date)
        except Exception as e:
            logger.debug("[%s] API 실패: %s", self.NAME, e)

        # 폴백: 구 엔드포인트
        try:
            url2 = "https://www.jejuair.net/jejuair/com/schedule/selectSchedule.do"
            data = {
                "tripType": "OW", "depAirportCode": dep,
                "arrAirportCode": arr, "depDt": date_str,
                "adtCnt": "1", "chdCnt": "0", "infCnt": "0",
            }
            headers2 = {**COMMON_HEADERS,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": "https://www.jejuair.net/"}
            resp2 = requests.post(url2, data=data, headers=headers2, timeout=20)
            resp2.raise_for_status()
            return self._parse(resp2.json(), dep, arr, date)
        except Exception as e:
            logger.debug("[%s] 폴백 API 실패: %s", self.NAME, e)
            return []

    def _parse(self, body, dep, arr, date) -> List[Flight]:
        flights = []
        items = self._find_list(body)
        for item in items:
            f = self._to_flight(item, dep, arr, date)
            if f:
                flights.append(f)
        return flights

    @staticmethod
    def _find_list(obj, depth=0) -> list:
        if depth > 8:
            return []
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            keys = set(obj[0].keys())
            if keys & {"depTime", "arrTime", "fare", "price", "amount",
                       "departureTime", "arrivalTime", "salePrice"}:
                return obj
        if isinstance(obj, dict):
            for v in obj.values():
                r = JejuAirScraper._find_list(v, depth + 1)
                if r:
                    return r
        return []

    def _to_flight(self, d: dict, dep, arr, date) -> Optional[Flight]:
        try:
            dep_s = (d.get("depTime") or d.get("departureTime") or
                     d.get("depDt") or d.get("std") or "")
            arr_s = (d.get("arrTime") or d.get("arrivalTime") or
                     d.get("arrDt") or d.get("sta") or "")
            price = (d.get("fare") or d.get("price") or d.get("amount") or
                     d.get("salePrice") or d.get("adultFare") or 0)
            if isinstance(price, str):
                price = int(re.sub(r"[^\d]", "", price) or 0)
            price = int(price)
            if not dep_s or not arr_s or price < 1000:
                return None

            dep_t = _parse_time(dep_s)
            arr_t = _parse_time(arr_s)
            if not dep_t or not arr_t:
                return None

            dep_dt = KST.localize(datetime.combine(date.date(), dep_t))
            arr_dt = KST.localize(datetime.combine(date.date(), arr_t))
            if arr_dt < dep_dt:
                arr_dt += timedelta(days=1)

            fn = d.get("flightNo") or d.get("flightNumber") or self.CODE
            return Flight(
                airline=self.CODE, airline_name=self.NAME,
                flight_number=str(fn),
                from_airport=dep, to_airport=arr,
                departure_time=dep_dt, arrival_time=arr_dt,
                price=price,
            )
        except Exception:
            return None


# ──────────────────────────────────────────────────────────────
# 진에어 (LJ)
# ──────────────────────────────────────────────────────────────
class JinAirScraper:
    NAME = "진에어"
    CODE = "LJ"

    def search(self, dep: str, arr: str, date: datetime) -> List[Flight]:
        date_str = date.strftime("%Y%m%d")
        url = "https://www.jinair.com/booking/availability"
        params = {
            "depAirportCode": dep, "arrAirportCode": arr,
            "depDate": date_str, "paxCount": 1,
            "tripType": "OW", "cabinClass": "Y",
        }
        try:
            resp = requests.get(url, params=params,
                                headers={**COMMON_HEADERS,
                                         "Referer": "https://www.jinair.com/"},
                                timeout=20)
            resp.raise_for_status()
            return self._parse(resp.json(), dep, arr, date)
        except Exception as e:
            logger.debug("[%s] API 실패: %s", self.NAME, e)
            return []

    def _parse(self, body, dep, arr, date) -> List[Flight]:
        flights = []
        items = JejuAirScraper._find_list(body)
        for item in items:
            f = self._to_flight(item, dep, arr, date)
            if f:
                flights.append(f)
        return flights

    def _to_flight(self, d: dict, dep, arr, date) -> Optional[Flight]:
        try:
            dep_s = (d.get("depTime") or d.get("departureTime") or
                     d.get("std") or "")
            arr_s = (d.get("arrTime") or d.get("arrivalTime") or
                     d.get("sta") or "")
            price = (d.get("fare") or d.get("price") or d.get("lowestFare") or
                     d.get("normalFare") or 0)
            if isinstance(price, str):
                price = int(re.sub(r"[^\d]", "", price) or 0)
            price = int(price)
            if not dep_s or not arr_s or price < 1000:
                return None
            dep_t = _parse_time(dep_s)
            arr_t = _parse_time(arr_s)
            if not dep_t or not arr_t:
                return None
            dep_dt = KST.localize(datetime.combine(date.date(), dep_t))
            arr_dt = KST.localize(datetime.combine(date.date(), arr_t))
            if arr_dt < dep_dt:
                arr_dt += timedelta(days=1)
            fn = d.get("flightNo") or d.get("flightNumber") or self.CODE
            return Flight(
                airline=self.CODE, airline_name=self.NAME,
                flight_number=str(fn),
                from_airport=dep, to_airport=arr,
                departure_time=dep_dt, arrival_time=arr_dt,
                price=price,
            )
        except Exception:
            return None


# ──────────────────────────────────────────────────────────────
# 티웨이항공 (TW)
# ──────────────────────────────────────────────────────────────
class TWayAirScraper:
    NAME = "티웨이항공"
    CODE = "TW"

    def search(self, dep: str, arr: str, date: datetime) -> List[Flight]:
        date_str = date.strftime("%Y%m%d")
        url = "https://www.twayair.com/app/popup/fareCalendar"
        data = {
            "depAirportCode": dep, "arrAirportCode": arr,
            "depDt": date_str, "tripType": "OW",
            "adultCnt": "1", "childCnt": "0", "infantCnt": "0",
        }
        try:
            resp = requests.post(
                url, data=data,
                headers={**COMMON_HEADERS,
                         "Content-Type": "application/x-www-form-urlencoded",
                         "Referer": "https://www.twayair.com/"},
                timeout=20,
            )
            resp.raise_for_status()
            return self._parse(resp.json(), dep, arr, date)
        except Exception as e:
            logger.debug("[%s] API 실패: %s", self.NAME, e)
            return []

    def _parse(self, body, dep, arr, date) -> List[Flight]:
        flights = []
        items = JejuAirScraper._find_list(body)
        for item in items:
            f = self._to_flight(item, dep, arr, date)
            if f:
                flights.append(f)
        return flights

    def _to_flight(self, d: dict, dep, arr, date) -> Optional[Flight]:
        try:
            dep_s = d.get("depTime") or d.get("departureTime") or ""
            arr_s = d.get("arrTime") or d.get("arrivalTime") or ""
            price = d.get("fare") or d.get("price") or d.get("amount") or 0
            if isinstance(price, str):
                price = int(re.sub(r"[^\d]", "", price) or 0)
            price = int(price)
            if not dep_s or not arr_s or price < 1000:
                return None
            dep_t = _parse_time(dep_s)
            arr_t = _parse_time(arr_s)
            if not dep_t or not arr_t:
                return None
            dep_dt = KST.localize(datetime.combine(date.date(), dep_t))
            arr_dt = KST.localize(datetime.combine(date.date(), arr_t))
            if arr_dt < dep_dt:
                arr_dt += timedelta(days=1)
            fn = d.get("flightNo") or d.get("flightNumber") or self.CODE
            return Flight(
                airline=self.CODE, airline_name=self.NAME,
                flight_number=str(fn),
                from_airport=dep, to_airport=arr,
                departure_time=dep_dt, arrival_time=arr_dt,
                price=price,
            )
        except Exception:
            return None


# ──────────────────────────────────────────────────────────────
# 통합 스크래퍼
# ──────────────────────────────────────────────────────────────
class NaverFlightScraper:
    """
    항공사 직접 API 통합 스크래퍼
    (Naver IP 차단 우회 → 각 항공사 직접 호출)
    """

    def __init__(self, config: ScraperConfig):
        self.config = config
        self._airline_scrapers = [
            JejuAirScraper(),
            JinAirScraper(),
            TWayAirScraper(),
        ]

    def fetch_flights(self, route: RouteConfig, date: datetime) -> List[Flight]:
        date_str = date.strftime("%Y%m%d")
        all_flights: List[Flight] = []

        for scraper in self._airline_scrapers:
            for attempt in range(1, self.config.retry_count + 1):
                try:
                    flights = scraper.search(route.from_airport, route.to_airport, date)
                    if flights:
                        logger.info("[%s %s→%s] %s에서 %d건",
                                    date_str, route.from_airport, route.to_airport,
                                    scraper.NAME, len(flights))
                    all_flights.extend(flights)
                    break
                except Exception as exc:
                    logger.debug("[%s] 시도 %d 실패: %s", scraper.NAME, attempt, exc)
                    if attempt < self.config.retry_count:
                        time.sleep(2 ** attempt)

        # 시간 범위 필터 + 가격순 정렬
        filtered = [
            f for f in all_flights
            if route.time_range.contains(f.departure_time.strftime("%H:%M"))
        ]
        result = sorted(filtered, key=lambda f: f.price)

        logger.info("[%s %s→%s] 시간범위(%s~%s) 내 항공편 %d건",
                    date_str, route.from_airport, route.to_airport,
                    route.time_range.start, route.time_range.end, len(result))
        return result


# ──────────────────────────────────────────────────────────────
# 공통 유틸
# ──────────────────────────────────────────────────────────────
def _parse_time(s: str) -> Optional[datetime.time]:
    s = str(s).strip()
    # ISO: 2026-04-19T06:30:00
    m = re.search(r"T(\d{2}):(\d{2})", s)
    if m:
        from datetime import time
        return time(int(m.group(1)), int(m.group(2)))
    # HH:MM
    m = re.search(r"(\d{2}):(\d{2})", s)
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
