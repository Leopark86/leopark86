"""
네이버 항공 (flight.naver.com) 가격 스크래퍼 - v2

DOM 셀렉터 대신 Playwright의 네트워크 인터셉트를 사용합니다.
브라우저가 페이지를 로딩할 때 내부적으로 호출하는 API 응답을
직접 캡처하므로, 클래스명 변경에 영향받지 않습니다.
"""
import json
import logging
import re
import time
from datetime import datetime, timedelta
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
    BASE_URL = "https://flight.naver.com"
    SEARCH_URL = "{base}/flights/domestic/{from_ap}-{to_ap}-{date}?adult=1&fareType=Y"

    def __init__(self, config: ScraperConfig):
        self.config = config

    def fetch_flights(self, route: RouteConfig, date: datetime) -> List[Flight]:
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
                    wait = 2 ** attempt
                    logger.info("%d초 후 재시도...", wait)
                    time.sleep(wait)

        logger.error("모든 재시도 실패: %s→%s %s", route.from_airport, route.to_airport, date_str)
        return []

    # ------------------------------------------------------------------
    # 핵심: 네트워크 인터셉트 방식
    # ------------------------------------------------------------------

    def _scrape(self, url: str, route: RouteConfig, date: datetime) -> List[Flight]:
        from playwright.sync_api import sync_playwright

        captured: list[dict] = []   # 캡처된 API 응답들

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.config.headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
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
            context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page = context.new_page()

            # ── 네트워크 응답 캡처 ──────────────────────────────────────
            def handle_response(response):
                try:
                    resp_url = response.url
                    # 네이버 항공 내부 API 패턴 필터링
                    if any(kw in resp_url for kw in [
                        "itinerary", "fare", "flight", "domestic", "schedule"
                    ]) and response.status == 200:
                        ct = response.headers.get("content-type", "")
                        if "json" in ct:
                            try:
                                body = response.json()
                                if body:
                                    captured.append({"url": resp_url, "body": body})
                                    logger.debug("API 캡처: %s", resp_url)
                            except Exception:
                                pass
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                logger.debug("페이지 로딩: %s", url)
                page.goto(url, timeout=self.config.timeout_seconds * 1000,
                          wait_until="domcontentloaded")

                # 최대 30초 동안 API 응답이 채워질 때까지 대기
                deadline = time.time() + 30
                while time.time() < deadline:
                    if captured:
                        # 추가 응답이 올 수 있으니 3초 더 대기
                        time.sleep(3)
                        break
                    time.sleep(1)

                if not captured:
                    # API 캡처 실패 → 페이지 텍스트 파싱으로 폴백
                    logger.warning("API 캡처 없음. 페이지 텍스트 파싱 시도...")
                    flights = self._parse_from_page_text(page, route, date)
                else:
                    flights = self._parse_captured(captured, route, date)

            except Exception as exc:
                # 실패 시 스크린샷 저장 (로그 디버깅용)
                try:
                    page.screenshot(path="logs/debug_screenshot.png", full_page=False)
                    logger.info("디버그 스크린샷 저장: logs/debug_screenshot.png")
                except Exception:
                    pass
                raise exc
            finally:
                browser.close()

        # 시간 범위 필터 + 가격순 정렬
        flights = self._filter_by_time(flights, route)
        return sorted(flights, key=lambda f: f.price)

    # ------------------------------------------------------------------
    # 캡처된 API 응답 파싱
    # ------------------------------------------------------------------

    def _parse_captured(self, captured: list, route: RouteConfig, date: datetime) -> List[Flight]:
        flights: List[Flight] = []
        for item in captured:
            body = item["body"]
            extracted = self._extract_flights_from_json(body, route, date)
            flights.extend(extracted)
            if extracted:
                logger.debug("API %s 에서 %d건 추출", item["url"], len(extracted))

        # 중복 제거 (같은 편명+시간)
        seen = set()
        unique = []
        for f in flights:
            key = (f.flight_number, f.departure_time)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique

    def _extract_flights_from_json(self, obj, route: RouteConfig, date: datetime,
                                   depth: int = 0) -> List[Flight]:
        """JSON 객체를 재귀 탐색하여 항공편 데이터 추출"""
        if depth > 10:
            return []
        results = []

        if isinstance(obj, list):
            for item in obj:
                results.extend(self._extract_flights_from_json(item, route, date, depth + 1))

        elif isinstance(obj, dict):
            # 항공편 데이터 특징 키 탐지
            flight = self._try_parse_flight_dict(obj, route, date)
            if flight:
                results.append(flight)
            else:
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        results.extend(self._extract_flights_from_json(v, route, date, depth + 1))

        return results

    def _try_parse_flight_dict(self, d: dict, route: RouteConfig, date: datetime) -> Optional[Flight]:
        """딕셔너리에서 항공편 정보 추출 시도 (다양한 키명 지원)"""
        try:
            # 가격 키
            price = None
            for k in ("fare", "price", "amount", "lowestFare", "totalFare",
                      "adultFare", "salePrice", "chargeAmt"):
                if k in d:
                    val = d[k]
                    if isinstance(val, (int, float)) and 10_000 <= val <= 2_000_000:
                        price = int(val)
                        break
                    elif isinstance(val, str):
                        cleaned = re.sub(r"[^\d]", "", val)
                        if cleaned and 10_000 <= int(cleaned) <= 2_000_000:
                            price = int(cleaned)
                            break

            if not price:
                return None

            # 출발시간 키
            dep_str = None
            for k in ("departureTime", "depTime", "departure", "deptTime",
                      "depDateTime", "std", "etd", "departAt"):
                if k in d and d[k]:
                    dep_str = str(d[k])
                    break

            # 도착시간 키
            arr_str = None
            for k in ("arrivalTime", "arrTime", "arrival", "arrDateTime",
                      "sta", "eta", "arriveAt"):
                if k in d and d[k]:
                    arr_str = str(d[k])
                    break

            if not dep_str or not arr_str:
                return None

            dep_time = self._parse_time(dep_str)
            arr_time = self._parse_time(arr_str)
            if not dep_time or not arr_time:
                return None

            dep_dt = KST.localize(datetime.combine(date.date(), dep_time))
            arr_dt = KST.localize(datetime.combine(date.date(), arr_time))
            if arr_dt < dep_dt:
                arr_dt += timedelta(days=1)

            # 항공사 키
            airline_code = "??"
            for k in ("airlineCode", "carrier", "carrierCode", "airline",
                      "airlineId", "operatingCarrier"):
                if k in d and d[k]:
                    airline_code = str(d[k]).strip().upper()
                    break

            # 편명 키
            flight_num = airline_code
            for k in ("flightNumber", "flightNo", "flight", "flightId",
                      "편명", "flightNum"):
                if k in d and d[k]:
                    flight_num = str(d[k]).strip()
                    break

            airline_name = AIRLINE_NAMES.get(airline_code, airline_code)

            return Flight(
                airline=airline_code,
                airline_name=airline_name,
                flight_number=flight_num,
                from_airport=route.from_airport,
                to_airport=route.to_airport,
                departure_time=dep_dt,
                arrival_time=arr_dt,
                price=price,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 폴백: 페이지 텍스트에서 가격/시간 패턴 파싱
    # ------------------------------------------------------------------

    def _parse_from_page_text(self, page, route: RouteConfig, date: datetime) -> List[Flight]:
        """DOM 파싱 폴백 — 렌더링된 텍스트에서 패턴으로 항공편 추출"""
        flights: List[Flight]= []
        try:
            # 모든 텍스트 콘텐츠 수집
            text = page.inner_text("body")

            # 패턴: HH:MM → HH:MM 형식의 출도착 시간 쌍
            time_pair = re.compile(r"(\d{2}:\d{2})\s*[→\-~]\s*(\d{2}:\d{2})")
            # 패턴: 가격 (5~6자리 숫자 + 원)
            price_pat = re.compile(r"([\d,]{5,10})\s*원")

            time_matches = time_pair.findall(text)
            price_matches = [int(m.replace(",", "")) for m in price_pat.findall(text)
                             if 10_000 <= int(m.replace(",", "")) <= 2_000_000]

            if not time_matches or not price_matches:
                logger.warning("페이지 텍스트에서도 항공편 데이터를 찾을 수 없습니다.")
                return flights

            logger.info("텍스트 파싱: 시간쌍 %d개, 가격 %d개 발견",
                        len(time_matches), len(price_matches))

            # 시간쌍과 가격을 순서대로 매핑 (추정)
            for i, (dep_s, arr_s) in enumerate(time_matches[:len(price_matches)]):
                try:
                    dep_time = datetime.strptime(dep_s, "%H:%M").time()
                    arr_time = datetime.strptime(arr_s, "%H:%M").time()
                    price = price_matches[i] if i < len(price_matches) else price_matches[-1]

                    dep_dt = KST.localize(datetime.combine(date.date(), dep_time))
                    arr_dt = KST.localize(datetime.combine(date.date(), arr_time))
                    if arr_dt < dep_dt:
                        arr_dt += timedelta(days=1)

                    flights.append(Flight(
                        airline="??",
                        airline_name="항공사 미상",
                        flight_number=f"UNKNOWN-{i}",
                        from_airport=route.from_airport,
                        to_airport=route.to_airport,
                        departure_time=dep_dt,
                        arrival_time=arr_dt,
                        price=price,
                    ))
                except Exception:
                    continue

        except Exception as exc:
            logger.error("텍스트 파싱 실패: %s", exc)

        return flights

    # ------------------------------------------------------------------
    # 공통 유틸
    # ------------------------------------------------------------------

    def _filter_by_time(self, flights: List[Flight], route: RouteConfig) -> List[Flight]:
        filtered = []
        for f in flights:
            dep_str = f.departure_time.strftime("%H:%M")
            if route.time_range.contains(dep_str):
                filtered.append(f)
        return filtered

    @staticmethod
    def _parse_time(s: str) -> Optional[datetime.time]:
        """다양한 형식의 시간 문자열을 time 객체로 변환"""
        s = s.strip()
        # ISO 형식: 2026-04-25T06:30:00
        iso = re.search(r"T(\d{2}):(\d{2})", s)
        if iso:
            from datetime import time
            return time(int(iso.group(1)), int(iso.group(2)))
        # HH:MM
        m = re.search(r"(\d{2}):(\d{2})", s)
        if m:
            from datetime import time
            return time(int(m.group(1)), int(m.group(2)))
        # HHMM
        m = re.fullmatch(r"(\d{2})(\d{2})", s)
        if m:
            from datetime import time
            return time(int(m.group(1)), int(m.group(2)))
        return None
