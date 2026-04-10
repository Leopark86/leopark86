# ✈ 김포↔제주 항공권 가격 알림

김포(GMP)→제주(CJU) 토요일 출발 / 제주(CJU)→김포(GMP) 월요일 귀환 항공권을 주기적으로 모니터링하여, 설정한 가격 이하이면 **카카오톡** 또는 **텔레그램**으로 알림을 보냅니다.

---

## 프로젝트 구조

```
.
├── main.py                # 메인 진입점 (스케줄러 실행)
├── setup_kakao.py         # 카카오 OAuth 토큰 발급 헬퍼
├── config.yaml            # 사용자 설정 (시간대, 가격 기준 등)
├── .env                   # 환경변수 (토큰 등 민감정보)
├── requirements.txt       # Python 패키지 목록
└── src/
    ├── config.py          # 설정 파일 파싱
    ├── models.py          # Flight, FlightPair 데이터 모델
    ├── scheduler.py       # 가격 모니터 & 알림 로직
    ├── scrapers/
    │   └── naver.py       # 네이버 항공 Playwright 스크래퍼
    └── notifiers/
        ├── kakao.py       # 카카오톡 나에게 보내기
        └── telegram.py    # 텔레그램 봇
```

---

## 빠른 시작

### 1. Python 환경 설정

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium   # 브라우저 설치 (최초 1회)
```

### 2. 환경변수 설정

```bash
cp .env.example .env
```

### 3. 알림 수단 선택

#### 방법 A: 카카오톡 (권장)

1. [카카오 개발자 콘솔](https://developers.kakao.com) 접속
2. **내 애플리케이션 추가** → 앱 이름 입력 (예: `항공권알림`)
3. **카카오 로그인** 활성화
4. **Redirect URI** 에 `http://localhost:5000` 추가
5. **앱 키 → REST API 키** 복사 → `.env`의 `KAKAO_REST_API_KEY` 에 입력
6. 토큰 발급 스크립트 실행:
   ```bash
   python setup_kakao.py
   ```

#### 방법 B: 텔레그램 (간단 대안)

1. 텔레그램에서 **@BotFather** 에게 `/newbot` 명령 → 봇 생성
2. 봇 토큰 복사 → `.env`의 `TELEGRAM_BOT_TOKEN` 에 입력
3. 생성한 봇과 대화 시작 → **@userinfobot** 에게 메시지 보내어 Chat ID 확인
4. `.env`의 `TELEGRAM_CHAT_ID` 에 입력
5. `config.yaml`에서 텔레그램 활성화:
   ```yaml
   notifications:
     telegram:
       enabled: true
   ```

### 4. 조건 설정

`config.yaml` 파일 편집:

```yaml
alert:
  max_price_each: 50000       # 편도 1인 기준 이하이면 알림 (원)
  max_price_round_trip: 90000 # 왕복 합산 이하이면 알림 (원) ← 주요 기준

routes:
  outbound:
    time_range:
      start: "06:00"    # 토요일 출발 시간 범위 시작
      end: "14:00"      # 토요일 출발 시간 범위 끝
  inbound:
    time_range:
      start: "18:00"    # 월요일 도착(기준) 시간 범위 시작
      end: "23:59"      # 월요일 도착 시간 범위 끝
```

### 5. 실행

```bash
# 알림 테스트 (카카오/텔레그램 연결 확인)
python main.py --test

# 즉시 1회 가격 체크
python main.py --once

# 스케줄러 시작 (기본: 60분마다 체크, Ctrl+C로 종료)
python main.py
```

---

## 백그라운드 실행 (Linux/Mac)

```bash
# nohup으로 백그라운드 실행
nohup python main.py > logs/nohup.log 2>&1 &
echo "PID: $!"

# 종료
kill <PID>
```

### cron으로 자동 실행 (시스템 재시작 후에도 유지)

```bash
crontab -e
# 다음 줄 추가 (매 시간 실행):
# 0 * * * * cd /path/to/project && /path/to/venv/bin/python main.py --once >> logs/cron.log 2>&1
```

---

## 설정 상세 설명

| 항목 | 기본값 | 설명 |
|------|--------|------|
| `alert.max_price_each` | 50,000원 | 편도 1인 기준 임계가격 |
| `alert.max_price_round_trip` | 90,000원 | 왕복 합산 임계가격 (우선 적용) |
| `schedule.interval_minutes` | 60분 | 가격 체크 주기 |
| `schedule.weeks_ahead` | 8주 | 몇 주 앞까지 검색 |
| `schedule.check_start_hour` | 7시 | 알림 시작 시간 |
| `schedule.check_end_hour` | 23시 | 알림 종료 시간 |
| `scraper.headless` | true | 브라우저 백그라운드 실행 |

---

## 주의사항

- **네이버 항공** 스크래퍼를 사용하므로 네이버의 이용약관을 준수해야 합니다
- 과도한 요청은 IP 차단의 원인이 될 수 있으므로 체크 주기를 30분 이상으로 설정 권장
- 카카오 액세스 토큰은 6시간마다 자동 갱신됩니다
- 로그는 `logs/flight_alert.log`에 저장됩니다

---

## 문의

이슈는 GitHub Issues에 남겨주세요.
