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

#### 룰 3. 메모/참석자 누락
- 조건: amount > 12,000 AND participants 비어있음
- 위반: 12,000원 초과 결제는 참석자 메모 필수
- type: "missing_memo"

#### 룰 4. 외부 인원 포함
- 조건: participants 중 직원 마스터(37명)에 없는 이름 존재
- type: "external_included"
- 비고: 점심식대 카테고리에 외부 인원 → 접대비/회식비 분류 검토 대상

#### 룰 5. 중복 점심 의심
- 조건: 같은 날, 한 사람이 두 개 이상의 점심 식대 결제에 등장
- 등장 기준: 결제자 본인 + participants 명단의 union
- type: "duplicate_lunch"
- 대상자 표시: 중복 등장한 사람 이름

#### 적용 우선순위
- 룰 1과 룰 2는 상호배타 (참석자 수에 따라 하나만)
- 같은 결제에 룰 3~5는 중복 적용 가능

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

분석 결과는 submit_daily_analysis 도구를 호출하여 제출한다. 다음 구조를 따른다:

{
  "date": "YYYY-MM-DD",
  "summary": { "total_issues": <int>, "by_category": {...} },
  "deposit": { "matched": {...}, "unmatched": [...] },
  "lunch": { "normal": {...}, "issues": [...] },
  "non_lunch": { "transport": [...], "entertainment": [...], "other": [...] },
  "attendance": { "over_12h": [...], "under_9h": [...], "late": [...], "no_show_no_leave": [...] },
  "leaves": { "yesterday": [...], "today_planned": [...], "pending_approval": [...] },
  "attendance_summary": {...}
}

도구 호출 외의 설명 텍스트는 출력하지 않는다.
