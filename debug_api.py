"""
제주항공 세션 처리 + 응답 상세 진단
"""
import requests, json, re
from bs4 import BeautifulSoup

DEP, ARR, DATE = "GMP", "CJU", "20260516"

HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

print("="*60)
print("  제주항공 세션 기반 스케줄 조회 진단")
print("="*60)

session = requests.Session()

# ── Step 1: 메인 페이지로 세션 쿠키 획득 ─────────────────────
print("\n[Step 1] 메인 페이지 방문 (세션 쿠키 획득)")
r = session.get("https://www.jejuair.net/ko/main/index.do",
                headers=HDR, timeout=15)
print(f"  상태: {r.status_code}")
print(f"  쿠키: {dict(session.cookies)}")

# ── Step 2: 예약 메인 페이지로 이동 ──────────────────────────
print("\n[Step 2] 예약 페이지 방문")
r2 = session.get("https://www.jejuair.net/ko/main/booking/onewayBooking.do",
                 headers={**HDR, "Referer": "https://www.jejuair.net/ko/main/index.do"},
                 timeout=15)
print(f"  상태: {r2.status_code}, 크기: {len(r2.content)}bytes")

# CSRF 토큰 탐색
soup = BeautifulSoup(r2.content, "html.parser")
csrf = None
for tag in soup.find_all("input", {"type": "hidden"}):
    name = tag.get("name", "")
    if "csrf" in name.lower() or "token" in name.lower():
        csrf = tag.get("value")
        print(f"  CSRF 토큰 발견: {name}={csrf}")

# ── Step 3: 스케줄 API 호출 (세션 쿠키 + CSRF) ───────────────
print("\n[Step 3] 스케줄 조회 API 호출")
post_data = {
    "tripType": "OW",
    "depAirportCode": DEP,
    "arrAirportCode": ARR,
    "depDt": DATE,
    "adtCnt": "1",
    "chdCnt": "0",
    "infCnt": "0",
}
if csrf:
    post_data["_csrf"] = csrf

r3 = session.post(
    "https://www.jejuair.net/jejuair/com/schedule/selectSchedule.do",
    data=post_data,
    headers={
        **HDR,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.jejuair.net/ko/main/booking/onewayBooking.do",
    },
    timeout=20,
)
print(f"  상태: {r3.status_code}")
print(f"  Content-Type: {r3.headers.get('content-type','')}")
print(f"  응답 크기: {len(r3.content)}bytes")

if "json" in r3.headers.get("content-type", ""):
    try:
        data = r3.json()
        print(f"\n  ✅ JSON 응답!")
        print(f"  키: {list(data.keys()) if isinstance(data,dict) else f'list[{len(data)}]'}")
        print(f"  전체:\n{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}")
    except Exception as e:
        print(f"  JSON 파싱 실패: {e}")
        print(f"  원문: {r3.text[:500]}")
else:
    decoded = r3.content.decode("utf-8", errors="replace")
    print(f"  HTML 응답 앞부분:\n{decoded[:800]}")

    # HTML에서 스케줄 데이터 탐색
    print("\n  [HTML 내 데이터 탐색]")
    soup3 = BeautifulSoup(r3.content, "html.parser")

    # script 태그 내 JSON 탐색
    for sc in soup3.find_all("script"):
        t = sc.get_text()
        if any(k in t for k in ["depTime","arrTime","flightNo","fareAmt"]):
            print(f"  ✅ 스크립트에서 항공편 관련 데이터 발견!")
            print(f"  내용: {t[:600]}")
            break
    else:
        print("  script 태그에서 항공편 데이터 없음")

    # 테이블 탐색
    tables = soup3.find_all("table")
    print(f"  테이블 수: {len(tables)}")
    for i, tbl in enumerate(tables[:3]):
        print(f"  테이블[{i}] 텍스트: {tbl.get_text()[:200]}")

print("\n진단 완료.")
