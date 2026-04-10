"""
가격 모니터링 스케줄러

매 N분마다 네이버 항공에서 가격을 조회하고,
설정한 임계값 이하의 항공권이 있으면 카카오톡/텔레그램으로 알림을 전송합니다.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from urllib.parse import urlencode

import pytz

from src.config import AppConfig, RouteConfig
from src.models import Flight, FlightPair
from src.scrapers.naver import NaverFlightScraper

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")

# 이미 알림 보낸 편명+날짜 조합 기록 (중복 알림 방지)
_notified_cache: set[str] = set()


def get_target_dates(day_of_week: int, weeks_ahead: int) -> List[datetime]:
    """
    특정 요일의 다가오는 날짜 목록을 반환합니다.

    Args:
        day_of_week: 0=월 ~ 6=일
        weeks_ahead: 몇 주 앞까지 검색

    Returns:
        KST 기준 날짜 목록
    """
    now = datetime.now(KST)
    dates = []
    for week in range(0, weeks_ahead + 1):
        # 이번 주의 해당 요일 날짜 계산
        days_until = (day_of_week - now.weekday()) % 7
        target = now + timedelta(days=days_until + week * 7)
        target = target.replace(hour=0, minute=0, second=0, microsecond=0)
        # 오늘 이후 날짜만 포함
        if target.date() > now.date():
            dates.append(target)
    return dates


def build_search_url(route: RouteConfig, date: datetime) -> str:
    """네이버 항공 검색 URL 생성"""
    date_str = date.strftime("%Y%m%d")
    return (
        f"https://flight.naver.com/flights/domestic/"
        f"{route.from_airport}-{route.to_airport}-{date_str}"
        f"?adult=1&fareType=Y"
    )


def build_roundtrip_search_url(
    outbound_route: RouteConfig,
    inbound_route: RouteConfig,
    outbound_date: datetime,
    inbound_date: datetime,
) -> str:
    """네이버 항공 왕복 검색 URL 생성"""
    out_date = outbound_date.strftime("%Y%m%d")
    in_date = inbound_date.strftime("%Y%m%d")
    return (
        f"https://flight.naver.com/flights/domestic/"
        f"{outbound_route.from_airport}-{outbound_route.to_airport}-{out_date}"
        f"/{inbound_route.from_airport}-{inbound_route.to_airport}-{in_date}"
        f"?adult=1&fareType=Y"
    )


def format_alert_message(
    pairs: List[FlightPair],
    threshold: int,
    now: datetime,
) -> List[str]:
    """카카오톡/텔레그램 알림 메시지 포맷"""
    lines = [
        "✈ 항공권 가격 알림",
        f"📅 조회 시각: {now.strftime('%Y-%m-%d %H:%M')} (KST)",
        f"💰 기준 가격 이하: {threshold:,}원 (왕복)",
        "─" * 30,
    ]

    for i, pair in enumerate(pairs[:5], 1):  # 최대 5개만 표시
        out = pair.outbound
        inn = pair.inbound
        lines.append(
            f"[{i}] 왕복 합계 {pair.total_price_formatted}"
        )
        lines.append(
            f"  ◆ 출발 {out.departure_time.strftime('%m/%d(%a)')} "
            f"{out.departure_time.strftime('%H:%M')}→"
            f"{out.arrival_time.strftime('%H:%M')} "
            f"[{out.airline_name}] {out.price_formatted}"
        )
        lines.append(
            f"  ◆ 귀환 {inn.departure_time.strftime('%m/%d(%a)')} "
            f"{inn.departure_time.strftime('%H:%M')}→"
            f"{inn.arrival_time.strftime('%H:%M')} "
            f"[{inn.airline_name}] {inn.price_formatted}"
        )
        lines.append("")

    if len(pairs) > 5:
        lines.append(f"... 외 {len(pairs) - 5}개 더")

    return lines


def format_single_alert_message(
    route_label: str,
    flights: List[Flight],
    threshold: int,
    now: datetime,
) -> List[str]:
    """편도 알림 메시지 포맷"""
    lines = [
        f"✈ 항공권 가격 알림 ({route_label})",
        f"📅 조회 시각: {now.strftime('%Y-%m-%d %H:%M')} (KST)",
        f"💰 기준 가격 이하: {threshold:,}원",
        "─" * 30,
    ]

    for i, f in enumerate(flights[:5], 1):
        lines.append(
            f"[{i}] {f.departure_time.strftime('%m/%d(%a)')} "
            f"{f.departure_time.strftime('%H:%M')}→"
            f"{f.arrival_time.strftime('%H:%M')} "
            f"[{f.airline_name}] {f.price_formatted}"
        )

    if len(flights) > 5:
        lines.append(f"... 외 {len(flights) - 5}개 더")

    return lines


class PriceMonitor:
    """
    항공권 가격 모니터

    APScheduler와 연동하여 주기적으로 가격을 확인하고 알림을 발송합니다.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.scraper = NaverFlightScraper(config.scraper)
        self._notifiers = self._build_notifiers()

    def _build_notifiers(self) -> list:
        """설정에 따라 알림 전송기 초기화"""
        notifiers = []
        cfg = self.config

        if cfg.kakao_enabled and cfg.kakao_access_token:
            from src.notifiers.kakao import KakaoNotifier
            n = KakaoNotifier(
                rest_api_key=cfg.kakao_rest_api_key or "",
                access_token=cfg.kakao_access_token,
                refresh_token=cfg.kakao_refresh_token,
            )
            notifiers.append(("카카오톡", n))
            logger.info("카카오톡 알림 활성화")
        elif cfg.kakao_enabled:
            logger.warning(
                "카카오톡 활성화 설정이지만 액세스 토큰이 없습니다. "
                "setup_kakao.py를 실행하세요."
            )

        if cfg.telegram_enabled and cfg.telegram_bot_token and cfg.telegram_chat_id:
            from src.notifiers.telegram import TelegramNotifier
            n = TelegramNotifier(cfg.telegram_bot_token, cfg.telegram_chat_id)
            notifiers.append(("텔레그램", n))
            logger.info("텔레그램 알림 활성화")
        elif cfg.telegram_enabled:
            logger.warning(
                "텔레그램 활성화 설정이지만 봇 토큰 또는 Chat ID가 없습니다."
            )

        if not notifiers:
            logger.warning("활성화된 알림 수단이 없습니다! .env 파일을 확인하세요.")

        return notifiers

    def check_prices(self, force: bool = False) -> None:
        """
        가격 확인 메인 로직 (스케줄러에서 주기적으로 호출)

        1. 다가오는 토요일 출발편 + 월요일 귀환편 목록 수집
        2. 가격 임계값 이하 조합 필터링
        3. 알림 전송 (중복 방지 포함)

        Args:
            force: True이면 운영시간 제한을 무시하고 강제 실행 (--once 모드)
        """
        now = datetime.now(KST)
        hour = now.hour
        # 운영 시간 외에는 체크 생략 (force=True 이면 통과)
        if not force and not (self.config.schedule.check_start_hour <= hour < self.config.schedule.check_end_hour):
            logger.info("운영 시간 외 (현재 KST %02d시, 운영: %d~%d시) — 체크 건너뜀",
                        hour, self.config.schedule.check_start_hour, self.config.schedule.check_end_hour)
            return

        logger.info("===== 가격 체크 시작: %s =====", now.strftime("%Y-%m-%d %H:%M:%S KST"))

        outbound_dates = get_target_dates(
            self.config.outbound.day_of_week,
            self.config.schedule.weeks_ahead,
        )
        inbound_dates = get_target_dates(
            self.config.inbound.day_of_week,
            self.config.schedule.weeks_ahead,
        )

        alert_pairs: List[FlightPair] = []

        for out_date in outbound_dates:
            # 출발일과 대응되는 귀환일: 같은 주 또는 다음 월요일 (2박 기준)
            matching_in_dates = self._match_inbound_dates(out_date, inbound_dates)
            if not matching_in_dates:
                continue

            out_flights = self.scraper.fetch_flights(self.config.outbound, out_date)
            cheap_out = [f for f in out_flights if f.price <= self.config.alert.max_price_each]

            if not cheap_out and not out_flights:
                continue

            for in_date in matching_in_dates:
                in_flights = self.scraper.fetch_flights(self.config.inbound, in_date)
                cheap_in = [f for f in in_flights if f.price <= self.config.alert.max_price_each]

                # 왕복 합산 기준 필터링
                for out_f in (cheap_out or out_flights[:3]):
                    for in_f in (cheap_in or in_flights[:3]):
                        total = out_f.price + in_f.price
                        if total <= self.config.alert.max_price_round_trip:
                            pair = FlightPair(outbound=out_f, inbound=in_f)
                            cache_key = (
                                f"{out_f.flight_number}_{out_date.date()}_"
                                f"{in_f.flight_number}_{in_date.date()}_"
                                f"{total}"
                            )
                            if cache_key not in _notified_cache:
                                alert_pairs.append(pair)
                                _notified_cache.add(cache_key)
                                logger.info("알림 대상 발견: %s", pair.summary())

        if alert_pairs:
            alert_pairs.sort(key=lambda p: p.total_price)
            self._send_alert(alert_pairs, now)
        else:
            logger.info("임계값 이하 항공편 없음 (왕복 %d원 이하)", self.config.alert.max_price_round_trip)

        logger.info("===== 가격 체크 완료 =====")

    def _match_inbound_dates(
        self, outbound_date: datetime, inbound_dates: List[datetime]
    ) -> List[datetime]:
        """
        출발일에 대응하는 귀환일 반환
        토요일 출발 → 같은 주 월요일 (2일 뒤)
        """
        result = []
        for d in inbound_dates:
            diff = (d.date() - outbound_date.date()).days
            # 1~5일 범위의 귀환일 (당일 귀환 제외, 일주일 이내)
            if 1 <= diff <= 5:
                result.append(d)
        return result

    def _send_alert(self, pairs: List[FlightPair], now: datetime) -> None:
        """알림 전송"""
        if not self._notifiers:
            logger.warning("알림 전송 수단이 없습니다.")
            return

        # 왕복 기준 검색 URL (첫 번째 페어 기준)
        best = pairs[0]
        search_url = build_roundtrip_search_url(
            self.config.outbound,
            self.config.inbound,
            best.outbound.departure_time,
            best.inbound.departure_time,
        )

        message_lines = format_alert_message(
            pairs, self.config.alert.max_price_round_trip, now
        )

        for name, notifier in self._notifiers:
            try:
                ok = notifier.send_flight_alert(message_lines, search_url)
                if ok:
                    logger.info("%s 알림 전송 완료", name)
                else:
                    logger.error("%s 알림 전송 실패", name)
            except Exception as exc:
                logger.error("%s 알림 전송 예외: %s", name, exc)

    def test_notification(self) -> None:
        """알림 테스트 전송"""
        now = datetime.now(KST)
        message_lines = [
            "✅ 항공권 가격 알림 테스트",
            f"📅 시각: {now.strftime('%Y-%m-%d %H:%M')} (KST)",
            "이 메시지가 수신되면 알림 설정이 완료된 것입니다!",
            "",
            "설정된 조건:",
            f"  출발: 김포→제주 토요일 {self.config.outbound.time_range.start}~{self.config.outbound.time_range.end}",
            f"  귀환: 제주→김포 월요일 {self.config.inbound.time_range.start}~{self.config.inbound.time_range.end}",
            f"  기준 가격: 왕복 {self.config.alert.max_price_round_trip:,}원 이하",
        ]

        for name, notifier in self._notifiers:
            try:
                ok = notifier.send_flight_alert(message_lines, "https://flight.naver.com")
                status = "성공" if ok else "실패"
                logger.info("%s 테스트 알림 %s", name, status)
                print(f"  {name} 테스트: {status}")
            except Exception as exc:
                logger.error("%s 테스트 실패: %s", name, exc)
                print(f"  {name} 테스트: 실패 ({exc})")
