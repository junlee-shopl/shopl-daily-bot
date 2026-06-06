"""환경변수 로드 + KST 날짜 헬퍼.

.env 파일에서만 비밀 정보를 읽는다 (코드/문서에 박지 않는다).
"""

import os
import sys
from datetime import datetime, timedelta

import pytz
from dotenv import load_dotenv

load_dotenv()

# Windows 콘솔(cp949)에서도 이모지/한글 입출력이 깨지지 않도록 UTF-8 고정.
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

KST = pytz.timezone("Asia/Seoul")

# --- 샤플 API ---
# base URL은 공개 호스트 (비밀 아님). 키만 .env로 관리.
SHOPL_API_BASE_URL = os.getenv("SHOPL_API_BASE_URL", "https://api.shoplworks.com")
SHOPL_API_KEY = os.getenv("SHOPL_API_KEY", "")

# --- 고위드 Open API ---
GOWID_API_BASE_URL = os.getenv("GOWID_API_BASE_URL", "https://openapi.gowid.com")
GOWID_API_KEY = os.getenv("GOWID_API_KEY", "")

# --- 팝빌 (IBK 계좌 조회) ---
POPBILL_LINK_ID = os.getenv("POPBILL_LINK_ID", "")
POPBILL_SECRET_KEY = os.getenv("POPBILL_SECRET_KEY", "")
POPBILL_CORP_NUM = os.getenv("POPBILL_CORP_NUM", "")
POPBILL_BANK_CODE = os.getenv("POPBILL_BANK_CODE", "0003")
POPBILL_ACCOUNT_NUM = os.getenv("POPBILL_ACCOUNT_NUM", "")

# --- Claude / Slack (다음 세션부터 사용) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "")

# --- 운영 ---
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"


def now_kst() -> datetime:
    return datetime.now(KST)


def yesterday_kst() -> datetime:
    """오늘 00:00 KST 기준 하루 전 날짜 (시각은 00:00)."""
    today_midnight = now_kst().replace(hour=0, minute=0, second=0, microsecond=0)
    return today_midnight - timedelta(days=1)


def yesterday_str(fmt: str = "%Y-%m-%d") -> str:
    return yesterday_kst().strftime(fmt)


_KWEEK = ["월", "화", "수", "목", "금", "토", "일"]


def report_plan(today=None) -> dict:
    """오늘(KST) 기준 일보 발송 계획.

    규칙 (2026-06-06 Jun 결정):
    - 토/일은 발송하지 않는다 (skip=True).
    - 월요일 일보는 금·토·일 3일치를 합산해서 본다.
    - 월요일엔 추가로 '주간 점검'(전주 월~일 미제출·중복)을 붙인다.
    - 화~금은 평소대로 어제 하루.

    반환 키:
      skip, weekday, daily_dates(list), is_weekly,
      weekly_start, weekly_end, fetch_start, fetch_end, run_date  (모두 'YYYY-MM-DD')
    """
    today = today or now_kst().date()
    wd = today.weekday()  # 월=0 ... 일=6
    fmt = lambda d: d.strftime("%Y-%m-%d")

    if wd >= 5:  # 토(5)/일(6)
        return {"skip": True, "weekday": wd, "run_date": fmt(today)}

    if wd == 0:  # 월요일 → 금·토·일 + 주간(전주 월~일)
        daily = [today - timedelta(days=n) for n in (3, 2, 1)]
        weekly_start = today - timedelta(days=7)
        weekly_end = today - timedelta(days=1)
        fetch_start, fetch_end = weekly_start, weekly_end
        is_weekly = True
    else:  # 화~금 → 어제 하루
        daily = [today - timedelta(days=1)]
        weekly_start = weekly_end = None
        fetch_start, fetch_end = daily[0], daily[-1]
        is_weekly = False

    return {
        "skip": False,
        "weekday": wd,
        "daily_dates": [fmt(d) for d in daily],
        "is_weekly": is_weekly,
        "weekly_start": fmt(weekly_start) if weekly_start else None,
        "weekly_end": fmt(weekly_end) if weekly_end else None,
        "fetch_start": fmt(fetch_start),
        "fetch_end": fmt(fetch_end),
        "run_date": fmt(today),
    }