"""
Google Flights API 진단 스크립트
"""
from fast_flights import FlightData, Passengers, create_filter, get_flights
import json

DEP, ARR, DATE = "GMP", "CJU", "2026-05-16"

print("="*60)
print(f"  Google Flights 진단  ({DEP}→{ARR} {DATE})")
print("="*60)

try:
    f = create_filter(
        flight_data=[FlightData(date=DATE, from_airport=DEP, to_airport=ARR)],
        trip="one-way",
        seat="economy",
        passengers=Passengers(adults=1),
    )

    result = get_flights(f, currency="KRW")
    print(f"\n✅ 조회 성공! 항공편 {len(result.flights)}건\n")

    for i, fl in enumerate(result.flights[:10], 1):
        print(f"[{i}] {fl}")

except Exception as e:
    print(f"\n❌ 실패: {e}")
    import traceback; traceback.print_exc()
