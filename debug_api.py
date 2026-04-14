"""
Google Flights API 진단 - fast-flights 2.2 API 확인
"""
import fast_flights, inspect, sys

DEP, ARR, DATE = "GMP", "CJU", "2026-05-16"

print(f"fast-flights 버전: {fast_flights.__version__ if hasattr(fast_flights,'__version__') else '알 수 없음'}")
print(f"제공 함수/클래스: {[x for x in dir(fast_flights) if not x.startswith('_')]}\n")

# ── 2.2 API: create_filter → get_flights_from_filter ─────────
try:
    from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter
    print("[방법 1] create_filter → get_flights_from_filter 시도...")

    f = create_filter(
        flight_data=[FlightData(date=DATE, from_airport=DEP, to_airport=ARR)],
        trip="one-way",
        seat="economy",
        passengers=Passengers(adults=1),
    )
    result = get_flights_from_filter(f, currency="KRW")
    print(f"✅ 성공! 항공편 {len(result.flights)}건")
    if result.flights:
        fl = result.flights[0]
        print(f"첫 번째 항공편 속성: {[a for a in dir(fl) if not a.startswith('_')]}")
        print(f"첫 번째 항공편 값: {fl}")
        for attr in ['price', 'departure', 'arrival', 'airline', 'name', 'flight_number', 'duration']:
            val = getattr(fl, attr, 'N/A')
            print(f"  .{attr} = {repr(val)}")
    else:
        print("⚠️  항공편 0건 (날짜/구간 확인 필요)")
    sys.exit(0)
except Exception as e:
    print(f"❌ 방법 1 실패: {e}\n")

# ── 2.2 API fallback: get_flights 직접 호출 ───────────────────
try:
    from fast_flights import FlightData, Passengers, get_flights
    print("[방법 2] get_flights 직접 호출 시도...")
    result = get_flights(
        flight_data=[FlightData(date=DATE, from_airport=DEP, to_airport=ARR)],
        trip="one-way",
        seat="economy",
        passengers=Passengers(adults=1),
    )
    print(f"✅ 성공! 항공편 {len(result.flights)}건")
    if result.flights:
        fl = result.flights[0]
        print(f"첫 번째 항공편 속성: {[a for a in dir(fl) if not a.startswith('_')]}")
        for attr in ['price', 'departure', 'arrival', 'airline', 'name', 'flight_number']:
            print(f"  .{attr} = {repr(getattr(fl, attr, 'N/A'))}")
    sys.exit(0)
except Exception as e:
    print(f"❌ 방법 2 실패: {e}\n")

print("진단 완료 — 두 방법 모두 실패.")
