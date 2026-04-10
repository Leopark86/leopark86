"""
설정 파일 로딩 및 유효성 검사
"""
import os
import yaml
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent


@dataclass
class TimeRange:
    start: str  # "HH:MM"
    end: str    # "HH:MM"

    def contains(self, time_str: str) -> bool:
        """HH:MM 형식의 시간이 이 범위에 포함되는지 확인"""
        return self.start <= time_str <= self.end


@dataclass
class RouteConfig:
    from_airport: str
    to_airport: str
    day_of_week: int  # 0=월 ~ 6=일
    time_range: TimeRange


@dataclass
class AlertConfig:
    max_price_each: int
    max_price_round_trip: int


@dataclass
class ScheduleConfig:
    interval_minutes: int
    weeks_ahead: int
    check_start_hour: int
    check_end_hour: int


@dataclass
class ScraperConfig:
    headless: bool
    timeout_seconds: int
    retry_count: int
    airlines: list


@dataclass
class AppConfig:
    outbound: RouteConfig
    inbound: RouteConfig
    alert: AlertConfig
    schedule: ScheduleConfig
    scraper: ScraperConfig
    kakao_enabled: bool
    telegram_enabled: bool

    # 환경변수에서 로딩
    kakao_rest_api_key: Optional[str] = None
    kakao_access_token: Optional[str] = None
    kakao_refresh_token: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


def load_config(config_path: Optional[str] = None) -> AppConfig:
    path = config_path or (BASE_DIR / "config.yaml")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    out_raw = raw["routes"]["outbound"]
    in_raw = raw["routes"]["inbound"]
    alert_raw = raw["alert"]
    sched_raw = raw["schedule"]
    scraper_raw = raw.get("scraper", {})
    notif_raw = raw.get("notifications", {})

    return AppConfig(
        outbound=RouteConfig(
            from_airport=out_raw["from"],
            to_airport=out_raw["to"],
            day_of_week=int(out_raw["day_of_week"]),
            time_range=TimeRange(
                start=out_raw["time_range"]["start"],
                end=out_raw["time_range"]["end"],
            ),
        ),
        inbound=RouteConfig(
            from_airport=in_raw["from"],
            to_airport=in_raw["to"],
            day_of_week=int(in_raw["day_of_week"]),
            time_range=TimeRange(
                start=in_raw["time_range"]["start"],
                end=in_raw["time_range"]["end"],
            ),
        ),
        alert=AlertConfig(
            max_price_each=int(alert_raw["max_price_each"]),
            max_price_round_trip=int(alert_raw["max_price_round_trip"]),
        ),
        schedule=ScheduleConfig(
            interval_minutes=int(sched_raw["interval_minutes"]),
            weeks_ahead=int(sched_raw["weeks_ahead"]),
            check_start_hour=int(sched_raw.get("check_start_hour", 7)),
            check_end_hour=int(sched_raw.get("check_end_hour", 23)),
        ),
        scraper=ScraperConfig(
            headless=bool(scraper_raw.get("headless", True)),
            timeout_seconds=int(scraper_raw.get("timeout_seconds", 60)),
            retry_count=int(scraper_raw.get("retry_count", 3)),
            airlines=scraper_raw.get("airlines", []),
        ),
        kakao_enabled=notif_raw.get("kakao", {}).get("enabled", True),
        telegram_enabled=notif_raw.get("telegram", {}).get("enabled", False),
        kakao_rest_api_key=os.getenv("KAKAO_REST_API_KEY"),
        kakao_access_token=os.getenv("KAKAO_ACCESS_TOKEN"),
        kakao_refresh_token=os.getenv("KAKAO_REFRESH_TOKEN"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
    )
