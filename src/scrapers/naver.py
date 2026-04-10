"""
네이버 항공 (flight.naver.com) 가격 스크래퍼

네이버 항공은 JavaScript 렌더링 사이트이므로 Playwright를 사용하여
실제 브라우저처럼 페이지를 로딩한 뒤 가격 정보를 추출합니다.
"""
import logging
import re
import time
from datetime import datetime
from typing import List, Optional

import pytz

from src.config import RouteConfig, ScraperConfig
from src.models import Flight

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")

AIRLINE_NAMES = {
    "KE": "대한항공",
    "OZ": "아시아나",
    "7C": "제주항공",
    "LJ": "진에어",
    "BX": "에어부산",
    "TW": "티웨이항공",
    "RS": "에어서울",
    "ZE": "이스타항공",
    "4V": "플라이강원",
}


class NaverFlightScraper:
    """
    네이버 항공 스크래퍼

    Playwright로 flight.naver.com을 직접 방문하여 항공편 정보를 수집합니다.
    Anti-bot 우회를 위해 실제 Chromium 브라우저를 사용합니다.
    """

    BASE_URL = "https://flight.naver.com"
    SEARCH_URL = "{base}/flights/domestic/{from_ap}-{to_ap}-{date}?adult=1&fareType=Y"

    def __init__(self, config: ScraperConfig):
        self.config = config

    def fetch_flights(self, route: RouteConfig, date: datetime) -> List[Flight]:
        """
        특정 날짜의 항공편 목록 및 가격 조회

        Args:
            route: 노선 설정 (from/to/time_range)
            date:  검색할 날짜

        Returns:
            조건에 맞는 Flight 리스트 (시간 범위 필터 적용 후)
        """
        date_str = date.strftime("%Y%m%d")
        url = self.SEARCH_URL.format(
            base=self.BASE_URL,
            from_ap=route.from_airport,
            to_ap=route.to_airport,
            date=date_str,
        )

        for attempt in range(1, self.config.retry_count + 1):
            try:
                logger.info(
                    "[%s→%s %s] 스크래핑 시도 %d/%d",
                    route.from_airport, route.to_airport, date_str,
                    attempt, self.config.retry_count,
                )
                flights = self._scrape(url, route, date)
                logger.info("항공편 %d건 조회됨", len(flights))
                return flights
            except Exception as exc:
                logger.warning("시도 %d 실패: %s", attempt, exc)
                if attempt < self.config.retry_count:
                    time.sleep(2 ** attempt)  # 지수 백오프

        logger.error("모든 재시도 실패: %s→%s %s", route.from_airport, route.to_airport, date_str)
        return []

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _scrape(self, url: str, route: RouteConfig, date: datetime) -> List[Flight]:
        """Playwright로 실제 브라우저를 실행하여 페이지를 파싱합니다."""
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

        flights: List[Flight] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.config.headless,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="ko-KR",
            )
            # webdriver 속성 숨기기
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()

            try:
                logger.debug("페이지 로딩: %s", url)
                page.goto(url, timeout=self.config.timeout_seconds * 1000, wait_until="domcontentloaded")

                # 항공편 카드가 나타날 때까지 대기
                self._wait_for_flights(page)

                # 항공편 데이터 파싱
                flights = self._parse_flights(page, route, date)

            except PlaywrightTimeout:
                logger.error("페이지 로딩 타임아웃: %s", url)
                raise
            except Exception as exc:
                logger.error("파싱 오류: %s", exc, exc_info=True)
                raise
            finally:
                browser.close()

        return flights

    def _wait_for_flights(self, page) -> None:
        """항공편 목록이 나타날 때까지 대기 (최대 30초)"""
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        selectors = [
            # 네이버 항공 SPA 컴포넌트 셀렉터들 (클래스명이 변경될 수 있어 복수 지원)
            "[class*='FlightItem']",
            "[class*='flight_item']",
            "[class*='flights_item']",
            ".flight-item",
            "[data-testid='flight-item']",
        ]

        for sel in selectors:
            try:
                page.wait_for_selector(sel, timeout=30_000)
                logger.debug("항공편 셀렉터 확인: %s", sel)
                return
            except PlaywrightTimeout:
                continue

        # 셀렉터를 못 찾은 경우 — 페이지 콘텐츠 덤프 후 예외
        content_snippet = page.content()[:2000]
        logger.debug("페이지 스니펫:\n%s", content_snippet)
        raise RuntimeError("항공편 목록을 찾을 수 없습니다. 셀렉터 업데이트가 필요할 수 있습니다.")

    def _parse_flights(self, page, route: RouteConfig, date: datetime) -> List[Flight]:
        """페이지에서 항공편 정보를 추출합니다."""
        flights: List[Flight] = []

        # 네이버 항공은 React 기반 SPA — 렌더링된 DOM에서 데이터 추출
        # 여러 셀렉터 패턴 시도
        item_selectors = [
            "[class*='FlightItem']",
            "[class*='flight_item']",
            "[class*='flights_item']",
            ".flight-item",
        ]

        items = []
        for sel in item_selectors:
            items = page.query_selector_all(sel)
            if items:
                logger.debug("항공편 아이템 %d개 발견 (셀렉터: %s)", len(items), sel)
                break

        if not items:
            # JavaScript 상태에서 직접 데이터 추출 시도
            return self._parse_from_js_state(page, route, date)

        for item in items:
            flight = self._parse_item(item, route, date)
            if flight:
                flights.append(flight)

        # 시간 범위 필터 적용
        flights = self._filter_by_time(flights, route)
        return sorted(flights, key=lambda f: f.price)

    def _parse_item(self, item, route: RouteConfig, date: datetime) -> Optional[Flight]:
        """단일 항공편 DOM 요소에서 Flight 객체 추출"""
        try:
            text = item.inner_text()
            lines = [l.strip() for l in text.splitlines() if l.strip()]

            dep_time, arr_time = self._extract_times(item, lines)
            price = self._extract_price(item, lines)
            airline_code, airline_name = self._extract_airline(item, lines)
            flight_number = self._extract_flight_number(item, lines, airline_code)

            if not all([dep_time, arr_time, price, airline_code]):
                return None

            dep_dt = KST.localize(datetime.combine(date.date(), dep_time))
            arr_dt = KST.localize(datetime.combine(date.date(), arr_time))
            # 자정 넘기는 경우
            if arr_dt < dep_dt:
                from datetime import timedelta
                arr_dt += timedelta(days=1)

            return Flight(
                airline=airline_code,
                airline_name=airline_name,
                flight_number=flight_number,
                from_airport=route.from_airport,
                to_airport=route.to_airport,
                departure_time=dep_dt,
                arrival_time=arr_dt,
                price=price,
            )
        except Exception as exc:
            logger.debug("아이템 파싱 실패: %s", exc)
            return None

    def _extract_times(self, item, lines: List[str]):
        """출도착 시간 추출 (HH:MM 형식)"""
        time_pattern = re.compile(r"\b(\d{2}:\d{2})\b")
        times = []
        # DOM 텍스트에서 시간 패턴 검색
        for line in lines:
            found = time_pattern.findall(line)
            times.extend(found)
        # 최소 2개의 시간 필요 (출발, 도착)
        if len(times) >= 2:
            dep = datetime.strptime(times[0], "%H:%M").time()
            arr = datetime.strptime(times[1], "%H:%M").time()
            return dep, arr

        # 셀렉터 기반 시도
        for dep_sel in ["[class*='departure']", "[class*='Departure']", "[class*='depart']"]:
            dep_el = item.query_selector(dep_sel)
            if dep_el:
                dep_text = dep_el.inner_text().strip()
                found = time_pattern.findall(dep_text)
                if found:
                    dep = datetime.strptime(found[0], "%H:%M").time()
                    break
        else:
            return None, None

        for arr_sel in ["[class*='arrival']", "[class*='Arrival']", "[class*='arrive']"]:
            arr_el = item.query_selector(arr_sel)
            if arr_el:
                arr_text = arr_el.inner_text().strip()
                found = time_pattern.findall(arr_text)
                if found:
                    arr = datetime.strptime(found[0], "%H:%M").time()
                    return dep, arr

        return None, None

    def _extract_price(self, item, lines: List[str]) -> Optional[int]:
        """가격 추출 (숫자 + 원 or 콤마 포함 숫자)"""
        price_pattern = re.compile(r"([\d,]+)\s*원")
        # 텍스트에서 검색
        full_text = " ".join(lines)
        match = price_pattern.search(full_text)
        if match:
            return int(match.group(1).replace(",", ""))

        # 숫자만 있는 경우 (큰 수 = 가격으로 판단)
        number_pattern = re.compile(r"\b(\d{4,6})\b")
        numbers = [int(m) for m in number_pattern.findall(full_text)]
        prices = [n for n in numbers if 10_000 <= n <= 500_000]
        if prices:
            return min(prices)  # 가장 저렴한 것 선택

        # 셀렉터 기반 시도
        for sel in ["[class*='price']", "[class*='Price']", "[class*='fare']"]:
            el = item.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                match = re.search(r"[\d,]+", text)
                if match:
                    val = int(match.group().replace(",", ""))
                    if 10_000 <= val <= 500_000:
                        return val

        return None

    def _extract_airline(self, item, lines: List[str]):
        """항공사 코드 및 이름 추출"""
        full_text = " ".join(lines)

        # 알려진 항공사 이름으로 매칭
        for code, name in AIRLINE_NAMES.items():
            if name in full_text:
                return code, name

        # IATA 코드로 매칭 (예: 7C, KE)
        for code, name in AIRLINE_NAMES.items():
            if code in full_text:
                return code, name

        # alt 속성에서 항공사 이미지 찾기
        img = item.query_selector("img[alt]")
        if img:
            alt = img.get_attribute("alt") or ""
            for code, name in AIRLINE_NAMES.items():
                if name in alt or code in alt:
                    return code, name

        return "??", "알 수 없는 항공사"

    def _extract_flight_number(self, item, lines: List[str], airline_code: str) -> str:
        """편명 추출 (예: 7C101)"""
        pattern = re.compile(rf"{re.escape(airline_code)}\s*(\d{{3,4}})")
        full_text = " ".join(lines)
        match = pattern.search(full_text)
        if match:
            return f"{airline_code}{match.group(1)}"
        return airline_code

    def _filter_by_time(self, flights: List[Flight], route: RouteConfig) -> List[Flight]:
        """설정된 시간 범위에 해당하는 항공편만 반환"""
        filtered = []
        for f in flights:
            dep_str = f.departure_time.strftime("%H:%M")
            if route.time_range.contains(dep_str):
                filtered.append(f)
        return filtered

    def _parse_from_js_state(self, page, route: RouteConfig, date: datetime) -> List[Flight]:
        """
        DOM 파싱 실패 시 JavaScript window.__INITIAL_STATE__ 또는
        window.__data__ 같은 전역 변수에서 데이터 직접 추출 시도
        """
        logger.info("JavaScript 상태에서 데이터 추출 시도...")
        flights: List[Flight] = []

        try:
            # 네이버 SPA는 보통 window.__INITIAL_STATE__ 또는 window.__DATA__에 데이터를 저장
            state_keys = [
                "window.__INITIAL_STATE__",
                "window.__data__",
                "window.__STORE__",
                "window.__APP_STATE__",
            ]
            raw_state = None
            for key in state_keys:
                result = page.evaluate(f"() => JSON.stringify({key})")
                if result and result != "undefined" and result != "null":
                    raw_state = result
                    logger.debug("JS 상태 발견: %s", key)
                    break

            if not raw_state:
                logger.warning("JavaScript 상태를 찾을 수 없습니다.")
                return flights

            import json
            state = json.loads(raw_state)

            # 재귀적으로 항공편 데이터 구조 탐색
            flight_data = self._find_flight_data(state)
            if not flight_data:
                logger.warning("JS 상태에서 항공편 데이터를 찾을 수 없습니다.")
                return flights

            for item in flight_data:
                flight = self._parse_js_flight(item, route, date)
                if flight:
                    flights.append(flight)

        except Exception as exc:
            logger.error("JS 상태 파싱 실패: %s", exc)

        return self._filter_by_time(flights, route)

    def _find_flight_data(self, obj, depth: int = 0):
        """JSON 객체에서 항공편 배열 재귀 탐색"""
        if depth > 8:
            return None
        if isinstance(obj, list) and len(obj) > 0:
            # 항공편 데이터 특징: price, departureTime 같은 키 포함
            if isinstance(obj[0], dict):
                keys = set(obj[0].keys())
                if any(k in keys for k in ("price", "fare", "amount")):
                    return obj
        if isinstance(obj, dict):
            for v in obj.values():
                result = self._find_flight_data(v, depth + 1)
                if result:
                    return result
        return None

    def _parse_js_flight(self, item: dict, route: RouteConfig, date: datetime) -> Optional[Flight]:
        """JS 상태의 항공편 딕셔너리에서 Flight 객체 생성"""
        try:
            price_keys = ("price", "fare", "amount", "lowestPrice")
            dep_keys = ("departureTime", "departure_time", "depTime", "deptTime")
            arr_keys = ("arrivalTime", "arrival_time", "arrTime")
            airline_keys = ("airlineCode", "airline_code", "carrier", "carrierCode")

            price = None
            for k in price_keys:
                if k in item:
                    price = int(str(item[k]).replace(",", ""))
                    break

            dep_str = None
            for k in dep_keys:
                if k in item:
                    dep_str = str(item[k])
                    break

            arr_str = None
            for k in arr_keys:
                if k in item:
                    arr_str = str(item[k])
                    break

            airline = None
            for k in airline_keys:
                if k in item:
                    airline = str(item[k])
                    break

            if not all([price, dep_str, arr_str, airline]):
                return None

            # 시간 파싱 (HH:MM 또는 HHmm)
            dep_time = self._parse_time_str(dep_str)
            arr_time = self._parse_time_str(arr_str)
            if not dep_time or not arr_time:
                return None

            dep_dt = KST.localize(datetime.combine(date.date(), dep_time))
            arr_dt = KST.localize(datetime.combine(date.date(), arr_time))
            if arr_dt < dep_dt:
                from datetime import timedelta
                arr_dt += timedelta(days=1)

            airline_name = AIRLINE_NAMES.get(airline, airline)
            return Flight(
                airline=airline,
                airline_name=airline_name,
                flight_number=str(item.get("flightNumber", item.get("flight_number", airline))),
                from_airport=route.from_airport,
                to_airport=route.to_airport,
                departure_time=dep_dt,
                arrival_time=arr_dt,
                price=price,
            )
        except Exception as exc:
            logger.debug("JS 항공편 파싱 실패: %s", exc)
            return None

    @staticmethod
    def _parse_time_str(s: str):
        """다양한 형식의 시간 문자열을 time 객체로 변환"""
        s = s.strip()
        for fmt in ("%H:%M", "%H%M", "%I:%M %p"):
            try:
                return datetime.strptime(s[:5] if ":" in s else s[:4], fmt.split()[0]).time()
            except ValueError:
                continue
        match = re.search(r"(\d{2}):?(\d{2})", s)
        if match:
            from datetime import time
            return time(int(match.group(1)), int(match.group(2)))
        return None
