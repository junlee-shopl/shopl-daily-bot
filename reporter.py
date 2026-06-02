"""reporter.py — 분석 결과(JSON) → Slack 발송용 일보 텍스트.

analyzer.py의 구조화 결과만 받아 텍스트로 변환한다 (분석 로직 없음).
포맷을 바꾸고 싶으면 이 파일만 수정.

이슈 객체는 LLM이 채우므로 키가 다소 유동적일 수 있다 → 방어적으로 렌더링한다
(없는 키는 건너뛰고, 절대 예외로 죽지 않는다).

단독 실행: python -m reporter < analysis.json
"""

import json
import re
import sys
from datetime import datetime, timedelta

import config

_DIV = "━" * 27
_KWEEK = ["월", "화", "수", "목", "금", "토", "일"]


# ---------- 포맷 헬퍼 ----------

def _won(v) -> str:
    """금액 → '12,000원'. 숫자가 아니면 원본 문자열."""
    try:
        return f"{int(round(float(v))):,}원"
    except (TypeError, ValueError):
        return f"{v}원" if v not in (None, "") else "-"


def _amount(item: dict):
    """항목에서 금액 값을 찾는다 (정규 amount 또는 원본 accIn 등)."""
    for k in ("amount", "accIn", "금액"):
        v = item.get(k) if isinstance(item, dict) else None
        if v not in (None, ""):
            return v
    return None


def _hhmm(item: dict, *keys) -> str:
    """시각 문자열에서 HH:MM만 추출 ('2026-06-01 12:15' → '12:15')."""
    for k in keys:
        v = item.get(k) if isinstance(item, dict) else None
        if v:
            m = re.search(r"(\d{1,2}:\d{2})", str(v))
            return m.group(1) if m else str(v)
    return ""


def _kdate(date_str: str) -> str:
    """'2026-05-28' → '5월 28일 (목)'."""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return f"{d.month}월 {d.day}일 ({_KWEEK[d.weekday()]})"
    except (TypeError, ValueError):
        return date_str or "-"


def _g(item: dict, *keys, default="") -> str:
    """item에서 keys 중 처음 존재하는 값을 문자열로."""
    for k in keys:
        if isinstance(item, dict) and item.get(k) not in (None, ""):
            return str(item[k])
    return default


def _participants(item: dict) -> str:
    p = item.get("participants")
    if isinstance(p, list) and p:
        return ", ".join(str(x) for x in p)
    if isinstance(p, str):
        return p
    return ""


def _len(x) -> int:
    return len(x) if isinstance(x, list) else 0


# 안전망: 모델이 비위반 건을 issues에 넣고 reason에 "정상/위반 아님" 등으로
# 자가정정하는 경우가 있어, 이런 단서가 든 항목은 issue에서 제외한다.
_NON_VIOLATION_MARKERS = (
    "위반 아님", "위반아님", "해당 없음", "해당없음", "해당 안", "미해당",
    "정상", "제거", "재확인", "경계값", "대상 외", "대상외", "아닙니다", "아님",
)


def _is_real_issue(it: dict) -> bool:
    reason = str(it.get("reason", "")) if isinstance(it, dict) else ""
    return not any(m in reason for m in _NON_VIOLATION_MARKERS)


def _filter_issues(analysis: dict) -> dict:
    """lunch.issues에서 비위반(자가정정) 항목 제거. 원본 보존 위해 얕은 복사."""
    lunch = dict(analysis.get("lunch") or {})
    issues = [it for it in (lunch.get("issues") or []) if _is_real_issue(it)]
    lunch["issues"] = issues
    a = dict(analysis)
    a["lunch"] = lunch
    return a


# ---------- 섹션 빌더 ----------

def _deposit_section(dep: dict) -> list:
    lines = [_DIV, "💰 입금 점검", _DIV]
    matched = dep.get("matched") or {}
    m_cnt = matched.get("count", 0)
    m_total = matched.get("total", 0)
    unmatched = dep.get("unmatched") or []
    lines.append(f"✅ 매출 입금 {m_cnt}건 / {_won(m_total)}")
    if unmatched:
        lines.append(f"⚠️ 미매칭 {len(unmatched)}건")
        for it in unmatched:
            name = _g(it, "depositor", "remark1", "remark", "name", "입금자명",
                      default="(이름없음)")
            amt = _won(_amount(it))
            t = _hhmm(it, "time", "시각")
            lines.append(f"  · {name} / {amt}" + (f" / {t}" if t else ""))
    else:
        lines.append("✅ 미매칭 없음")
    return lines


