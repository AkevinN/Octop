"""tests/unit/i18n/test_skills.py"""

from __future__ import annotations

from tests.support.i18n_bundles import merged_backend_bundle, merged_dashboard_bundle

from octop.i18n import all_skill_labels, skill_display_name


def test_skill_display_name_known_zh():
    assert skill_display_name("pdf", "zh") == "PDF 处理"


def test_skill_display_name_octop_assistant_slug_zh():
    assert skill_display_name("octop-assistant", "zh") == "Octop 配置助手"


def test_skill_display_name_octop_assistant_name_zh():
    assert skill_display_name("octop_assistant", "zh") == "Octop 配置助手"


def test_skill_display_name_unknown_passthrough():
    assert skill_display_name("my-custom-skill", "en") == "my-custom-skill"


def test_skill_display_name_empty_passthrough():
    assert skill_display_name(None, "en") == ""


def test_all_skill_labels_includes_pdf():
    labels = all_skill_labels("en")
    assert labels["docx"] == "Word"
    assert labels["octop-assistant"] == "Octop Assistant"


def test_dashboard_skill_labels_match_backend():
    dash_en = merged_dashboard_bundle("en")
    backend_en = merged_backend_bundle("en")
    for slug, label in backend_en["skills"].items():
        assert dash_en["skills"][slug] == label
