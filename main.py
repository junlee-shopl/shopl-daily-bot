"""경영지원 일일 보고 봇 — 진입점 (Phase 2).

흐름: 어제(KST) 날짜 → 3개 collector 수집 → AI 분석 → 일보 텍스트 → Slack 발송.
각 단계 실패가 전체를 중단시키지 않도록 격리한다.
  - collector 실패 → 가능한 데이터만으로 진행 (collector 내부에서 이미 격리)
  - analyzer 실패 → 빈 분석 결과로 진행 (운영 중단 방지)
  - reporter 실패 → "일보 생성 실패" 메시지 발송
  - slack 발송 실패 → 에러 로그 + 종료 코드 1

DRY_RUN=true 면 발송하지 않고 stdout으로만 일보 출력.
실행: python main.py
"""

import sys

import config
import analyzer
import expense_audit
import reporter
import slack_sender
from collectors import gowid, popbill, shopl


def _safe(name: str, fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"[main] '{name}' 전체 실패: {msg}", file=sys.stderr)
        return {"_error": msg}


def _ymd(d: str) -> str:
    return d.replace("-", "")


def run() -> int:
    plan = config.report_plan()

    # 주말(토/일)은 발송하지 않는다 — 월요일에 금요일치를 본다.
    if plan.get("skip"):
        print(f"[main] {plan['run_date']} 주말 — 일보 미발송", file=sys.stderr)
        return 0

    daily_dates = plan["daily_dates"]
    date_str = daily_dates[-1]
    daily_ymd = {_ymd(d) for d in daily_dates}

    # 1) 데이터 수집 (월요일=금~일 범위, 그 외 어제 하루)
    shopl_data = _safe("shopl", shopl.collect_range, daily_dates)
    gowid_data = _safe("gowid", gowid.collect_range, plan["fetch_start"], plan["fetch_end"],
                       plan.get("is_weekly", False))
    popbill_data = _safe("popbill", popbill.collect_range, plan["fetch_start"], plan["fetch_end"])

    # 고위드 expenses: LLM(점심 외 카드/근태)에는 '일일 범위'만, 식대 코드 점검도 일일 범위.
    all_expenses = gowid_data.get("expenses") or []
    daily_expenses = [e for e in all_expenses if e.get("expenseDate") in daily_ymd]
    purposes = gowid_data.get("purposes") or []

    raw = {
        "date": date_str,
        "daily_dates": daily_dates,
        "shopl": shopl_data,
        "gowid": {"members": gowid_data.get("members"), "purposes": purposes,
                  "expenses": daily_expenses},
        "popbill": popbill_data,
    }

    # 2) AI 분석 (근태/휴가/입금/점심외카드). 점심·식대는 아래에서 코드로 덮어쓴다.
    try:
        analysis = analyzer.analyze(raw)
    except Exception as e:
        print(f"[main] analyzer 실패: {type(e).__name__}: {e}", file=sys.stderr)
        analysis = {"date": date_str, "error": f"{type(e).__name__}: {e}"}

    # 2-1) 식대 점검 — 결정적 코드로 덮어쓰기 (LLM 비결정성 제거).
    try:
        analysis["lunch"] = expense_audit.audit_daily(daily_expenses, purposes, daily_dates)
    except Exception as e:
        print(f"[main] expense_audit(daily) 실패: {type(e).__name__}: {e}", file=sys.stderr)

    # 2-2) 주간 점검(월요일) — 전주 미제출 + 중복사용.
    if plan.get("is_weekly"):
        try:
            analysis["weekly"] = expense_audit.audit_weekly(
                all_expenses, gowid_data.get("not_submitted"), purposes,
                plan["weekly_start"], plan["weekly_end"])
        except Exception as e:
            print(f"[main] expense_audit(weekly) 실패: {type(e).__name__}: {e}", file=sys.stderr)

    analysis["daily_dates"] = daily_dates
    analysis["run_date"] = plan["run_date"]

    # 3) 일보 텍스트 생성 (parent + 섹션별 스레드 본문)
    parent_text, section_texts = None, None
    try:
        parent_text, section_texts = reporter.build(analysis)
    except Exception as e:
        print(f"[main] reporter 실패: {type(e).__name__}: {e}", file=sys.stderr)
        parent_text = (
            f"📋 일일 경영지원 일보 ({date_str})\n\n"
            f"⚠️ 오늘 일보 생성 실패. 로그 확인 필요.\n({type(e).__name__}: {e})"
        )
        section_texts = []

    # 4) 발송 — 메인은 채널에, 섹션 상세는 스레드에 (DRY_RUN이면 stdout 미리보기)
    try:
        slack_sender.send_threaded(parent_text, section_texts)
    except Exception as e:
        print(f"[main] Slack 발송 실패: {e}", file=sys.stderr)
        return 1

    print(f"[main] {date_str} 일보 처리 완료"
          f"{' (DRY_RUN)' if config.DRY_RUN else ''}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(run())
