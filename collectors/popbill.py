"""팝빌 계좌조회(빠른조회, EasyFinBank) collector — IBK 기업은행 어제 입금내역.

빠른조회 서비스는 사전에 IBK에 신청/등록되어 있어야 한다 (이미 신청됨).
수집 흐름 (EasyFinBank는 비동기 수집):
  1) requestJob   : 어제 거래내역 수집 작업 요청 → jobID
  2) getJobState  : 작업 완료(jobState==3)까지 폴링
  3) search       : 입금(I)만 조회
입금 = accIn(입금액) > 0. raw 응답은 fixtures에 저장.

단독 실행: python -m collectors.popbill
"""

import sys
import time

import config
from storage import save_fixture

try:
    from popbill import EasyFinBankService, PopbillException
except ImportError:  # pragma: no cover
    EasyFinBankService = None
    PopbillException = Exception


_JOB_DONE = 3  # 팝빌 작업 상태: 3 = 완료
_POLL_TIMEOUT_SEC = 60
_POLL_INTERVAL_SEC = 2


def _service() -> "EasyFinBankService":
    if EasyFinBankService is None:
        raise RuntimeError("popbill 패키지가 설치되지 않았습니다. pip install popbill")
    svc = EasyFinBankService(config.POPBILL_LINK_ID, config.POPBILL_SECRET_KEY)
    svc.IsTest = False
    svc.UseStaticIP = False
    svc.UseLocalTimeYN = True
    return svc


def collect_range(start_date: str, end_date: str) -> dict:
    """[start_date, end_date] 범위 IBK 입금내역 수집 (월요일=금~일 대응)."""
    return collect(start_date, end_date)


def collect(date_str: str | None = None, end_date: str | None = None) -> dict:
    """입금내역을 수집해 dict로 반환.

    date_str: 시작일 'YYYY-MM-DD' (미지정 시 KST 어제).
    end_date: 종료일. 미지정 시 date_str 과 동일(단일일).
    반환: {"date", "deposits": [...], "raw_count", "error"?}
    """
    if date_str is None:
        date_str = config.yesterday_str()
    if end_date is None:
        end_date = date_str
    ymd = date_str.replace("-", "")        # 팝빌 날짜 형식: yyyyMMdd
    ymd_end = end_date.replace("-", "")

    corp = config.POPBILL_CORP_NUM
    bank = config.POPBILL_BANK_CODE
    acct = config.POPBILL_ACCOUNT_NUM

    svc = _service()

    # 1) 수집 작업 요청 (시작~종료 범위)
    job_id = svc.requestJob(corp, bank, acct, ymd, ymd_end)

    # 2) 작업 완료 폴링
    waited = 0
    while waited < _POLL_TIMEOUT_SEC:
        state = svc.getJobState(corp, job_id)
        if int(getattr(state, "jobState", 0)) == _JOB_DONE:
            break
        time.sleep(_POLL_INTERVAL_SEC)
        waited += _POLL_INTERVAL_SEC
    else:
        raise TimeoutError(f"팝빌 수집 작업이 {_POLL_TIMEOUT_SEC}s 내 완료되지 않음 (jobID={job_id})")

    # 3) 입금(I)만 조회 — 페이지네이션
    deposits = []
    page = 1
    per_page = 100
    while True:
        result = svc.search(corp, job_id, ["I"], "", page, per_page, "D")
        rows = getattr(result, "list", []) or []
        for r in rows:
            deposits.append(_row_to_dict(r))
        total = int(getattr(result, "total", len(deposits)))
        if page * per_page >= total or not rows:
            break
        page += 1

    save_fixture(date_str, "popbill", "deposits_raw", deposits)
    return {"date": date_str, "deposits": deposits, "raw_count": len(deposits)}


def _row_to_dict(row) -> dict:
    """팝빌 거래 레코드 객체를 dict로 (raw 보존; 응답 스키마는 fixtures로 확인)."""
    if isinstance(row, dict):
        return row
    return {k: getattr(row, k) for k in vars(row)} if hasattr(row, "__dict__") else {"value": str(row)}


if __name__ == "__main__":
    try:
        out = collect()
        print(f"[popbill] {out['date']} 입금 {out['raw_count']}건 수집 완료")
        import json

        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    except PopbillException as e:  # 팝빌 API 에러
        print(f"[popbill] 팝빌 API 오류: code={getattr(e, 'code', '?')} msg={e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[popbill] 수집 실패: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