def _lunch_section(lunch: dict) -> list:
    lines = [_DIV, "🍱 점심 식대 점검", _DIV]
    normal = lunch.get("normal") or {}
    n_cnt = normal.get("count", 0)
    n_total = normal.get("total", 0)
    extra = ""
    if normal.get("avg_per_person") not in (None, ""):
        extra = f" (1인당 평균 {_won(normal['avg_per_person'])})"
    lines.append(f"✅ 정상 사용: {n_cnt}건 / {_won(n_total)}{extra}")

    issues = lunch.get("issues") or []
    if not issues:
        lines.append("✅ 점검 필요 없음")
        return lines

    lines.append(f"⚠️ 점검 필요 {len(issues)}건")
    labels = {
        "solo_over_limit": "1인 한도 초과",
        "group_avg_over_limit": "참석자 한도 초과",
        "external_included": "외부 인원 포함",
        "duplicate_lunch": "중복 점심 의심",
        "missing_memo": "메모 누락",
    }
    # 타입별 그룹화 (정의된 순서 유지)
    by_type = {}
    for it in issues:
        by_type.setdefault(it.get("type", "기타"), []).append(it)
    order = list(labels.keys()) + [t for t in by_type if t not in labels]
    for t in order:
        group = by_type.get(t)
        if not group:
            continue
        lines.append("")
        lines.append(f"  [{labels.get(t, t)}]")
        for it in group:
            user = _g(it, "user", "userName", "payer", "결제자", default="(미상)")
            t_str = _hhmm(it, "time", "usedAt", "시각")
            amt = _won(_amount(it))
            parts = _participants(it)
            head = f"  · {user}".ljust(10) + f"{t_str}  {amt}"
            if parts:
                head += f" (참석자: {parts})"
            lines.append(head)
            reason = _g(it, "reason", "note", "비고")
            if reason:
                lines.append(f"    → {reason}")
    return lines


def _non_lunch_section(nl: dict) -> list:
    lines = [_DIV, "💳 점심 외 카드 사용", _DIV,
             "법인카드는 점심 식대 명목으로 배부됨. 점심 외 사용은 검토 대상."]
    buckets = [("transport", "교통비 / 낮시간"),
               ("entertainment", "회식·접대"),
               ("other", "기타 / 미분류")]
    total = sum(_len(nl.get(k)) for k, _ in buckets)
    total_amt = 0
    for k, _ in buckets:
        for it in (nl.get(k) or []):
            try:
                total_amt += int(round(float(_amount(it))))
            except (TypeError, ValueError):
                pass
    if total == 0:
        lines.append("✅ 점심 외 사용 없음")
        return lines
    lines.append(f"총 {total}건 / {_won(total_amt)}")
    for k, label in buckets:
        rows = nl.get(k) or []
        if not rows:
            continue
        lines.append("")
        lines.append(f"  [{label}] {len(rows)}건")
        for it in rows:
            user = _g(it, "user", "userName", "결제자", default="(미상)")
            t_str = _hhmm(it, "time", "usedAt", "시각")
            merch = _g(it, "merchant", "store", "가맹점")
            amt = _won(_amount(it))
            memo = _g(it, "memo", "메모")
            row = f"  · {user}".ljust(10) + f"{t_str}  {merch}  {amt}"
            row += f'  "{memo}"' if memo else "  메모 없음 ⚠️"
            lines.append(row)
    return lines


