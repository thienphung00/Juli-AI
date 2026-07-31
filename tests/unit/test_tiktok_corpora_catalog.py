"""Unit tests for TikTok corpora catalog builder (ADR-051 / issue #593)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from tiktok_corpora_catalog.builder import (  # noqa: E402
    REQUIRED_ENTRY_FIELDS,
    build_catalog_for_corpus,
    build_corpus_root,
    parse_front_matter,
    should_skip_path,
)

FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "tiktok_corpora_catalog"

MINIMUM_FIELDS = {
    "corpus",
    "path",
    "title",
    "url",
    "slug",
    "section",
    "nav_path",
    "page_kind",
    "last_crawled",
}


def test_parse_front_matter_extracts_fields_and_body():
    text = FIXTURE_ROOT.joinpath("business_documents/started/postman-collection.md").read_text(
        encoding="utf-8"
    )
    fields, body = parse_front_matter(text)
    assert fields["title"] == "Postman collection"
    assert fields["slug"] == "postman-collection"
    assert fields["version"] == "v1.3"
    assert body.startswith("# Postman collection")
    assert "API endpoints" in body


def test_business_fixture_catalog_entry_shape():
    catalog = build_catalog_for_corpus("business", FIXTURE_ROOT / "business_documents")
    assert len(catalog["entries"]) == 1
    entry = catalog["entries"][0]
    assert MINIMUM_FIELDS <= set(entry.keys())
    assert entry["corpus"] == "business"
    assert entry["path"] == "started/postman-collection.md"
    assert entry["title"] == "Postman collection"
    assert entry["slug"] == "postman-collection"
    assert entry["version"] == "v1.3"
    assert entry["page_kind"] == "guide"


def test_partner_skips_raw_paths():
    catalog = build_catalog_for_corpus("partner", FIXTURE_ROOT / "partner_documents")
    paths = [e["path"] for e in catalog["entries"]]
    assert len(paths) == 1
    assert paths[0] == "api/get-active-shops.md"
    assert not any("_raw" in p for p in paths)


def test_partner_endpoint_optional_fields():
    catalog = build_catalog_for_corpus("partner", FIXTURE_ROOT / "partner_documents")
    entry = catalog["entries"][0]
    assert entry["method"] == "GET"
    assert entry["api_path"] == "/seller/202309/shops"
    assert entry["page_kind"] == "endpoint"


def test_academy_maps_breadcrumb_and_knowledge_id():
    catalog = build_catalog_for_corpus("academy", FIXTURE_ROOT / "academy_documents")
    assert len(catalog["entries"]) == 1
    entry = catalog["entries"][0]
    assert entry["slug"] == "10018975"
    assert entry["nav_path"] == ("Trang chủ > Hướng dẫn Tính năng > Chiếu Trực Tiếp Livestream")
    assert entry["section"] == "trang-chu"
    assert entry["page_kind"] == "article"


def test_catalog_entries_contain_no_body_text():
    for corpus in ("business", "partner", "academy"):
        corpus_dir = FIXTURE_ROOT / f"{corpus}_documents"
        catalog = build_catalog_for_corpus(corpus, corpus_dir)
        serialized = json.dumps(catalog)
        assert "must not appear in catalogs" not in serialized
        assert "must not leak into catalog JSON" not in serialized
        assert "must be excluded" not in serialized
        for entry in catalog["entries"]:
            for value in entry.values():
                assert isinstance(value, str)
                assert len(value) < 500


def test_should_skip_path_rejects_raw_segments():
    assert should_skip_path(Path("api/get-active-shops.md")) is False
    assert should_skip_path(Path("_raw/api/page.md")) is True
    assert should_skip_path(Path("nested/_raw/twin.md")) is True


def test_build_corpus_root_default_and_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("JULI_TIKTOK_CORPORA_ROOT", raising=False)
    default_root = build_corpus_root()
    assert default_root.name == "tiktok-corpora"
    assert (default_root / "business_documents").name == "business_documents"

    override = Path("/tmp/custom-corpora-root")
    monkeypatch.setenv("JULI_TIKTOK_CORPORA_ROOT", str(override))
    assert build_corpus_root() == override


def test_required_entry_fields_match_adr():
    assert REQUIRED_ENTRY_FIELDS == MINIMUM_FIELDS


def test_playbook_documents_crawler_output_retarget():
    readme = (REPO_ROOT / "docs/integrations/tiktok_corpora/README.md").read_text(encoding="utf-8")
    assert "Crawler" in readme or "crawler" in readme
    assert "Juli-AI-local/tiktok-corpora" in readme


def test_focus_phase_gate_excludes_executor_review_corpora():
    skill = (REPO_ROOT / ".cursor/skills/standalone/focus/SKILL.md").read_text(encoding="utf-8")
    assert "PHASE GATE" in skill
    assert "Executor/Review" in skill
    assert "tiktok_corpora" in skill


def test_playbook_documents_fail_soft_missing_bodies():
    readme = (REPO_ROOT / "docs/integrations/tiktok_corpora/README.md").read_text(encoding="utf-8")
    lowered = readme.lower()
    assert "fail soft" in lowered or "fail-soft" in lowered
    assert "unavailable" in lowered
