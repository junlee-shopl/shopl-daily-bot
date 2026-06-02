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

### 2. 점심 식대 점검 (gowid.expenses 중 점심식대 카테고리)

기준 한도: 1인당 12,000원

#### 룰 1. 1인 한도 초과
- 조건: participants 길이 == 1 (또는 비어있는데 amount ≤ 12,000)
- 위반: amount > 12,000
- type: "solo_over_limit"

#### 룰 2. 참석자 1인당 한도 초과
- 조건: participants 길이 >= 2
- 위반: (amount / participants 길이) > 12,000
- type: "group_avg_over_limit"
- **반드시 계산해서 확인: (amount / 인원) 이 12,000 이하이면 위반이 아니다. issues에 넣지 말고 normal로 센다.** 예) 33,000 / 3 = 11,000 ≤ 12,000 → 정상.

#### 룰 3. 메모/참석자 누락
- 조건: amount > 12,000 AND **participants가 비어있음(0명)**
- 위반: 12,000원 초과인데 참석자 정보가 없는 경우
- type: "missing_memo"
- **participants에 1명 이상 있으면 memo 텍스트가 비어 있어도 missing_memo가 아니다.** (참석자 명단이 곧 근거)

#### 룰 4. 외부 인원 포함
- 조건: participants 중 직원 마스터(37명)에 없는 이름 존재
- type: "external_included"
- 비고: 점심식대 카테고리에 외부 인원 → 접대비/회식비 분류 검토 대상

#### 룰 5. 중복 점심 의심
- 조건: 같은 날, 한 사람이 **점심식대 카테고리 결제 2건 이상**에 등장
- 등장 기준: (점심식대 결제 건들에 한해) 결제자 본인 + participants 명단의 union
- **교통비 등 점심 외 카테고리는 중복 계산에서 제외한다. 점심식대 결제에 1번만 등장하는 사람은 절대 duplicate_lunch가 아니다.**
- type: "duplicate_lunch"
- 대상자 표시: 중복 등장한 사람 이름

#### 적용 우선순위
- 룰 1과 룰 2는 상호배타 (참석자 수에 따라 하나만)
- 같은 결제에 룰 3~5는 중복 적용 가능
- **이슈로 분류하기 전에 각 룰의 위반 조건을 숫자로 정확히 계산해 확인하라. 조건을 충족하지 않으면 issues에 넣지 말고 normal(정상)로 집계한다.** 애매하면 정상으로 둔다.
- **issues 배열에 넣는 항목은 모두 확정 위반이어야 한다. reason에 '정상', '해당 없음', '해당 안 됨', '제거', '재확인', '경계값' 같은 표현이 들어갈 항목이라면 애초에 issues에 넣지 말고 normal로 처리하라.** reason에는 위반 근거만 한 줄로 적는다.

### 3. 점심 외 카드 사용 (gowid.expenses 중 점심식대 외)

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
