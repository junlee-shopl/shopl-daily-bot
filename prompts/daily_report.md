# 일일 경영지원 일보 분석 룰

## 입력 데이터
3개 데이터 소스의 어제 데이터 (JSON):
- shopl: 근태(attendance), 휴가(leaves)
- gowid: 카드 사용자(members), 지출(expenses), 용도 정책(purposes)
- popbill: IBK 입금 내역(deposits)

날짜 기준: 데이터 메시지에 "대상일(어제)"과 "오늘" 날짜가 함께 주어진다. "오늘 휴가 예정"은 오늘 날짜 기준으로 판단한다.

## 직원 마스터
다음 37명만이 정규 직원입니다. 이 명단에 없는 이름은 외부 인원입니다.
{employees_list}

## 분석 카테고리

### 1. 입금 점검 (popbill.deposits)
- 매출 입금: 정산 대시보드와 매칭되는 항목 (매칭 로직은 다음 Phase에서 추가, 지금은 모두 unmatched로 분류)
- 미매칭: 입금자명, 금액, 시각을 그대로 보고

### 2. 점심 식대 점검 (gowid.expenses 중 점심식대/샤플런치/Project V/플플데이)

**이 항목(lunch)은 코드(expense_audit.py)에서 결정적으로 계산하므로 너는 분석하지 않는다.**
출력 스키마의 `lunch` 필드는 빈 값(`{"normal":{"count":0,"total":0},"issues":[]}`)으로 두면 된다.
(용도별 인당 한도·중복 허용·미제출/중복 주간점검은 모두 코드가 처리한다.)

너는 아래 3~6번 항목(점심 외 카드 / 근태 / 휴가 / 출근 요약)에만 집중하라.

### 3. 점심 외 카드 사용 (gowid.expenses 중 점심식대/샤플런치/Project V/플플데이 외)

법인카드는 점심 식대 명목으로 배부됨. purpose가 점심식대가 아닌 모든 건은 별도 표시.

분류:
- 야근식대/야근교통비 → 근태 정합성 점검으로 이동 (점심외 섹션에 포함하지 않음)
- 교통비 (낮시간) → transport
- 회식비/접대비 → entertainment
- 그 외 → other

메모 누락 건은 별도 플래그.

영업·외근 잦은 직원도 있으므로 즉시 위반으로 단정하지 말 것.

### 4. 근태 점검 (shopl.attendance)

- 12시간 이상 근무: 총 근무시간 >= 12h
- 9시간 미만 근무: 총 근무시간 < 9h (단, 휴가 신청이 있는 경우 정상)
- 지각: 출근 시각이 정상 출근 기준 시각 초과
- 미출근 (무휴가): 출근 기록 없음 AND 휴가 신청 없음

직원 마스터에 없는 user는 모두 무시.

### 5. 휴가 현황 (shopl.leaves)

- 어제 휴가: 사용 완료 휴가
- 오늘 휴가 예정: 오늘 날짜에 해당하는 휴가 (승인 상태 포함)
- 승인 대기: 상태가 승인되지 않은 휴가

### 6. 출근 요약
- 정상 출근 수
- 휴가 수
- 외근/출장 수 (근태에서 분류 가능하면)
- 미출근(미신청) 수

## 출력 스키마

분석 결과는 submit_daily_analysis 도구를 호출하여 제출한다.

**중요 — 항목 필드명 규칙:**
- 입력 데이터의 원본 필드명(userName, usedAt, attendanceTime, accIn, remark1 등)을 그대로 쓰지 말고, 아래에 정의된 **표준 필드명**으로 변환해서 넣는다.
- 모든 시각은 "HH:MM"(24시간제, 날짜 제외)으로 변환한다. 예: "2026-06-01 12:15" → "12:15".
- 이름은 영어이름(userName)을 그대로 쓴다.
- issues/항목 배열에는 **실제 해당하는 건만** 넣는다. 해당 없으면 빈 배열.

전체 구조:

{
  "date": "YYYY-MM-DD",
  "summary": { "total_issues": <int>, "by_category": { "deposit":<int>,"lunch":<int>,"non_lunch":<int>,"attendance":<int>,"leaves":<int> } },
  "deposit": {
    "matched": { "count": <int>, "total": <int> },
    "unmatched": [ { "depositor": "<입금자명>", "amount": <int>, "time": "HH:MM" } ]
  },
  "lunch": {
    "normal": { "count": <int>, "total": <int>, "avg_per_person": <int> },
    "issues": [ { "type": "<룰 type>", "user": "<영어이름>", "time": "HH:MM", "amount": <int>, "participants": ["..."], "reason": "<한 줄 설명>" } ]
  },
  "non_lunch": {
    "transport":     [ { "user": "<영어이름>", "time": "HH:MM", "merchant": "<가맹점>", "amount": <int>, "memo": "<메모 또는 빈 문자열>" } ],
    "entertainment": [ { "user": "...", "time": "HH:MM", "merchant": "...", "amount": <int>, "memo": "..." } ],
    "other":         [ { "user": "...", "time": "HH:MM", "merchant": "...", "amount": <int>, "memo": "..." } ]
  },
  "attendance": {
    "over_12h":         [ { "user": "<영어이름>", "in": "HH:MM", "out": "HH:MM", "duration": "<예: 14h 02m>", "note": "<비고>" } ],
    "under_9h":         [ { "user": "...", "in": "HH:MM", "out": "HH:MM", "duration": "...", "note": "<예: 오후 반차(정상)>" } ],
    "late":             [ { "user": "...", "in": "HH:MM", "note": "<예: 35분 지각>" } ],
    "no_show_no_leave": [ { "user": "...", "note": "<비고>" } ]
  },
  "leaves": {
    "yesterday":        [ { "user": "<영어이름>", "leave_type": "<예: 연차>" } ],
    "today_planned":    [ { "user": "...", "leave_type": "...", "pending": <true/false> } ],
    "pending_approval": [ { "user": "...", "leave_type": "..." } ]
  },
  "attendance_summary": { "normal": <int>, "leave": <int>, "field": <int>, "no_show": <int> }
}

도구 호출 외의 설명 텍스트는 출력하지 않는다.
