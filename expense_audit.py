"""expense_audit.py — 식대/카드 한도 점검을 '코드로' 결정적으로 계산.

기존엔 점심·식대 분류를 LLM(analyzer)이 매 실행마다 판단해 결과가 흔들렸다
(같은 데이터인데 실행마다 식대 1건/0건). 이 모듈은 Gowid expenses + purposes 를
받아 룰을 숫자로 계산하므로 실행마다 동일한 결과가 나온다.

핵심 룰 (Jun + Stella 합의, 2026-06-06):
- 용도별 인당 한도는 Gowid purposes 의 limitAmount 를 그대로 쓴다 (하드코딩 금지).
    점심식비 12,000 / 샤플런치 30,000 / Project V 50,000 / 플플데이 50,000 ...
- 샤플런치·Project V·플플데이: 한 사람이 하루 여러 건 결제 허용(중복 아님).
    대신 '사용자별 하루 합계'가 인당 한도를 넘으면 위반. (참석자 균등배분)
- 점심식비: 결제 1건 단위로 (금액 / 참석자수) > 한도 면 위반.
- 외부 인원(직원 마스터 밖) 참석 → 별도 표시.
- 일일 검증: 한도초과 / 외부인원 / 메모미입력 후 제출.
- 주간 검증(매주 월요일, 전주 월~일): 미제출 + 중복사용.

날짜 포맷: expenses 의 expenseDate 는 'YYYYMMDD'. 입력 date_str 은 'YYYY-MM-DD'.
"""

from employees import is_employee

# 중복(한 사람이 같은 용도로 하루 여러 건) 이 허용되는 용도 — 합계만 한도 비교.
EXEMPT_DUP_PURPOSES = {"샤플런치", "Project V", "플플데이"}
# 매일 식대 한도/메모를 점검하는 점심 성격 용도.
LUNCH_PURPOSE = "점심식비"
# 일일 식대 점검 대상 용도 = 점심식비 + 특수 3종.
AUDITED_PURPOSES = {LUNCH_PURPOSE} | EXEMPT_DUP_PURPOSES

# 제출 완료로 간주하는 상태 (NOT_SUBMITTED = 미제출).
_SUBMITTED = {"APPROVED", "SUBMITTED"}


# ---------- 헬퍼 ----------

def _ymd(date_str: str) -> str:
    """'2026-06-05' → '20260605'. 이미 YYYYMMDD 면 그대로."""
    return date_str.replace("-", "") if date_str else ""


def _hhmm(t) -> str:
    """'122717' → '12:27'."""
    s = str(t or "")
    return f"{s[:2]}:{s[2:4]}" if len(s) >= 4 else s


def _purpose_name(exp: dict) -> str:
    p = exp.get("purpose")
    return (p or {}).get("name", "") if isinstance(p, dict) else ""


def _amount(exp: dict) -> float:
    for k in ("krwAmount", "approvedAmount", "useAmount"):
        v = exp.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


def _participant_names(exp: dict) -> list:
    out = []
    for p in (exp.get("participants") or []):
        name = p.get("userName") if isinstance(p, dict) else str(p)
        if name:
            out.append(name)
    return out


def _is_submitted(exp: dict) -> bool:
    return str(exp.get("approvalStatus", "")).upper() in _SUBMITTED


def limit_map(purposes: list) -> dict:
    """purposes 응답 → {용도이름: 인당 한도(limitAmount)}. PERSON 한도만."""
    data = purposes.get("data") if isinstance(purposes, dict) else purposes
    out = {}
    for p in (data or []):
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if name and p.get("limitType") == "PERSON":
            try:
                out[name] = float(p.get("limitAmount") or 0)
            except (TypeError, ValueError):
                out[name] = 0.0
    return out


def _expenses_list(gowid_expenses) -> list:
    """collect 결과의 expenses(원본 응답 또는 list) → content list."""
    if isinstance(gowid_expenses, dict):
        data = gowid_expenses.get("data")
        if isinstance(data, dict):
            return data.get("content") or []
        if isinstance(data, list):
            return data
        return []
    return gowid_expenses or []


# ---------- 일일 식대 점검 ----------

