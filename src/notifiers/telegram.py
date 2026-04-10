"""
텔레그램 알림 모듈 (카카오톡 대체 수단)

텔레그램 Bot API를 사용하여 항공권 가격 알림을 전송합니다.
카카오톡 설정이 복잡한 경우 텔레그램을 대신 사용할 수 있습니다.

준비사항:
  1. 텔레그램에서 @BotFather 에게 /newbot 명령으로 봇 생성
  2. 봇 토큰 복사 → .env 파일의 TELEGRAM_BOT_TOKEN 에 입력
  3. 봇과 대화 시작 후 @userinfobot 에서 Chat ID 확인
  4. .env 파일의 TELEGRAM_CHAT_ID 에 입력
"""
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """
    텔레그램 봇 알림 전송기

    사용법:
        notifier = TelegramNotifier(bot_token, chat_id)
        notifier.send_flight_alert(message_lines, search_url)
    """

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._api_url = SEND_MESSAGE_URL.format(token=bot_token)

    def send_flight_alert(
        self,
        message_lines: list[str],
        search_url: str = "https://flight.naver.com",
    ) -> bool:
        """
        항공권 가격 알림 메시지 전송

        Args:
            message_lines: 알림 본문 줄 목록
            search_url:    네이버 항공 검색 링크

        Returns:
            전송 성공 여부
        """
        text = "\n".join(message_lines)
        # 링크 버튼 추가 (Markdown v2 방식)
        text += f"\n\n[✈ 항공권 검색하기]({search_url})"
        return self._send(text, parse_mode="Markdown")

    def send_simple(self, text: str) -> bool:
        """간단한 텍스트 메시지 전송"""
        return self._send(text)

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _send(self, text: str, parse_mode: Optional[str] = None) -> bool:
        """텔레그램 Bot API로 메시지 전송"""
        payload: dict = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": False,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            resp = requests.post(self._api_url, json=payload, timeout=10)
            if resp.status_code == 200 and resp.json().get("ok"):
                logger.info("텔레그램 알림 전송 성공")
                return True
            logger.error("텔레그램 API 오류: %s", resp.text)
            return False
        except requests.exceptions.RequestException as exc:
            logger.error("텔레그램 전송 실패: %s", exc)
            return False
