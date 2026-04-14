"""
Google Flights 기반 항공권 가격 스크래퍼

fast-flights 라이브러리를 통해 Google Flights의 내부 API를 호출합니다.
Google 서버는 GitHub Actions 데이터센터 IP에서도 차단 없이 접근 가능합니다.
"""
import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

import pytz

from src.config import RouteConfig, ScraperConfig
from src.models import Flight

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")

AIRLINE_NAMES = {
    "KE": "대한항공", "OZ": "아시아나", "7C": "제주항공",
    "LJ": "진에어",   "BX": "에어부산", "TW": "티웨이항공",
    "RS": "에어서울", "ZE": "이스타항공",
}


class NaverFlightScraper:
    """Google Flights API 기반 스크래퍼"""

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
                               route.from_airport, route.to_airport,
                               date_str, attempt, exc)
                if attempt < self.config.retry_count:
                    time.sleep(2 ** attempt)

        return []

    def _fetch(self, route: RouteConfig, date: datetime) -> List[Flight]:
        from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter

        date_str = date.strftime("%Y-%m-%d")

        f = create_filter(
            flight_data=[FlightData(
                date=date_str,
                from_airport=route.from_airport,
                to_airport=route.to_airport,
            )],
            trip="one-way",
            seat="economy",
            passengers=Passengers(adults=1),
        )

        result = get_flights_from_filter(f, currency="KRW")
        flights = []

        for flight in result.flights:
            try:
                # 가격 파싱 (예: "₩82,700" 또는 "82700")
                price = self._parse_price(flight.price)
                if not price:
                    continue

                # 시간 파싱
                dep_t = self._parse_time(flight.departure)
                arr_t = self._parse_time(flight.arrival)
                if not dep_t or not arr_t:
                    continue

                dep_dt = KST.localize(datetime.combine(date.date(), dep_t))
                arr_dt = KST.localize(datetime.combine(date.date(), arr_t))
                if arr_dt < dep_dt:
                    arr_dt += timedelta(days=1)

                # 항공사 파싱
                airline_name = getattr(flight, "airline", "") or getattr(flight, "name", "") or "?"
                airline_code = self._name_to_code(airline_name)
                flight_num = getattr(flight, "flight_number", "") or airline_code

                flights.append(Flight(
                    airline=airline_code,
                    airline_name=AIRLINE_NAMES.get(airline_code, airline_name),
                    flight_number=str(flight_num),
                    from_airport=route.from_airport,
                    to_airport=route.to_airport,
                    departure_time=dep_dt,
                    arrival_time=arr_dt,
                    price=price,
                ))
            except Exception as e:
                logger.debug("항공편 파싱 실패: %s / 원본: %s", e, flight)

        logger.info("[%s→%s %s] Google Flights에서 %d건 조회",
                    route.from_airport, route.to_airport,
                    date.strftime("%Y%m%d"), len(flights))
        return flights

    @staticmethod
    def _parse_price(raw) -> Optional[int]:
        import re
        if raw is None:
            return None
        s = str(raw).replace(",", "").replace("₩", "").replace("￦", "").strip()
        m = re.search(r"\d+", s)
        if m:
            val = int(m.group())
            if 5_000 <= val <= 3_000_000:
                return val
        return None

    @staticmethod
    def _parse_time(raw) -> Optional[datetime.time]:
        import re
        if not raw:
            return None
        s = str(raw).strip()
        # "7:05 PM on Sat, May 16" 형식 (Google Flights 응답)
        m = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", s, re.IGNORECASE)
        if m:
            h, mi, period = int(m.group(1)), int(m.group(2)), m.group(3).upper()
            if period == "PM" and h != 12:
                h += 12
            elif period == "AM" and h == 12:
                h = 0
            from datetime import time
            return time(h % 24, mi)
        # "오전 6:30", "오후 2:15" 형식
        m = re.search(r"(오전|오후)\s*(\d{1,2}):(\d{2})", s)
        if m:
            period, h, mi = m.group(1), int(m.group(2)), int(m.group(3))
            if period == "오후" and h != 12:
                h += 12
            elif period == "오전" and h == 12:
                h = 0
            from datetime import time
            return time(h % 24, mi)
        # "06:30", "14:15" 24시간 형식
        m = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mi <= 59:
                from datetime import time
                return time(h, mi)
        return None

    @staticmethod
    def _name_to_code(name: str) -> str:
        mapping = {
            "제주항공": "7C", "Jeju Air": "7C", "jeju": "7C",
            "진에어": "LJ", "Jin Air": "LJ",
            "대한항공": "KE", "Korean Air": "KE",
            "아시아나": "OZ", "Asiana": "OZ",
            "티웨이": "TW", "T'way": "TW", "Tway": "TW",
            "에어부산": "BX", "Air Busan": "BX",
            "에어서울": "RS", "Air Seoul": "RS",
            "이스타": "ZE", "Eastar": "ZE",
        }
        name_lower = name.lower()
        for k, v in mapping.items():
            if k.lower() in name_lower:
                return v
        return name[:2].upper() if name else "??"
