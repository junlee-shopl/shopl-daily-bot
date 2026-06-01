"""경영지원 일일 보고 봇 — Phase 1 진입점.

어제(KST) 기준으로 3개 collector(shopl/gowid/popbill)를 독립 호출하고,
통합 JSON을 stdout에 출력한다. 한 collector 실패가 전체를 중단시키지 않는다.
각 collector는 원본 응답을 tests/fixtures/YYYY-MM-DD/ 에 저장한다.

실행: python main.py
"""

import json
import sys

import config
from collectors import gowid, popbill, shopl


def _run(name: str, fn, date_str: str) -> dict:
    """collector 하나를 안전하게 실행. 실패 시 {"_error": ...} 반환 (전체 중단 방지)."""
    try:
        return fn(date_str)
    except Exception as e:  # collector 자체가 통째로 실패한 경우
        msg = f"{type(e).__name__}: {e}"
        print(f"[main] collector '{name}' 전체 실패: {msg}", file=sys.stderr)
        return {"_error": msg}


def main() -> int:
    date_str = config.yesterday_str()

    result = {
        "date": date_str,
        "shopl": _run("shopl", shopl.collect, date_str),
        "gowid": _run("gowid", gowid.collect, date_str),
        "popbill": _run("popbill", popbill.collect, date_str),
    }

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    # 실패한 collector가 있으면 stderr에 요약 + non-zero exit (cron 모니터링용).
    failed = [k for k in ("shopl", "gowid", "popbill")
              if result[k].get("_error") or result[k].get("errors")]
    if failed:
        print(f"[main] {date_str} 수집 완료 (일부 이슈: {failed})", file=sys.stderr)
        return 1
    print(f"[main] {date_str} 수집 완료 (전체 정상)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())