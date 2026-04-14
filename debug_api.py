"""
Google Flights API 진단 - fast-flights 버전 호환성 확인
"""
import fast_flights, inspect

DEP, ARR, DATE = "GMP", "CJU", "2026-05-16"

print(f"fast-flights 버전: {fast_flights.__version__ if hasattr(fast_flights,'__version__') else '알 수 없음'}")
print(f"제공 함수/클래스: {[x for x in dir(fast_flights) if not x.startswith('_')]}\n")

# ── 방법 1: 최신 API (2.x) ────────────────────────────────────
try:
    from fast_flights import FlightData, Passengers, create_filter, get_flights
    print("[방법 1] create_filter / get_flights 시도...")

    f = create_filter(
        flight_data=[FlightData(date=DATE, from_airport=DEP, to_airport=ARR)],
        trip="one-way",
        seat="economy",
        passengers=Passengers(adults=1),
    )
    result = get_flights(f, currency="KRW")
    print(f"✅ 성공! 항공편 {len(result.flights)}건")
    if result.flights:
        fl = result.flights[0]
        print(f"첫 번째 항공편 속성: {[a for a in dir(fl) if not a.startswith('_')]}")
        print(f"첫 번째 항공편 값: {fl}")
        # 각 속성 값 출력
        for attr in ['price','departure','arrival','airline','name','flight_number','duration']:
            val = getattr(fl, attr, 'N/A')
            print(f"  .{attr} = {repr(val)}")
    import sys; sys.exit(0)
except Exception as e:
    print(f"❌ 방법 1 실패: {e}\n")

# ── 방법 2: 구버전 API (1.x) ──────────────────────────────────
try:
    from fast_flights import get_flights as gf
    print("[방법 2] 구버전 get_flights 시도...")
    result = gf(departure=DEP, destination=ARR, date=DATE, currency="KRW")
    print(f"✅ 성공! 결과: {result}")
except Exception as e:
    print(f"❌ 방법 2 실패: {e}\n")

print("진단 완료.")
