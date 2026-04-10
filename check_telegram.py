"""
텔레그램 봇 설정 진단 스크립트

실행: python check_telegram.py
"""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

print("=" * 50)
print("  텔레그램 설정 진단")
print("=" * 50)

# ── 1. 토큰 존재 여부 ────────────────────────────────
if not TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN 이 .env 파일에 없습니다.")
    sys.exit(1)
print(f"✅ TELEGRAM_BOT_TOKEN: {TOKEN[:10]}...{TOKEN[-5:]}")

if not CHAT_ID:
    print("❌ TELEGRAM_CHAT_ID 가 .env 파일에 없습니다.")
    sys.exit(1)
print(f"✅ TELEGRAM_CHAT_ID: [{CHAT_ID}]  (따옴표/공백 없어야 함)")

# ── 2. 봇 토큰 유효성 확인 ───────────────────────────
print("\n[1단계] 봇 토큰 확인 중...")
resp = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
data = resp.json()
if not data.get("ok"):
    print(f"❌ 봇 토큰이 잘못됐습니다: {data}")
    sys.exit(1)
bot_name = data["result"]["username"]
print(f"✅ 봇 확인 완료: @{bot_name}")

# ── 3. getUpdates 로 실제 chat_id 확인 ───────────────
print("\n[2단계] 대화 기록에서 Chat ID 확인 중...")
resp = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=10)
updates = resp.json().get("result", [])

if not updates:
    print("⚠️  대화 기록이 없습니다.")
    print(f"   → 텔레그램 앱에서 @{bot_name} 을 검색하여 /start 메시지를 보내세요.")
    print("   → 그 후 이 스크립트를 다시 실행하세요.")
    sys.exit(1)

print("발견된 Chat ID 목록:")
seen = set()
for u in updates:
    msg = u.get("message") or u.get("channel_post") or {}
    chat = msg.get("chat", {})
    cid = chat.get("id")
    ctype = chat.get("type", "")
    cname = chat.get("username") or chat.get("title") or chat.get("first_name", "")
    if cid and cid not in seen:
        seen.add(cid)
        match = "← ✅ 현재 설정값과 일치" if str(cid) == CHAT_ID else ""
        print(f"   id={cid}  type={ctype}  name={cname}  {match}")

if not any(str(u.get("message", {}).get("chat", {}).get("id")) == CHAT_ID
           for u in updates if u.get("message")):
    print(f"\n❌ 설정된 TELEGRAM_CHAT_ID={CHAT_ID} 가 위 목록에 없습니다!")
    print("   GitHub Secrets의 TELEGRAM_CHAT_ID 를 위 id 값으로 수정하세요.")
    sys.exit(1)

# ── 4. 실제 메시지 전송 테스트 ───────────────────────
print("\n[3단계] 테스트 메시지 전송 중...")
resp = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    json={"chat_id": CHAT_ID, "text": "✅ 텔레그램 설정 확인 완료! 항공권 알림이 정상 작동합니다."},
    timeout=10,
)
result = resp.json()
if result.get("ok"):
    print("✅ 메시지 전송 성공! 텔레그램을 확인하세요.")
else:
    print(f"❌ 메시지 전송 실패: {result}")
    print(f"   정확한 chat_id: {list(seen)}")