def audit_daily(gowid_expenses, purposes, daily_dates: list) -> dict:
    """일일 식대 점검 → reporter 가 쓰는 lunch 구조.

    반환:
      {
        "normal": {"count", "total", "avg_per_person"},   # 점심식비 정상 건
        "by_purpose": {용도: {"count", "total"}},          # 특수 용도 사용 요약
        "issues": [ {type, user, purpose, time, amount, participants, reason} ]
      }
    """
    limits = limit_map(purposes)
    day_set = {_ymd(d) for d in daily_dates}
    exps = [e for e in _expenses_list(gowid_expenses)
            if e.get("expenseDate") in day_set
            and _purpose_name(e) in AUDITED_PURPOSES
            and _is_submitted(e)]

    issues = []
    normal_count = 0
    normal_total = 0.0
    normal_people = 0
    by_purpose = {}

    # 1) 점심식비 — 결제 단위 점검.
    for e in [x for x in exps if _purpose_name(x) == LUNCH_PURPOSE]:
        amt = _amount(e)
        limit = limits.get(LUNCH_PURPOSE, 12000)
        cnt = int(e.get("participantCount") or 0)
        names = _participant_names(e)
        memo = e.get("memo")
        user = e.get("cardUserName") or "(미상)"
        time = _hhmm(e.get("expenseTime"))
        externals = [n for n in names if not is_employee(n)]

        if cnt == 0:
            # 참석자/메모 없는데 1인 한도 초과 → 근거 없는 초과 = 메모미입력 후 제출.
            if amt > limit and not memo:
                issues.append({"type": "missing_memo", "user": user,
                               "purpose": LUNCH_PURPOSE, "time": time, "amount": amt,
                               "reason": f"{int(limit):,}원 초과인데 참석자/메모 없음"})
            else:
                normal_count += 1
                normal_total += amt
                normal_people += 1
            continue

        per = amt / cnt
        flagged = False
        if externals:
            issues.append({"type": "external_included", "user": user,
                           "purpose": LUNCH_PURPOSE, "time": time, "amount": amt,
                           "participants": names,
                           "reason": f"외부 인원 포함: {', '.join(externals)}"})
            flagged = True
        if per > limit:
            issues.append({"type": "over_limit", "user": user,
                           "purpose": LUNCH_PURPOSE, "time": time, "amount": amt,
                           "participants": names,
                           "reason": f"1인당 {int(round(per)):,}원 > 한도 {int(limit):,}원 "
                                     f"({int(amt):,}/{cnt}명)"})
            flagged = True
        if not flagged:
            normal_count += 1
            normal_total += amt
            normal_people += cnt

    # 2) 특수 용도(샤플런치 등) — 사용자별 '하루 합계'로 한도 점검 (중복 허용).
    for purpose in EXEMPT_DUP_PURPOSES:
        rows = [x for x in exps if _purpose_name(x) == purpose]
        if not rows:
            continue
        limit = limits.get(purpose, 0)
        total = sum(_amount(r) for r in rows)
        by_purpose[purpose] = {"count": len(rows), "total": total, "limit": limit}

        # 사용자별 일 합계 (참석자 균등배분). 날짜별로 한도가 적용되므로 (용도,날짜,사용자) 키.
        alloc = {}
        for r in rows:
            amt = _amount(r)
            names = _participant_names(r)
            d = r.get("expenseDate")
            if not names:  # 참석자 미기재 → 결제자 본인에게 전액
                names = [r.get("cardUserName") or "(미상)"]
            share = amt / len(names)
            for n in names:
                alloc.setdefault((d, n), 0.0)
                alloc[(d, n)] += share
                if not is_employee(n):
                    # 외부 인원은 한도 무관하게 표시 (중복 1회만)
                    pass
        for (d, n), used in alloc.items():
            if limit and used > limit:
                issues.append({"type": "over_limit", "user": n, "purpose": purpose,
                               "time": "", "amount": used,
                               "reason": f"{purpose} {_kdate_short(d)} 합계 "
                                         f"{int(round(used)):,}원 > 인당 한도 {int(limit):,}원"})

    avg = int(round(normal_total / normal_people)) if normal_people else 0
    return {
        "normal": {"count": normal_count, "total": normal_total, "avg_per_person": avg},
        "by_purpose": by_purpose,
        "issues": issues,
    }


def _kdate_short(ymd: str) -> str:
    """'20260605' → '6/5'."""
    s = str(ymd or "")
    return f"{int(s[4:6])}/{int(s[6:8])}" if len(s) == 8 else s


# ---------- 주간 점검 (월요일, 전주 월~일) ----------

def audit_weekly(gowid_expenses, not_submitted, purposes,
                 week_start: str, week_end: str) -> dict:
    """전주(월~일) 미제출 + 중복사용 점검.

    - 미제출: /v1/expenses/not-submitted 결과(없으면 expenses의 NOT_SUBMITTED) 중
      expenseDate 가 전주 범위인 건.
    - 중복사용: 특수 3종(중복 허용) 제외한 용도에서, 같은 사람이 같은 날 같은 용도로
      2건 이상 결제한 경우.

    반환: {"not_submitted": [...], "duplicates": [...], "range": "6/1~6/7"}
    """
    start, end = _ymd(week_start), _ymd(week_end)

    def _in_week(e):
        d = e.get("expenseDate")
        return d and start <= d <= end

    # 1) 미제출
    ns_src = _expenses_list(not_submitted) if not_submitted else []
    if not ns_src:
        ns_src = [e for e in _expenses_list(gowid_expenses)
                  if not _is_submitted(e)]
    ns_rows = []
    for e in ns_src:
        if not _in_week(e):
            continue
        ns_rows.append({
            "user": e.get("cardUserName") or "(미상)",
            "date": _kdate_short(e.get("expenseDate")),
            "amount": _amount(e),
            "store": e.get("storeName") or "",
        })

    # 2) 중복사용 — 특수 3종 제외.
    seen = {}  # (date, user, purpose) -> [amount...]
    for e in _expenses_list(gowid_expenses):
        if not _in_week(e) or not _is_submitted(e):
            continue
        purpose = _purpose_name(e)
        if not purpose or purpose in EXEMPT_DUP_PURPOSES:
            continue
        user = e.get("cardUserName") or "(미상)"
        key = (e.get("expenseDate"), user, purpose)
        seen.setdefault(key, []).append(_amount(e))
    dup_rows = []
    for (d, user, purpose), amts in seen.items():
        if len(amts) >= 2:
            dup_rows.append({
                "user": user, "date": _kdate_short(d), "purpose": purpose,
                "count": len(amts), "amounts": amts,
            })
    dup_rows.sort(key=lambda r: (r["date"], r["user"]))

    return {
        "not_submitted": ns_rows,
        "duplicates": dup_rows,
        "range": f"{_kdate_short(start)}~{_kdate_short(end)}",
    }
