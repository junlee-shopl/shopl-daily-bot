# shopl-daily-bot

매일 아침 KST 09:00에 어제 데이터 기준 경영지원 일일 보고를 생성해 Slack에 발송하는 봇.

흐름: **수집(샤플·고위드·팝빌) → AI 분석(Claude) → 일보 텍스트 → Slack 발송**.
Render Cron Job으로 배포된다.

## 필요 환경

- Python 3.11+

## 설치

```bash
pip install -r requirements.txt
```

## 환경변수 설정

`.env.example`을 복사해 `.env`를 만들고 값을 채운다.

```bash
cp .env.example .env
```

| 변수 | 설명 |
|---|---|
| `SHOPL_API_BASE_URL` / `SHOPL_API_KEY` | 샤플 API (인증 헤더 `authKey`) |
| `GOWID_API_BASE_URL` / `GOWID_API_KEY` | 고위드 Open API (인증 헤더 `Authorization`, 키 원문) |
| `POPBILL_LINK_ID` / `POPBILL_SECRET_KEY` / `POPBILL_CORP_NUM` / `POPBILL_BANK_CODE` / `POPBILL_ACCOUNT_NUM` | 팝빌 IBK 계좌 빠른조회 |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | Claude 분석 (기본 `claude-sonnet-4-6`) |
| `SLACK_BOT_TOKEN` / `SLACK_CHANNEL` | Slack 발송 (Bot Token `xoxb-...`, 채널 ID 권장) |
| `DRY_RUN` | `true`면 발송하지 않고 stdout 출력만 |

## 실행

```bash
# 전체 파이프라인 (수집 → 분석 → 발송)
python main.py

# 미리보기 (발송 없이 일보만 stdout)
DRY_RUN=true python main.py

# 모듈 단독 실행 (디버깅)
python -m collectors.shopl          # 샤플 수집
python -m collectors.gowid          # 고위드 수집
python -m collectors.popbill        # 팝빌 수집
python -m analyzer  < raw.json      # 통합 JSON → 분석 결과 JSON
python -m reporter  < analysis.json # 분석 결과 → 일보 텍스트
echo "msg" | python -m slack_sender # Slack 발송/미리보기
```

수집 원본 응답은 `tests/fixtures/YYYY-MM-DD/`에 저장된다 (gitignore 처리됨).

## 일보 포맷 / 분석 룰 수정

코드 수정 없이 `prompts/` 의 두 파일만 고치면 된다:
- `prompts/system.md` — AI 역할 정의
- `prompts/daily_report.md` — 분석 카테고리·룰·출력 스키마 (점심 한도, 외부 인원 판별 등)

텍스트 레이아웃(섹션 순서·표기)은 `reporter.py`에서 조정한다.

## 배포 (Render Cron Job)

`render.yaml`이 Cron Job(매일 KST 09:00 = UTC 00:00)을 정의한다.

1. Render dashboard → New → Blueprint(또는 Cron Job), GitHub repo 연결
2. `render.yaml` 자동 인식
3. `sync: false` 환경변수(키·시크릿)는 dashboard에서 직접 입력
4. 첫 배포 빌드 성공 확인
5. Manual trigger로 1회 실행 → 로그 + Slack 발송 확인

> 보안: `.env`와 실제 키는 commit하지 않는다. `render.yaml`의 비밀값은 모두 `sync: false`.
