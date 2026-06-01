"""직원 마스터 — 영어이름만 사용 (사내에서 영어이름만 씀)."""

EMPLOYEES = [
    "Jun", "Ray", "Jay", "Willy", "BB", "Jin", "Kevin", "Bella", "Wade",
    "Danny", "Dawn", "Jerry", "Zed", "Jimmy", "Casper", "Teddy", "Daisy",
    "Stella", "Dana", "Ellin", "Rio", "Velo", "Alina", "Dino", "Ayaan",
    "Karla", "Scott", "Jane", "Tas", "Katie", "Sangun", "Summer", "Leo",
    "Kai", "Jamie", "Lumi", "Aeri",
]


def is_employee(name: str) -> bool:
    """이름이 직원 마스터에 있는지 확인 (외부 인원 식별용)."""
    return name in EMPLOYEES


def total_count() -> int:
    return len(EMPLOYEES)