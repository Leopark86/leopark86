"""
카카오톡 알림 모듈

'나에게 보내기' 기능을 통해 카카오톡으로 항공권 가격 알림을 전송합니다.
Kakao REST API를 사용하며, 액세스 토큰 자동 갱신을 지원합니다.

준비사항:
  1. https://developers.kakao.com 에서 앱 생성
  2. 카카오 로그인 활성화
  3. setup_kakao.py 실행하여 토큰 발급
"""
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TOKEN_CACHE_PATH = Path(__file__).parent.parent.parent / ".kakao_token_cache.json"

SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


class KakaoNotifier:
    """
    카카오톡 나에게 보내기 알림 전송기

    사용법:
        notifier = KakaoNotifier(rest_api_key, access_token, refresh_token)
        notifier.send_flight_alert(outbound_flights, inbound_flights, threshold)
    """

    def __init__(
        self,
        rest_api_key: str,
        access_token: str,
        refresh_token: Optional[str] = None,
    ):
        self.rest_api_key = rest_api_key
        self.access_token = access_token
        self.refresh_token = refresh_token

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------

    def send_flight_alert(
        self,
        message_lines: list[str],
        search_url: str = "https://flight.naver.com",
    ) -> bool:
        """
        항공권 가격 알림 메시지 전송

        Args:
            message_lines: 알림 본문 줄 목록
            search_url:    네이버 항공 검색 URL

        Returns:
            전송 성공 여부
        """
        text = "\n".join(message_lines)
        template = {
            "object_type": "text",
            "text": text,
            "link": {
                "web_url": search_url,
                "mobile_web_url": search_url,
            },
            "button_title": "항공권 보러가기",
        }
        return self._send(template)

    def send_simple(self, text: str) -> bool:
        """간단한 텍스트 메시지 전송"""
        template = {
            "object_type": "text",
            "text": text,
            "link": {"web_url": "https://flight.naver.com"},
        }
        return self._send(template)

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _send(self, template: dict) -> bool:
        """카카오 API로 메시지 전송 (토큰 만료 시 자동 갱신)"""
        payload = {"template_object": json.dumps(template, ensure_ascii=False)}
        headers = {"Authorization": f"Bearer {self.access_token}"}

        resp = requests.post(SEND_URL, headers=headers, data=payload, timeout=10)

        # 401 = 토큰 만료 → 갱신 후 재시도
        if resp.status_code == 401 and self.refresh_token:
            logger.info("액세스 토큰 만료. 갱신 시도...")
            if self._refresh_access_token():
                headers["Authorization"] = f"Bearer {self.access_token}"
                resp = requests.post(SEND_URL, headers=headers, data=payload, timeout=10)

        if resp.status_code == 200:
            result = resp.json()
            if result.get("result_code") == 0:
                logger.info("카카오톡 알림 전송 성공")
                return True
            logger.error("카카오 API 오류: %s", result)
            return False

        logger.error("카카오 HTTP 오류 %d: %s", resp.status_code, resp.text)
        return False

    def _refresh_access_token(self) -> bool:
        """Refresh Token으로 새 Access Token 발급"""
        if not self.refresh_token:
            logger.error("Refresh Token이 없습니다. setup_kakao.py를 다시 실행하세요.")
            return False

        data = {
            "grant_type": "refresh_token",
            "client_id": self.rest_api_key,
            "refresh_token": self.refresh_token,
        }
        resp = requests.post(TOKEN_URL, data=data, timeout=10)

        if resp.status_code != 200:
            logger.error("토큰 갱신 실패: %s", resp.text)
            return False

        tokens = resp.json()
        self.access_token = tokens["access_token"]
        if "refresh_token" in tokens:
            self.refresh_token = tokens["refresh_token"]

        # .env 파일 및 캐시 업데이트
        self._save_tokens(self.access_token, self.refresh_token)
        logger.info("액세스 토큰 갱신 성공")
        return True

    @staticmethod
    def _save_tokens(access_token: str, refresh_token: Optional[str]) -> None:
        """갱신된 토큰을 .env 및 캐시 파일에 저장"""
        # 캐시 파일에 저장
        cache = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "updated_at": datetime.now().isoformat(),
        }
        try:
            with open(TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("토큰 캐시 저장 실패: %s", exc)

        # .env 파일 업데이트
        env_path = Path(__file__).parent.parent.parent / ".env"
        if env_path.exists():
            _update_env_file(env_path, "KAKAO_ACCESS_TOKEN", access_token)
            if refresh_token:
                _update_env_file(env_path, "KAKAO_REFRESH_TOKEN", refresh_token)


def _update_env_file(env_path: Path, key: str, value: str) -> None:
    """특정 키의 값을 .env 파일에서 업데이트 (없으면 추가)"""
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
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
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception as exc:
        logger.warning(".env 업데이트 실패 (%s): %s", key, exc)
