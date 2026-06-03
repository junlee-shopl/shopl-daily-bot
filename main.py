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
import reporter
import slack_sender
from collectors import gowid, popbill, shopl


def _run_collector(name: str, fn, date_str: str) -> dict:
    try:
        return fn(date_str)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"[main] collector '{name}' 전체 실패: {msg}", file=sys.stderr)
        return {"_error": msg}


def collect_all(date_str: str) -> dict:
    return {
        "date": date_str,
        "shopl": _run_collector("shopl", shopl.collect, date_str),
        "gowid": _run_collector("gowid", gowid.collect, date_str),
        "popbill": _run_collector("popbill", popbill.collect, date_str),
    }


def run() -> int:
    date_str = config.yesterday_str()

    # 1) 데이터 수집
    raw = collect_all(date_str)

    # 2) AI 분석 (실패해도 빈 결과로 진행)
    try:
        analysis = analyzer.analyze(raw)
    except Exception as e:
        print(f"[main] analyzer 실패: {type(e).__name__}: {e}", file=sys.stderr)
        analysis = {"date": date_str, "error": f"{type(e).__name__}: {e}"}

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
