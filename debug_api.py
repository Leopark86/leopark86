"""
네이버 항공 API 응답 진단 스크립트
실행: python debug_api.py

어떤 엔드포인트가 동작하는지, 어떤 JSON이 오는지 확인합니다.
"""
import requests, json, re, sys

DEP, ARR, DATE = "GMP", "CJU", "20260516"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://flight.naver.com/",
}

ENDPOINTS = [
    f"https://flight.naver.com/api/v1/fares?departureAirport={DEP}&arrivalAirport={ARR}&departureDate={DATE}&adults=1&fareType=Y",
    f"https://flight.naver.com/api/v1/domestic/oneway?from={DEP}&to={ARR}&date={DATE}&adults=1",
    f"https://flight.naver.com/api/v1/schedules?dep={DEP}&arr={ARR}&date={DATE}&cnt=1",
    f"https://flight.naver.com/api/v2/domestic?departureAirport={DEP}&arrivalAirport={ARR}&date={DATE}&adults=1",
]

print(f"\n{'='*60}")
print(f"  네이버 항공 API 진단  ({DEP}→{ARR} {DATE})")
print(f"{'='*60}\n")

session = requests.Session()
# 먼저 메인 페이지 방문 (쿠키 획득)
print("[0] 메인 페이지 방문 중...")
try:
    r = session.get("https://flight.naver.com/", headers=HEADERS, timeout=10)
    print(f"    상태코드: {r.status_code}, 쿠키: {dict(session.cookies)}\n")
except Exception as e:
    print(f"    실패: {e}\n")

for i, url in enumerate(ENDPOINTS, 1):
    print(f"[{i}] {url[:80]}...")
    try:
        r = session.get(url, headers=HEADERS, timeout=15)
        ct = r.headers.get("content-type", "")
        print(f"    상태코드: {r.status_code}  Content-Type: {ct}")
        if r.status_code == 200:
            if "json" in ct:
                data = r.json()
                print(f"    JSON 키: {list(data.keys()) if isinstance(data, dict) else f'list[{len(data)}]'}")
                print(f"    미리보기: {json.dumps(data, ensure_ascii=False)[:300]}")
            else:
                print(f"    응답 미리보기: {r.text[:200]}")
        elif r.status_code == 302:
            print(f"    리다이렉트 → {r.headers.get('Location')}")
    except Exception as e:
        print(f"    오류: {e}")
    print()

# 페이지 HTML에서 JSON 데이터 탐색
print(f"[{len(ENDPOINTS)+1}] 페이지 HTML에서 JSON 탐색 중...")
try:
    page_url = f"https://flight.naver.com/flights/domestic/{DEP}-{ARR}-{DATE}?adult=1&fareType=Y"
    r = session.get(page_url, headers=HEADERS, timeout=20)
    print(f"    상태코드: {r.status_code}, 응답 크기: {len(r.text):,}자")

    patterns = [
        (r"window\.__INITIAL_STATE__\s*=\s*({.+?});", "INITIAL_STATE"),
        (r"window\.__data__\s*=\s*({.+?});", "__data__"),
        (r'"flights"\s*:\s*(\[.+?\])', "flights array"),
        (r'"schedules"\s*:\s*(\[.+?\])', "schedules array"),
    ]
    for pat, name in patterns:
        m = re.search(pat, r.text, re.DOTALL)
        if m:
            preview = m.group(1)[:200]
            print(f"    ✅ '{name}' 발견! 미리보기: {preview}")
        else:
            print(f"    ❌ '{name}' 없음")
except Exception as e:
    print(f"    오류: {e}")

print("\n진단 완료. 위 결과를 공유해주세요.")
