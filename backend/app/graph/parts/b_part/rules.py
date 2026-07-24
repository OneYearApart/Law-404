"""
B파트 Rule Engine.

이 파일은 GPT가 직접 계산하면 실수할 수 있는 날짜/금액 계산을
Python 코드로 처리하기 위한 B파트 전용 규칙 모듈입니다.

현재 지원 기능:
1. 계약갱신요구권 행사 기간 계산
2. 월세 인상률 및 5% 초과 여부 계산
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any

RENEWAL_CATEGORIES = {"계약갱신", "계약갱신요구권"}
RENT_INCREASE_CATEGORIES = {"차임증감"}


def normalize_year(year_text: str) -> int:
    """
    2자리/4자리 연도를 4자리 연도로 정규화합니다.

    2자리 연도는 00~69를 2000년대, 70~99를 1900년대로 해석합니다.
    예:
        26 -> 2026
        2026 -> 2026
    """
    year = int(year_text)
    if len(year_text) == 2:
        return 2000 + year if year <= 69 else 1900 + year
    return year


def subtract_months(base_date: date, months: int) -> date:
    """
    기준 날짜에서 months개월을 뺍니다.

    예:
        2027-03-01에서 6개월 전 -> 2026-09-01

    주의:
        월마다 마지막 날짜가 다르기 때문에 단순히 30일 * 개월 수로 빼면 안 됩니다.
        예를 들어 3월 31일에서 1개월 전은 2월 31일이 없으므로 2월 말일로 보정합니다.
    """
    month_index = base_date.month - months
    year = base_date.year

    while month_index <= 0:
        month_index += 12
        year -= 1

    last_day = calendar.monthrange(year, month_index)[1]
    day = min(base_date.day, last_day)

    return date(year, month_index, day)


def parse_date_from_text(text: str) -> date | None:
    """
    사용자 질문에서 날짜를 추출합니다.

    지원하는 형식:
    - 2027-03-01
    - 27-03-01
    - 2027.03.01
    - 27.03.01
    - 2027/03/01
    - 27/03/01
    - 2027년 3월 1일
    - 27년 3월 1일
    """
    patterns = [
        r"(?P<year>\d{2,4})[-./](?P<month>\d{1,2})[-./](?P<day>\d{1,2})",
        r"(?P<year>\d{2,4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue

        year = normalize_year(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))

        try:
            return date(year, month, day)
        except ValueError:
            return None

    return None


def parse_year_month_from_text(text: str) -> tuple[int, int] | None:
    """
    사용자 질문에서 연도와 월만 추출합니다.

    지원하는 형식:
    - 2026년 9월
    - 26년 9월
    - 2026-09
    - 26.09

    일자까지 있는 완전한 날짜는 parse_date_from_text()가 담당합니다.
    이 함수는 "2026년 9월입니다"처럼 날짜 계산에 필요한 일자가 빠진 상태를
    별도로 감지하기 위해 사용합니다.
    """
    patterns = [
        r"(?P<year>\d{2,4})년\s*(?P<month>\d{1,2})월(?!\s*\d{1,2}\s*일)",
        r"(?P<year>\d{2,4})[-./](?P<month>\d{1,2})(?![-./]\d{1,2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue

        year = normalize_year(match.group("year"))
        month = int(match.group("month"))
        if 1 <= month <= 12:
            return year, month

    return None


def parse_day_from_text(text: str) -> int | None:
    """
    사용자 답변에서 일자만 추출합니다.

    예:
    - 10일
    - 10일입니다
    """
    match = re.search(r"(?P<day>\d{1,2})\s*일", text)
    if not match:
        return None

    day = int(match.group("day"))
    if 1 <= day <= 31:
        return day
    return None


def has_date_in_text(text: str) -> bool:
    """사용자 입력에 실제 날짜가 포함되어 있는지 확인합니다."""
    return parse_date_from_text(text) is not None


def calculate_renewal_request_period(contract_end_date: date) -> dict[str, Any]:
    """
    계약갱신요구권 행사 가능 기간을 계산합니다.

    주택임대차 계약갱신요구권은 일반적으로 계약 종료 6개월 전부터
    계약 종료 2개월 전까지 행사해야 합니다.
    """
    start_date = subtract_months(contract_end_date, 6)
    deadline = subtract_months(contract_end_date, 2)

    return {
        "rule_name": "계약갱신요구권 행사 기간 계산",
        "rule_type": "renewal_request_period",
        "contract_end_date": contract_end_date.isoformat(),
        "renewal_request_start_date": start_date.isoformat(),
        "renewal_request_deadline": deadline.isoformat(),
        "explanation": "계약갱신요구권은 일반적으로 계약 종료 6개월 전부터 2개월 전까지 행사해야 합니다.",
    }


def parse_money_values_from_text(text: str) -> list[int]:
    """
    사용자 질문에서 원 단위 금액을 추출합니다.

    우선 지원하는 표현:
    - 50만 원
    - 50만원
    - 600000원
    - 600,000원

    반환값:
        [500000, 600000]처럼 원 단위 정수 리스트
    """
    pattern = r"(\d[\d,]*)\s*(만)?\s*원"
    matches = re.findall(pattern, text)

    money_values: list[int] = []

    for number_text, has_man_unit in matches:
        number = int(number_text.replace(",", ""))

        if has_man_unit:
            money_values.append(number * 10000)
        else:
            money_values.append(number)

    return money_values


def calculate_rent_increase(current_rent: int, requested_rent: int) -> dict[str, Any]:
    """
    현재 월세와 요구 월세를 기준으로 인상률과 5% 초과 여부를 계산합니다.
    """
    increase_amount = requested_rent - current_rent

    if current_rent <= 0:
        increase_rate = 0.0
    else:
        increase_rate = increase_amount / current_rent

    increase_rate_percent = round(increase_rate * 100, 2)
    allowed_max_rent = int(current_rent * 1.05)

    return {
        "rule_name": "차임 증액률 계산",
        "rule_type": "rent_increase_limit",
        "current_rent": current_rent,
        "requested_rent": requested_rent,
        "increase_amount": increase_amount,
        "increase_rate": round(increase_rate, 4),
        "increase_rate_percent": increase_rate_percent,
        "exceeds_five_percent": increase_rate > 0.05,
        "allowed_max_rent_by_five_percent": allowed_max_rent,
        "explanation": "현재 월세 대비 요구 월세의 인상률과 5% 초과 여부를 계산했습니다.",
    }


def run_b_part_rules(question: str, categories: list[str]) -> list[dict[str, Any]]:
    """
    사용자 질문과 예측 카테고리를 바탕으로 필요한 Rule Engine 계산을 실행합니다.

    이 함수는 계산 가능한 정보가 있을 때만 결과를 반환합니다.
    정보가 부족하면 빈 리스트를 반환하고, 추가 질문은 graph.py의 Missing Info Checker가 담당합니다.
    """
    results: list[dict[str, Any]] = []
    category_set = set(categories)

    if category_set & RENEWAL_CATEGORIES:
        contract_end_date = parse_date_from_text(question)
        if contract_end_date:
            results.append(calculate_renewal_request_period(contract_end_date))

    if category_set & RENT_INCREASE_CATEGORIES:
        money_values = parse_money_values_from_text(question)
        if len(money_values) >= 2:
            current_rent = money_values[0]
            requested_rent = money_values[1]
            results.append(calculate_rent_increase(current_rent, requested_rent))

    return results
