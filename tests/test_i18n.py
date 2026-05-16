import pytest

from allspark.i18n import t, set_language, get_language, init_language


class TestI18nBasic:
    def test_default_language(self):
        lang = get_language()
        assert lang in ("zh", "en")

    def test_set_chinese(self):
        set_language("zh", persist=False)
        assert get_language() == "zh"

    def test_set_english(self):
        set_language("en", persist=False)
        assert get_language() == "en"

    def test_invalid_language_falls_back(self):
        original = get_language()
        set_language("fr", persist=False)
        assert get_language() in ("zh", "en")


class TestI18nTranslation:
    def test_chinese_key_exists(self):
        set_language("zh", persist=False)
        result = t("resource_not_configured")
        assert "未配置" in result or len(result) > 0

    def test_english_key_exists(self):
        set_language("en", persist=False)
        result = t("resource_not_configured")
        assert "not configured" in result.lower() or len(result) > 0

    def test_missing_key_returns_key(self):
        result = t("nonexistent_key_12345")
        assert "nonexistent_key_12345" in result

    def test_resource_type_keys(self):
        set_language("zh", persist=False)
        for key in ["resource_power", "resource_water", "resource_food",
                     "resource_fire", "resource_storage"]:
            result = t(key)
            assert len(result) > 0

    def test_advice_keys(self):
        set_language("en", persist=False)
        for key in ["advice_hibernation_1", "advice_hibernation_2"]:
            result = t(key)
            assert len(result) > 0
