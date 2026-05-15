from src.legal_chatbot.text_quality import detect_runaway_generation


def test_detect_runaway_generation_flags_repetitive_loop():
    repeated = "được cơ quan có thẩm quyền cho hưởng án treo"
    answer = (
        "Theo Điều 46 Bộ luật Lao động. "
        + " ".join([repeated for _ in range(12)])
    )
    result = detect_runaway_generation(answer)
    assert result["is_runaway"] is True
    assert result["max_ngram_repeat"] >= 6


def test_detect_runaway_generation_allows_normal_answer():
    answer = (
        "Theo Điều 46 Bộ luật Lao động, người sử dụng lao động phải trả trợ cấp thôi việc "
        "khi hợp đồng chấm dứt thuộc các trường hợp luật định và người lao động đủ điều kiện thời gian làm việc."
    )
    result = detect_runaway_generation(answer)
    assert result["is_runaway"] is False

