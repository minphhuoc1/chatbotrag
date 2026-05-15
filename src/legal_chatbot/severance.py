import re
from dataclasses import dataclass
from typing import List


@dataclass
class Period:
    label: str
    start_year: int | None = None
    end_year: int | None = None
    note: str = ""


def _contains_severance_calculation_request(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "trợ cấp thôi việc" in lowered
        and any(marker in lowered for marker in ["tính", "khoảng thời gian", "bao nhiêu", "thời gian nào"])
    )


def _extract_year_periods(text: str) -> List[Period]:
    periods: List[Period] = []
    for start, end in re.findall(r"(\d{4})\s*[-–]\s*(\d{4})", text):
        periods.append(Period(label=f"{start}-{end}", start_year=int(start), end_year=int(end)))
    return periods


def try_build_severance_answer(user_input: str) -> str:
    """Deterministic severance-pay helper for complex date/BHTN questions.

    The helper intentionally avoids producing a final money amount when the query
    lacks wage/BHTN details. It gives a legally grounded calculation framework and
    identifies the periods that need classification.
    """
    text = user_input or ""
    lowered = text.lower()
    if not _contains_severance_calculation_request(lowered):
        return ""

    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", lowered)]
    periods = _extract_year_periods(lowered)
    has_military = "nghĩa vụ" in lowered or "quân sự" in lowered
    has_insurance_debt = any(marker in lowered for marker in ["nợ bảo hiểm", "nợ bh", "không đóng bảo hiểm"])
    has_bhtn = "bhtn" in lowered or "bảo hiểm thất nghiệp" in lowered

    timeline = ""
    if years:
        timeline = (
            f"\n\nDữ kiện thời gian nhận diện được: {min(years)} đến {max(years)}"
            + (f"; các giai đoạn nêu riêng: {', '.join(p.label for p in periods)}." if periods else ".")
        )

    special_notes: List[str] = []
    if has_military:
        special_notes.append(
            "Giai đoạn đi nghĩa vụ quân sự cần kiểm tra hồ sơ lao động: nếu không được tính là thời gian làm việc thực tế "
            "hoặc quan hệ lao động bị tạm hoãn theo cách không được tính trợ cấp thì không cộng; nếu pháp luật/hồ sơ coi là "
            "thời gian làm việc thực tế mà chưa tham gia BHTN thì mới xem xét cộng."
        )
    if has_insurance_debt or has_bhtn:
        special_notes.append(
            "Giai đoạn công ty nợ/không đóng bảo hiểm không nên tự động chuyển thành thời gian hưởng trợ cấp thôi việc. "
            "Cần xác định đây có phải thời gian thuộc diện tham gia bảo hiểm thất nghiệp hay không; nếu thuộc diện tham gia "
            "thì hướng xử lý chính là yêu cầu doanh nghiệp hoàn tất nghĩa vụ bảo hiểm, không cộng trùng vào trợ cấp thôi việc."
        )

    notes_block = ""
    if special_notes:
        notes_block = "\n\nCác điểm cần xác minh:\n" + "\n".join(f"- {note}" for note in special_notes)

    return (
        "Kết luận: chưa nên chốt một con số trợ cấp thôi việc chỉ từ dữ kiện hiện có. "
        "Cần tính theo công thức của Điều 46: thời gian tính trợ cấp = tổng thời gian người lao động đã làm việc thực tế "
        "trừ thời gian đã tham gia bảo hiểm thất nghiệp và trừ thời gian đã được chi trả trợ cấp thôi việc/mất việc trước đó.\n\n"
        "Cách tính tiền: mỗi năm làm việc được trợ cấp 1/2 tháng tiền lương; tiền lương làm căn cứ là tiền lương bình quân "
        "theo hợp đồng của 06 tháng liền kề trước khi thôi việc.\n\n"
        "Với tình huống bạn nêu, các khoảng chắc chắn phải bóc tách gồm: thời gian làm việc trước khi tham gia BHTN, "
        "thời gian đi nghĩa vụ quân sự, và giai đoạn doanh nghiệp nợ/không đóng bảo hiểm."
        f"{timeline}"
        f"{notes_block}\n\n"
        "Căn cứ pháp lý: Điều 46 Bộ luật Lao động 2019."
    )
