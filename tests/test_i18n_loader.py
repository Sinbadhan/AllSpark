"""AS-NEW-20260907-I18N-IMPORT-SLO: preserve data and safe loader semantics."""
import runpy

import pytest
import yaml

from allspark.core import i18n


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_accelerated_catalog_matches_independent_python_safe_loader(lang):
    path = i18n._LOCALES_DIR / f"{lang}.yaml"
    expected = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert expected
    assert i18n._load_locale(lang) == expected
    assert i18n.MESSAGES[lang] == expected


@pytest.mark.parametrize("loader", [yaml.SafeLoader, getattr(yaml, "CSafeLoader", yaml.SafeLoader)])
def test_locale_loader_rejects_python_object_tags(loader, tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(i18n, "_LOCALES_DIR", tmp_path)
    monkeypatch.setattr(i18n, "_LOCALE_LOADER", loader)
    (tmp_path / "zh.yaml").write_text(
        "!!python/object/apply:builtins.str [123]", encoding="utf-8"
    )
    assert i18n._load_locale("zh") == {}
    assert "could not determine a constructor" in caplog.text


def test_source_only_pyyaml_falls_back_without_changing_catalogs(monkeypatch):
    monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    # Isolated namespace: do not reload the live module or replace request
    # ContextVars used by other tests/application instances.
    isolated = runpy.run_path(i18n.__file__)
    assert isolated["_LOCALE_LOADER"] is yaml.SafeLoader
    assert isolated["MESSAGES"] == i18n.MESSAGES
