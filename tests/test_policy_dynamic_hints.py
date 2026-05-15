import json

from src.legal_chatbot import policy


def test_dynamic_hints_are_loaded_from_json_file(tmp_path, monkeypatch):
    hint_file = tmp_path / "approved_hints.json"
    hint_file.write_text(
        json.dumps(
            {
                "hints": [
                    {
                        "keywords": ["nghỉ giữa giờ độc hại"],
                        "articles": [109],
                        "enabled": True,
                        "confidence": 0.9,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(policy, "HINTS_APPROVED_PATH", str(hint_file))
    policy.reload_dynamic_hints_cache()

    query = "Người lao động làm việc nặng nhọc có nghỉ giữa giờ độc hại thế nào?"
    hints = policy.suggest_target_articles(query)

    assert 109 in hints


def test_dynamic_hints_skip_disabled_entries(tmp_path, monkeypatch):
    hint_file = tmp_path / "approved_hints.json"
    hint_file.write_text(
        json.dumps(
            {
                "hints": [
                    {
                        "keywords": ["nghỉ giữa giờ độc hại"],
                        "articles": [109],
                        "enabled": False,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(policy, "HINTS_APPROVED_PATH", str(hint_file))
    policy.reload_dynamic_hints_cache()

    query = "Người lao động làm việc nặng nhọc có nghỉ giữa giờ độc hại thế nào?"
    hints = policy.suggest_target_articles(query)

    assert 109 not in hints

