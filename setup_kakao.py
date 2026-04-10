"""
카카오톡 OAuth 토큰 발급 헬퍼 스크립트

카카오 REST API를 통해 액세스 토큰과 리프레시 토큰을 발급받습니다.
처음 한 번만 실행하면 되며, 이후 토큰은 자동으로 갱신됩니다.

준비사항:
  1. https://developers.kakao.com 접속 → 애플리케이션 추가
  2. [내 애플리케이션] → [앱 키] → REST API 키 복사
  3. [카카오 로그인] 활성화
  4. [카카오 로그인] → [Redirect URI] 에 http://localhost:5000 추가
  5. .env 파일에 KAKAO_REST_API_KEY=<복사한 키> 입력
  6. 이 스크립트 실행: python setup_kakao.py
"""
import os
import sys
import json
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from dotenv import load_dotenv

load_dotenv()

REDIRECT_URI = "http://localhost:5000"
AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
ENV_PATH = Path(__file__).parent / ".env"

received_code: str | None = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """카카오 인증 코드를 수신하는 임시 HTTP 서버 핸들러"""

    def do_GET(self):
        global received_code
        query = parse_qs(urlparse(self.path).query)
        if "code" in query:
            received_code = query["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body>"
                b"<h2>\xec\x9d\xb8\xec\xa6\x9d \xec\x99\x84\xeb\xa3\x8c!</h2>"
                b"<p>\xec\x9d\xb4 \xec\xb0\xbd\xec\x9d\x84 \xeb\x8b\xab\xec\x95\x84\xeb\x8f\x84 \xeb\x90\xa9\xeb\x8b\x88\xeb\x8b\xa4.</p>"
                b"</body></html>"
            )
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # 서버 로그 출력 억제


def get_rest_api_key() -> str:
    key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not key:
        print("\n카카오 REST API 키를 입력하세요")
        print("(https://developers.kakao.com → 내 애플리케이션 → 앱 키 → REST API 키)")
        key = input("REST API 키: ").strip()
    return key


def save_tokens_to_env(access_token: str, refresh_token: str) -> None:
    """토큰을 .env 파일에 저장"""
    def update_or_append(lines, key, value):
        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        return new_lines

    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    else:
        # .env.example 에서 복사
        example = ENV_PATH.parent / ".env.example"
        lines = example.read_text(encoding="utf-8").splitlines() if example.exists() else []

    lines = update_or_append(lines, "KAKAO_ACCESS_TOKEN", access_token)
    lines = update_or_append(lines, "KAKAO_REFRESH_TOKEN", refresh_token)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✅ 토큰이 {ENV_PATH} 에 저장되었습니다.")


def main():
    print("=" * 50)
    print("  카카오톡 OAuth 토큰 발급")
    print("=" * 50)

    rest_api_key = get_rest_api_key()

    # 인증 URL 생성
    params = {
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
    }
    auth_url = f"{AUTH_URL}?{urlencode(params)}"

    print(f"\n1. 브라우저에서 카카오 로그인 페이지를 엽니다...")
    print(f"   URL: {auth_url}\n")
    webbrowser.open(auth_url)

    # 인증 코드 수신 대기 (임시 HTTP 서버)
    print("2. 카카오 로그인 후 자동으로 인증 코드를 수신합니다...")
    server = HTTPServer(("localhost", 5000), OAuthCallbackHandler)
    server.timeout = 120  # 2분 대기
    server.handle_request()

    if not received_code:
        print("\n❌ 인증 코드를 받지 못했습니다. 다시 시도하세요.")
        sys.exit(1)

    print(f"3. 인증 코드 수신 완료. 토큰 발급 중...")

    # 액세스 토큰 요청
    token_data = {
        "grant_type": "authorization_code",
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "code": received_code,
    }
    resp = requests.post(TOKEN_URL, data=token_data, timeout=10)

    if resp.status_code != 200:
        print(f"\n❌ 토큰 발급 실패: {resp.text}")
        sys.exit(1)

    tokens = resp.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    if not access_token:
        print(f"\n❌ 액세스 토큰이 없습니다: {tokens}")
        sys.exit(1)

    print(f"\n✅ 토큰 발급 성공!")
    print(f"   Access Token : {access_token[:20]}...")
    if refresh_token:
        print(f"   Refresh Token: {refresh_token[:20]}...")

    # .env 파일에 저장
    if rest_api_key != os.getenv("KAKAO_REST_API_KEY", ""):
        save_tokens_to_env.__doc__  # dummy
        # REST_API_KEY도 저장
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
        found = any(l.startswith("KAKAO_REST_API_KEY=") for l in lines)
        if not found:
            lines.append(f"KAKAO_REST_API_KEY={rest_api_key}")
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    save_tokens_to_env(access_token, refresh_token or "")

    print("\n📱 테스트 알림을 전송하려면:")
    print("   python main.py --test")
    print("\n🚀 모니터링을 시작하려면:")
    print("   python main.py")


if __name__ == "__main__":
    main()
