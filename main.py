"""
항공권 가격 알림 프로그램 - 메인 진입점

김포↔제주 토요일 출발 / 월요일 귀환 항공권 가격을 주기적으로 모니터링하여
설정한 임계값 이하이면 카카오톡 또는 텔레그램으로 알림을 전송합니다.

사용법:
    python main.py              # 스케줄러 시작 (백그라운드 실행)
    python main.py --test       # 알림 테스트 전송
    python main.py --once       # 즉시 1회 가격 체크 후 종료
    python main.py --config PATH   # 다른 설정 파일 사용
"""
import argparse
import logging
import signal
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import load_config
from src.scheduler import PriceMonitor

# ── 로깅 설정 ─────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "flight_alert.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="김포↔제주 항공권 가격 알림 프로그램",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python main.py                     # 스케줄러 실행 (무한 루프)
  python main.py --test              # 알림 테스트 전송
  python main.py --once              # 1회 즉시 체크
  python main.py --config my.yaml   # 다른 설정 파일 사용
        """,
    )
    parser.add_argument("--test", action="store_true", help="알림 테스트 메시지 전송")
    parser.add_argument("--once", action="store_true", help="1회 가격 체크 후 종료")
    parser.add_argument("--config", type=str, help="설정 파일 경로 (기본: config.yaml)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # 설정 로딩
    try:
        config = load_config(args.config)
        logger.info("설정 파일 로딩 완료")
    except FileNotFoundError as exc:
        logger.error("설정 파일을 찾을 수 없습니다: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.error("설정 파일 오류: %s", exc)
        sys.exit(1)

    monitor = PriceMonitor(config)

    # ── 모드별 실행 ──────────────────────────────────────────────────────────
    if args.test:
        print("\n[테스트] 알림 메시지 전송 중...")
        monitor.test_notification()
        print("테스트 완료. 카카오톡/텔레그램을 확인하세요.")
        return

    if args.once:
        print("\n[1회 체크] 가격 확인 중... (시간 제한 무시)")
        monitor.check_prices(force=True)
        print("완료.")
        return

    # ── 스케줄러 모드 (기본) ─────────────────────────────────────────────────
    interval = config.schedule.interval_minutes
    logger.info(
        "스케줄러 시작: %d분 간격으로 가격 체크 (운영 시간: %d시~%d시)",
        interval,
        config.schedule.check_start_hour,
        config.schedule.check_end_hour,
    )
    logger.info(
        "노선: 김포(%s)→제주(%s) 토요일 %s~%s / 제주(%s)→김포(%s) 월요일 %s~%s",
        config.outbound.from_airport, config.outbound.to_airport,
        config.outbound.time_range.start, config.outbound.time_range.end,
        config.inbound.from_airport, config.inbound.to_airport,
        config.inbound.time_range.start, config.inbound.time_range.end,
    )
    logger.info(
        "알림 기준: 왕복 %s원 이하",
        f"{config.alert.max_price_round_trip:,}",
    )

    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        monitor.check_prices,
        trigger=IntervalTrigger(minutes=interval),
        id="price_check",
        name="항공권 가격 체크",
        max_instances=1,        # 중복 실행 방지
        misfire_grace_time=60,  # 1분 지연까지 허용
    )

    def _shutdown(signum, frame):
        logger.info("종료 신호 수신. 스케줄러 중지 중...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("\n" + "=" * 50)
    print(" 항공권 가격 알림 프로그램 시작")
    print("=" * 50)
    print(f" 체크 간격  : {interval}분마다")
    print(f" 왕복 기준  : {config.alert.max_price_round_trip:,}원 이하")
    print(f" 출발 조건  : 토요일 {config.outbound.time_range.start}~{config.outbound.time_range.end}")
    print(f" 귀환 조건  : 월요일 {config.inbound.time_range.start}~{config.inbound.time_range.end}")
    print(" 종료하려면 Ctrl+C 를 누르세요.")
    print("=" * 50 + "\n")

    # 시작과 동시에 즉시 1회 체크
    monitor.check_prices()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("프로그램 종료")


if __name__ == "__main__":
    main()
