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


_PAGE_SIZE = 100
_MAX_PAGES = 200  # 폭주 방지 가드


def _ymd(date_str: str) -> str:
    return date_str.replace("-", "") if date_str else ""


def _fetch_expenses_range(start_date: str, end_date: str) -> list:
    """[start_date, end_date] 범위의 expenses 를 페이지네이션으로 전부 모은다.

    /v1/expenses 는 startDate 이후 전체를 최신순(내림차순)으로 페이지로 준다
    (endDate 파라미터 없음). 그래서 startDate=start 로 호출해 페이지를 넘기며
    expenseDate 가 start 미만이 되면 멈추고, [start,end] 안의 건만 모은다.
    (이전엔 1페이지만 받아 그날 지출 일부가 누락됐음 — totalPages 90+.)
    """
    start_ymd, end_ymd = _ymd(start_date), _ymd(end_date)
    collected, page = [], 0
    while page < _MAX_PAGES:
        resp = _get("/v1/expenses",
                    params={"startDate": start_date, "page": page, "size": _PAGE_SIZE})
        data = resp.get("data") or {}
        content = data.get("content") if isinstance(data, dict) else data
        content = content or []
        if not content:
            break
        passed_start = False
        for x in content:
            d = x.get("expenseDate")
            if d and d < start_ymd:
                passed_start = True
                continue
            if d and start_ymd <= d <= end_ymd:
                collected.append(x)
        last = isinstance(data, dict) and data.get("last")
        if passed_start or last or len(content) < _PAGE_SIZE:
            break
        page += 1
    return collected


def _fetch_not_submitted() -> list:
    """미제출 지출 백로그 전체 (/v1/expenses/not-submitted). 날짜 필터는 호출측에서."""
    collected, page = [], 0
    while page < _MAX_PAGES:
        resp = _get("/v1/expenses/not-submitted",
                    params={"page": page, "size": _PAGE_SIZE})
        data = resp.get("data") or {}
        content = data.get("content") if isinstance(data, dict) else data
        content = content or []
        collected.extend(content)
        last = isinstance(data, dict) and data.get("last")
        if last or len(content) < _PAGE_SIZE:
            break
        page += 1
    return collected


def collect_range(start_date: str, end_date: str, with_not_submitted: bool = False) -> dict:
    """[start_date, end_date] 범위 고위드 데이터 수집 (범위·페이지네이션 대응).

    with_not_submitted=True 일 때만 미제출 백로그를 조회한다 (주간 점검=월요일 전용).
    반환: {"start","end","members","expenses"(list),"purposes","not_submitted"(list),"errors"}
    expenses 는 원본 응답이 아니라 범위로 필터된 content list 다.
    """
    result: dict = {"start": start_date, "end": end_date, "members": [],
                    "expenses": [], "purposes": [], "not_submitted": [], "errors": {}}

    try:
        result["members"] = _get("/v1/members")
        save_fixture(end_date, "gowid", "members_raw", result["members"])
    except Exception as e:
        result["errors"]["members"] = f"{type(e).__name__}: {e}"

    try:
        result["purposes"] = _get("/v1/purposes")
        save_fixture(end_date, "gowid", "purposes_raw", result["purposes"])
    except Exception as e:
        result["errors"]["purposes"] = f"{type(e).__name__}: {e}"

    try:
        result["expenses"] = _fetch_expenses_range(start_date, end_date)
        save_fixture(end_date, "gowid", "expenses_range", result["expenses"])
    except Exception as e:
        result["errors"]["expenses"] = f"{type(e).__name__}: {e}"

    if with_not_submitted:
        try:
            result["not_submitted"] = _fetch_not_submitted()
            save_fixture(end_date, "gowid", "not_submitted_raw", result["not_submitted"])
        except Exception as e:
            result["errors"]["not_submitted"] = f"{type(e).__name__}: {e}"

    return result


def collect(date_str: str | None = None) -> dict:
    """단일일 수집 (하위호환). 내부적으로 collect_range 사용."""
    if date_str is None:
        date_str = config.yesterday_str()
    r = collect_range(date_str, date_str)
    return {"date": date_str, "members": r["members"], "expenses": r["expenses"],
            "purposes": r["purposes"], "not_submitted": r["not_submitted"],
            "errors": r["errors"]}


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
