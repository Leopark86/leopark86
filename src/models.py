"""
데이터 모델 정의
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Flight:
    """항공편 정보"""
    airline: str           # 항공사 코드 (e.g. 7C, KE)
    airline_name: str      # 항공사 이름 (e.g. 제주항공)
    flight_number: str     # 편명 (e.g. 7C101)
    from_airport: str      # 출발 공항 코드
    to_airport: str        # 도착 공항 코드
    departure_time: datetime  # 출발 시각
    arrival_time: datetime    # 도착 시각
    price: int             # 가격 (원, 편도 1인 기준, 유류할증료 포함)
    seats_left: Optional[int] = None  # 잔여 좌석 수

    @property
    def duration_minutes(self) -> int:
        delta = self.arrival_time - self.departure_time
        return int(delta.total_seconds() / 60)

    @property
    def price_formatted(self) -> str:
        return f"{self.price:,}원"

    def __str__(self) -> str:
        dep = self.departure_time.strftime("%H:%M")
        arr = self.arrival_time.strftime("%H:%M")
        return (
            f"[{self.airline_name}] {self.flight_number} "
            f"{dep}→{arr} ({self.duration_minutes}분) "
            f"{self.price_formatted}"
        )


@dataclass
class FlightPair:
    """왕복 항공편 쌍"""
    outbound: Flight       # 출발편 (김포→제주)
    inbound: Flight        # 귀환편 (제주→김포)

    @property
    def total_price(self) -> int:
        return self.outbound.price + self.inbound.price

    @property
    def total_price_formatted(self) -> str:
        return f"{self.total_price:,}원"

    def summary(self) -> str:
        out_date = self.outbound.departure_time.strftime("%m/%d(%a)")
        in_date = self.inbound.departure_time.strftime("%m/%d(%a)")
        return (
            f"✈ 왕복 합산: {self.total_price_formatted}\n"
            f"  └ 출발 {out_date} {self.outbound}\n"
            f"  └ 귀환 {in_date} {self.inbound}"
        )
