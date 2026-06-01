"""고위드(Gowid) Open API collector — 카드 지출/식대.

인증: 헤더 Authorization 에 API Key 원문(접두사 없음).
  예) curl ... --header 'Authorization: {API_KEY}'
엔드포인트:
  GET /v1/members   — 카드 사용자(영어이름 매핑)
  GET /v1/expenses  — 지출 내역 (startDate 로 어제 데이터). memo·participants 응답 포함 필수.
  GET /v1/purposes  — 용도(카테고리) 정책 목록
raw 응답은 fixtures에 저장.

단독 실행: python -m collectors.gowid
"""

import sys

import requests

import config
from storage import save_fixture

_TIMEOUT = 30


def _headers() -> dict:
    # 고위드는 Authorization 헤더에 API Key 원문을 그대로 넣는다 (Bearer 등 접두사 없음).
    return {"Authorization": config.GOWID_API_KEY, "Accept": "application/json"}


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{config.GOWID_API_BASE_URL.rstrip('/')}{path}"
    resp = requests.get(url, headers=_headers(), params=params or {}, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def collect(date_str: str | None = None) -> dict:
    """어제(또는 지정일) 고위드 데이터를 수집해 dict로 반환.

    반환: {"date", "members", "expenses", "purposes", "errors": {...}}
    각 endpoint는 독립적으로 호출 — 하나 실패해도 나머지는 수집.
    """
    if date_str is None:
        date_str = config.yesterday_str()

    result: dict = {"date": date_str, "members": [], "expenses": [], "purposes": [], "errors": {}}

    # 1) 카드 사용자
    try:
        members = _get("/v1/members")
        save_fixture(date_str, "gowid", "members_raw", members)
        result["members"] = members
    except Exception as e:
        result["errors"]["members"] = f"{type(e).__name__}: {e}"

    # 2) 지출 내역 (어제) — startDate 로 필터. memo·participants 는 응답에 기본 포함.
    try:
        expenses = _get("/v1/expenses", params={"startDate": date_str})
        save_fixture(date_str, "gowid", "expenses_raw", expenses)
        result["expenses"] = expenses
    except Exception as e:
        result["errors"]["expenses"] = f"{type(e).__name__}: {e}"

    # 3) 용도(카테고리) 정책
    try:
        purposes = _get("/v1/purposes")
        save_fixture(date_str, "gowid", "purposes_raw", purposes)
        result["purposes"] = purposes
    except Exception as e:
        result["errors"]["purposes"] = f"{type(e).__name__}: {e}"

    return result


if __name__ == "__main__":
    if not config.GOWID_API_KEY:
        print("[gowid] GOWID_API_KEY 가 .env에 없습니다.", file=sys.stderr)
        sys.exit(1)
    out = collect()
    import json

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    if out["errors"]:
        print(f"[gowid] 일부 endpoint 실패: {list(out['errors'].keys())}", file=sys.stderr)
        sys.exit(1)
    print(f"[gowid] {out['date']} 수집 완료 "
          f"(members={len(out['members'])}, expenses={len(out['expenses'])}, purposes={len(out['purposes'])})")
