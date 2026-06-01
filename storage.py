"""수집한 원본 응답을 tests/fixtures/YYYY-MM-DD/{source}_{name}.json 으로 저장.

다음 세션의 분석 로직 개발 및 디버깅에 사용. (.gitignore 처리됨)
"""

import json
import os

_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "tests", "fixtures")


def save_fixture(date_str: str, source: str, name: str, data) -> str:
    """원본 JSON을 fixtures에 저장하고 저장 경로를 반환."""
    day_dir = os.path.join(_FIXTURES_DIR, date_str)
    os.makedirs(day_dir, exist_ok=True)
    path = os.path.join(day_dir, f"{source}_{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return path