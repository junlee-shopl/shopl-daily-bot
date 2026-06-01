"""샤플(Shopl) Workforce API collector — 근태 + 휴가 + 직원 마스터.

(비용정산은 Shopl API에 엔드포인트가 없어 제외 — 경비/지출은 gowid collector가 커버.)

인증: 헤더 authKey 에 API Key 원문 (64자).
봉투(envelope) 형태가 엔드포인트별로 두 가지:
  - {"header": {"statusCode": "SUCCESS"}, "body": {...}}   (att/report, user/list/v2)
  - {"statusCode": "SUCCESS", "body": [...]}               (leave/usage/list)
둘 다 처리. raw 응답은 fixtures에 저장.

엔드포인트:
  GET /api/att/report?date=YYYY-MM-DD                 — 근태 일보 (출근/퇴근/지각/스케줄)
  GET /api/user/list/v2?includeResignedAfterDate=...  — 직원 목록 (empId ↔ userName 영어이름)
  GET /api/leave/usage/list (date range)              — 휴가 (usedList/tobeList=승인, aprvWaitList=대기)

단독 실행: python -m collectors.shopl
"""

import sys
from datetime import timedelta

import requests

import config
from storage import save_fixture

_TIMEOUT = 30


def _headers() -> dict:
    # 샤플은 커스텀 헤더 authKey 에 API Key 원문을 넣는다 (Bearer 등 접두사 없음).
    return {"authKey": config.SHOPL_API_KEY, "Accept": "application/json"}


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{config.SHOPL_API_BASE_URL.rstrip('/')}{path}"
    resp = requests.get(url, headers=_headers(), params=params or {}, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    # statusCode 는 header 안 또는 최상위에 올 수 있다 (엔드포인트별 봉투 차이).
    status = (data.get("header") or {}).get("statusCode") or data.get("statusCode")
    if status and status != "SUCCESS":
        raise RuntimeError(f"Shopl statusCode={status} ({path})")
    return data


def _body_list(data: dict):
    """봉투에서 리스트 본문을 꺼낸다. body가 {list:[...]} 이거나 [...] 일 수 있음."""
    body = data.get("body")
    if isinstance(body, dict):
        return body.get("list", body)
    return body if body is not None else []


def collect(date_str: str | None = None) -> dict:
    """어제(또는 지정일) 샤플 데이터를 수집해 dict로 반환.

    반환: {"date", "attendance", "users", "leaves", "errors": {...}}
    각 endpoint 독립 호출 — 하나 실패해도 나머지는 수집.
    """
    if date_str is None:
        date_str = config.yesterday_str()

    result: dict = {"date": date_str, "attendance": [], "users": [], "leaves": [], "errors": {}}

    # 1) 근태 일보 — date 파라미터 (YYYY-MM-DD)
    try:
        data = _get("/api/att/report", params={"date": date_str})
        attendance = _body_list(data)
        save_fixture(date_str, "shopl", "attendance_raw", data)
        result["attendance"] = attendance
    except Exception as e:
        result["errors"]["attendance"] = f"{type(e).__name__}: {e}"

    # 2) 직원 목록 — includeResignedAfterDate 로 최근 퇴사자까지 포함(이름↔id 매핑 완전성).
    #    활성 직원은 항상 포함되고, 이 값은 '언제 이후 퇴사자까지 포함할지'만 제어.
    try:
        cutoff = (config.yesterday_kst() - timedelta(days=365)).strftime("%Y-%m-%d")
        data = _get("/api/user/list/v2", params={"includeResignedAfterDate": cutoff})
        users = _body_list(data)
        save_fixture(date_str, "shopl", "users_raw", data)
        result["users"] = users
    except Exception as e:
        result["errors"]["users"] = f"{type(e).__name__}: {e}"

    # 3) 휴가 — 어제 기준. 날짜 파라미터(startDate/endDate)는 라이브 Postman에서 미확인,
    #    합리적 추정값으로 호출 후 raw 저장 → 실제 키 test-run 때 응답 보고 확정.
    #    응답 body[]의 usedList/tobeList=승인, aprvWaitList=승인대기.
    try:
        data = _get("/api/leave/usage/list", params={"startDate": date_str, "endDate": date_str})
        leaves = _body_list(data)
        save_fixture(date_str, "shopl", "leaves_raw", data)
        result["leaves"] = leaves
    except Exception as e:
        result["errors"]["leaves"] = f"{type(e).__name__}: {e}"

    return result


if __name__ == "__main__":
    if not config.SHOPL_API_KEY:
        print("[shopl] SHOPL_API_KEY 가 .env에 없습니다.", file=sys.stderr)
        sys.exit(1)
    out = collect()
    import json

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    if out["errors"]:
        print(f"[shopl] 일부 endpoint 실패: {list(out['errors'].keys())}", file=sys.stderr)
        sys.exit(1)
    print(f"[shopl] {out['date']} 수집 완료 "
          f"(attendance={len(out['attendance'])}, users={len(out['users'])}, leaves={len(out['leaves'])})")