def _attendance_section(att: dict) -> list:
    lines = [_DIV, "⏰ 근태 점검", _DIV]
    blocks = [("over_12h", "12시간 이상 근무"),
              ("under_9h", "9시간 미만 근무"),
              ("late", "지각"),
              ("no_show_no_leave", "미출근 (무휴가)")]
    any_row = False
    for k, label in blocks:
        rows = att.get(k) or []
        lines.append(f"[{label}] {len(rows)}명")
        for it in rows:
            any_row = True
            user = _g(it, "user", "userName", "name", default="(미상)")
            t_in = _hhmm(it, "in", "attendanceTime", "출근")
            t_out = _hhmm(it, "out", "quittingTime", "퇴근")
            dur = _g(it, "duration", "worked", "근무시간")
            note = _g(it, "note", "비고", "reason")
            line = f"• {user}".ljust(10)
            if t_in and t_out:
                line += f"{t_in} → {t_out}"
            elif t_in:
                line += t_in
            elif t_out:
                line += f"→ {t_out}"
            if dur:
                line += f" ({dur})"
            if note:
                line += f" · {note}"
            lines.append(line)
    if not any_row:
        lines.append("✅ 근태 이상 없음")
    return lines


def _leaves_section(lv: dict) -> list:
    lines = [_DIV, "🏖️ 휴가 현황", _DIV]

    def _fmt(rows):
        out = []
        for it in (rows or []):
            user = _g(it, "user", "userName", "name", default="(미상)")
            kind = _g(it, "leave_type", "leaveTypeName", "type", "종류")
            tag = " ⚠️ 승인 대기" if it.get("pending") else ""
            out.append(f"{user} {kind}{tag}".strip())
        return " · ".join(out) if out else "없음"

    lines.append(f"[어제] {_fmt(lv.get('yesterday'))}")
    lines.append(f"[오늘] {_fmt(lv.get('today_planned'))}")
    pending = lv.get("pending_approval") or []
    if pending:
        lines.append(f"[승인 대기] {_fmt(pending)}")
    return lines


def _summary_section(att_sum: dict) -> list:
    lines = [_DIV, "📊 출근 요약", _DIV]
    normal = att_sum.get("normal", 0)
    leave = att_sum.get("leave", 0)
    field = att_sum.get("field", 0)
    no_show = att_sum.get("no_show", 0)
    lines.append(f"정상 {normal} · 휴가 {leave} · 외근/출장 {field} · 미출근(미신청) {no_show}")
    return lines


# ---------- 메인 ----------

def _issue_counts(analysis: dict) -> dict:
    dep = analysis.get("deposit") or {}
    lunch = analysis.get("lunch") or {}
    att = analysis.get("attendance") or {}
    lv = analysis.get("leaves") or {}
    return {
        "입금": _len(dep.get("unmatched")),
        "식대": _len(lunch.get("issues")),
        "근태": _len(att.get("late")) + _len(att.get("no_show_no_leave")),
        "휴가": _len(lv.get("pending_approval")),
    }


def generate(analysis: dict) -> str:
    """분석 결과 dict → 일보 텍스트."""
    analysis = _filter_issues(analysis)
    target_date = analysis.get("date") or config.yesterday_str()
    try:
        report_d = datetime.strptime(target_date[:10], "%Y-%m-%d") + timedelta(days=1)
        report_date_str = report_d.strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        report_date_str = target_date

    head = [
        f"📋 일일 경영지원 일보 — {report_date_str[:4]}년 {_kdate(report_date_str)}",
        f"대상 기간: {_kdate(target_date)}",
        "",
    ]
    if analysis.get("error"):
        head.append(f"⚠️ 분석 일부 제한: {analysis['error']}")
        head.append("")

    counts = _issue_counts(analysis)
    total = sum(counts.values())
    if total == 0:
        head.append("✅ 오늘 점검 사항 없음. 정상 운영 중")
    else:
        brk = " · ".join(f"{k} {v}" for k, v in counts.items())
        head.append(f"⚠️ 오늘 점검 필요 {total}건 — {brk}")

    sections = (
        _deposit_section(analysis.get("deposit") or {})
        + [""] + _lunch_section(analysis.get("lunch") or {})
        + [""] + _non_lunch_section(analysis.get("non_lunch") or {})
        + [""] + _attendance_section(analysis.get("attendance") or {})
        + [""] + _leaves_section(analysis.get("leaves") or {})
        + [""] + _summary_section(analysis.get("attendance_summary") or {})
    )
    return "\n".join(head + [""] + sections)


if __name__ == "__main__":
    try:
        data = json.load(sys.stdin)
    except Exception as e:
        print(f"[reporter] stdin JSON 파싱 실패: {e}", file=sys.stderr)
        sys.exit(1)
    print(generate(data))
