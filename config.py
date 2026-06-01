"""환경변수 로드 + KST 날짜 헬퍼.

.env 파일에서만 비밀 정보를 읽는다 (코드/문서에 박지 않는다).
"""

import os
from datetime import datetime, timedelta

import pytz
from dotenv import load_dotenv

load_dotenv()

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