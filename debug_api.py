"""
항공사별 API 진단 스크립트 (GitHub Actions에서 실행)
"""
import requests, json, re

DEP, ARR, DATE = "GMP", "CJU", "20260516"
HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

def probe(label, method, url, **kwargs):
    try:
        r = requests.request(method, url, timeout=15, **kwargs)
        ct = r.headers.get("content-type", "")
        print(f"  [{r.status_code}] {label}")
        if r.status_code == 200:
            if "json" in ct:
                try:
                    d = r.json()
                    print(f"    JSON 키: {list(d.keys()) if isinstance(d,dict) else f'list[{len(d)}]'}")
                    print(f"    미리보기: {json.dumps(d,ensure_ascii=False)[:400]}")
                except Exception:
                    print(f"    (JSON 파싱 실패) 텍스트: {r.text[:300]}")
            else:
                snippet = r.text[:400].replace("\n"," ")
                print(f"    텍스트 미리보기: {snippet}")
        elif r.status_code in (301,302):
            print(f"    → Redirect: {r.headers.get('Location')}")
        return r.status_code
    except Exception as e:
        print(f"  [ERR] {label}: {e}")
        return 0

print("="*60)
print(f"  항공사 API 진단  ({DEP}→{ARR} {DATE})")
print("="*60)

# ── 제주항공 ──────────────────────────────────────────────────
print("\n■ 제주항공 (jejuair.net)")
probe("메인", "GET", "https://www.jejuair.net/", headers=HDR)
probe("스케줄 조회 (POST)", "POST",
      "https://www.jejuair.net/jejuair/com/schedule/selectSchedule.do",
      headers={**HDR, "Content-Type":"application/x-www-form-urlencoded",
               "Referer":"https://www.jejuair.net/"},
      data={"tripType":"OW","depAirportCode":DEP,"arrAirportCode":ARR,
            "depDt":DATE,"adtCnt":"1","chdCnt":"0","infCnt":"0"})
probe("운임조회 (POST)", "POST",
      "https://www.jejuair.net/jejuair/com/price/selectFare.do",
      headers={**HDR, "Content-Type":"application/x-www-form-urlencoded",
               "Referer":"https://www.jejuair.net/"},
      data={"tripType":"OW","depAirportCode":DEP,"arrAirportCode":ARR,
            "depDt":DATE,"adtCnt":"1"})
probe("신규 예약 API (GET)", "GET",
      f"https://booking.jejuair.net/api/v1/schedule?dep={DEP}&arr={ARR}&date={DATE}&adt=1",
      headers={**HDR,"Referer":"https://booking.jejuair.net/"})

# ── 진에어 ────────────────────────────────────────────────────
print("\n■ 진에어 (jinair.com)")
probe("스케줄 조회 (GET)", "GET",
      f"https://www.jinair.com/booking/schedule?depApt={DEP}&arrApt={ARR}&depDt={DATE}&adtCnt=1",
      headers={**HDR,"Referer":"https://www.jinair.com/"})
probe("운임 조회 API", "POST",
      "https://www.jinair.com/booking/fareInfo",
      headers={**HDR,"Content-Type":"application/json",
               "Referer":"https://www.jinair.com/"},
      json={"depAirportCode":DEP,"arrAirportCode":ARR,"depDate":DATE,"paxCount":1})

# ── 티웨이항공 ────────────────────────────────────────────────
print("\n■ 티웨이항공 (twayair.com)")
probe("운임달력 (POST)", "POST",
      "https://www.twayair.com/app/popup/fareCalendar",
      headers={**HDR,"Content-Type":"application/x-www-form-urlencoded",
               "Referer":"https://www.twayair.com/"},
      data={"depAirportCode":DEP,"arrAirportCode":ARR,"depDt":DATE,
            "tripType":"OW","adultCnt":"1","childCnt":"0","infantCnt":"0"})
probe("스케줄 검색 (POST)", "POST",
      "https://www.twayair.com/app/flight/search",
      headers={**HDR,"Content-Type":"application/json",
               "Referer":"https://www.twayair.com/"},
      json={"departureAirport":DEP,"arrivalAirport":ARR,"departureDate":DATE,"adults":1})

# ── 에어서울 ──────────────────────────────────────────────────
print("\n■ 에어서울 (flyairseoul.com)")
probe("운임 조회 (POST)", "POST",
      "https://flyairseoul.com/CW/ko/selectFlightSchedule.do",
      headers={**HDR,"Content-Type":"application/x-www-form-urlencoded",
               "Referer":"https://flyairseoul.com/"},
      data={"tripType":"OW","depAirportCode":DEP,"arrAirportCode":ARR,
            "depDt":DATE,"adtCnt":"1","chdCnt":"0","infCnt":"0"})

print("\n진단 완료.")
