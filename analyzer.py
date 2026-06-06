"""AI 분석 레이어 — 통합 JSON(Phase 1) → 구조화된 분석 결과(JSON).

Claude API에 system 프롬프트 + 분석 룰(prompts/daily_report.md) + 통합 데이터를 보내고,
강제 tool use(submit_daily_analysis)로 엄격한 JSON 구조를 받아온다.

- 분석과 포맷팅 분리: 여기서는 데이터 → 구조화 결과만. 텍스트화는 reporter.py.
- 프롬프트는 prompts/*.md (코드 수정 없이 룰 튜닝). 정적 프롬프트는 prompt caching 적용.
- 직원 마스터(영어이름 37명)를 룰에 주입해 외부 인원 판별.
- 토큰 절약: 분석에 불필요한 bulky/PII 필드는 전송 전 제거.
- 에러 처리: Claude 호출/파싱 실패 시 빈 분석 결과 + error 메시지 반환 (운영 중단 방지).

단독 실행: python -m analyzer < fixtures.json   (통합 JSON을 stdin으로)
"""

import json
import os
import sys

import config
from employees import EMPLOYEES

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_MAX_TOKENS = 8000

# 전송 전 제거할 bulky/개인식별 필드 (분석에 불필요).
_DROP_KEYS = {
    "attMaskedImg", "quitMaskedImg", "userRegImg", "userGradeIcon",
    "userGradeId", "phone", "schTmplInfo",
}

# 강제 tool use 스키마 — 중첩 issue 객체는 유연하게(additionalProperties 허용).
_OBJ_LIST = {"type": "array", "items": {"type": "object", "additionalProperties": True}}
ANALYSIS_TOOL = {
    "name": "submit_daily_analysis",
    "description": "분석 룰에 따라 분류한 일일 경영지원 분석 결과를 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "대상일 YYYY-MM-DD"},
            "summary": {
                "type": "object",
                "properties": {
                    "total_issues": {"type": "integer"},
                    "by_category": {"type": "object", "additionalProperties": True},
                },
                "required": ["total_issues", "by_category"],
            },
            "deposit": {
                "type": "object",
                "properties": {
                    "matched": {"type": "object", "additionalProperties": True},
                    "unmatched": _OBJ_LIST,
                },
            },
            "lunch": {
                "type": "object",
                "properties": {
                    "normal": {"type": "object", "additionalProperties": True},
                    "issues": _OBJ_LIST,
                },
            },
            "non_lunch": {
                "type": "object",
                "properties": {
                    "transport": _OBJ_LIST,
                    "entertainment": _OBJ_LIST,
                    "other": _OBJ_LIST,
                },
            },
            "attendance": {
                "type": "object",
                "properties": {
                    "over_12h": _OBJ_LIST,
                    "under_9h": _OBJ_LIST,
                    "late": _OBJ_LIST,
                    "no_show_no_leave": _OBJ_LIST,
                },
            },
            "leaves": {
                "type": "object",
                "properties": {
                    "yesterday": _OBJ_LIST,
                    "today_planned": _OBJ_LIST,
                    "pending_approval": _OBJ_LIST,
                },
            },
            "attendance_summary": {"type": "object", "additionalProperties": True},
        },
        "required": ["date", "summary", "lunch", "non_lunch", "attendance", "leaves"],
    },
}


def _load_prompt(name: str) -> str:
    with open(os.path.join(_PROMPTS_DIR, name), encoding="utf-8") as f:
        return f.read()


def _prune(obj):
    """bulky/PII 필드를 재귀적으로 제거한 사본을 반환."""
    if isinstance(obj, dict):
        return {k: _prune(v) for k, v in obj.items() if k not in _DROP_KEYS}
    if isinstance(obj, list):
        return [_prune(v) for v in obj]
    return obj


def _empty(date_str: str, error: str) -> dict:
    """분석 실패 시 reporter가 처리할 수 있는 빈 결과 + error."""
    return {
        "date": date_str,
        "error": error,
        "summary": {"total_issues": 0, "by_category": {}},
        "deposit": {"matched": {"count": 0, "total": 0}, "unmatched": []},
        "lunch": {"normal": {"count": 0, "total": 0}, "issues": []},
        "non_lunch": {"transport": [], "entertainment": [], "other": []},
        "attendance": {"over_12h": [], "under_9h": [], "late": [], "no_show_no_leave": []},
        "leaves": {"yesterday": [], "today_planned": [], "pending_approval": []},
        "attendance_summary": {},
    }


def analyze(raw_data: dict) -> dict:
    """통합 JSON을 받아 구조화된 분석 결과 dict를 반환."""
    date_str = raw_data.get("date") or config.yesterday_str()
    today_str = config.now_kst().strftime("%Y-%m-%d")
    daily_dates = raw_data.get("daily_dates") or [date_str]
    period = (daily_dates[0] if len(daily_dates) == 1
              else f"{daily_dates[0]} ~ {daily_dates[-1]} ({len(daily_dates)}일)")

    if anthropic is None:
        return _empty(date_str, "anthropic 패키지 미설치")
    if not config.ANTHROPIC_API_KEY:
        return _empty(date_str, "ANTHROPIC_API_KEY 미설정")

    system_prompt = _load_prompt("system.md")
    rules = _load_prompt("daily_report.md").replace(
        "{employees_list}", ", ".join(EMPLOYEES)
    )
    data_json = json.dumps(_prune(raw_data), ensure_ascii=False, default=str)
    data_msg = (
        f"대상 기간(어제): {period}\n오늘: {today_str}\n"
        f"※ 근태/휴가는 위 기간 전체가 합쳐져 있을 수 있다(월요일=금·토·일). "
        f"점심·식대(lunch) 분류는 코드에서 따로 계산하므로 비워 둬도 된다.\n\n"
        f"## 분석 대상 통합 데이터\n```json\n{data_json}\n```"
    )

    try:
        # max_retries 상향: 일시적 529(Overloaded)/429에 cron이 빈 일보 내지 않도록.
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=5)
        resp = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=_MAX_TOKENS,
            # 정적 프롬프트는 캐싱 (tools → system → 룰 순으로 prefix).
            system=[{"type": "text", "text": system_prompt,
                     "cache_control": {"type": "ephemeral"}}],
            tools=[ANALYSIS_TOOL],
            tool_choice={"type": "tool", "name": "submit_daily_analysis"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": rules,
                 "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": data_msg},
            ]}],
        )
    except Exception as e:  # API 호출 실패 → 빈 결과 (운영 중단 방지)
        print(f"[analyzer] Claude 호출 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return _empty(date_str, f"{type(e).__name__}: {e}")

    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            result = dict(block.input)
            result.setdefault("date", date_str)
            return result

    # tool_use 블록이 없으면 원본 응답을 stderr로 남기고 빈 결과.
    print(f"[analyzer] 응답에 tool_use 없음: {resp.content}", file=sys.stderr)
    return _empty(date_str, "응답에 tool_use 블록 없음")


if __name__ == "__main__":
    try:
        raw = json.load(sys.stdin)
    except Exception as e:
        print(f"[analyzer] stdin JSON 파싱 실패: {e}", file=sys.stderr)
        sys.exit(1)
    out = analyze(raw)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    if out.get("error"):
        sys.exit(1)
