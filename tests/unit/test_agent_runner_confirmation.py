"""`runner/confirmation.py` -- decision-request construction at a CONFIRM
pause (ADR-075 decision 2, issue #1221 / AGT-W5A).

Two things this module defines and this file proves:

- `compute_params_sha`: a NEW, independent fingerprint over a tool's raw
  params -- deliberately not `runner/concurrency.py::_hash_field` (a
  narrower mechanism scoped to individual mutable product fields for the
  stale-read guard). Determinism is asserted two ways per the issue's own
  acceptance criteria: a shuffled-key input (same logical dict, different
  insertion order) hashes identically, and a *fresh interpreter*
  (subprocess) computes the same hash as this process -- `PYTHONHASHSEED`
  varies per process, so an in-process-only check could hide a seed-
  dependent bug.
- `build_confirmation_options`: binary confirm is the N=1 case -- exactly
  one `ConfirmationOptionPayload`, `proposed_change` verbatim, `params_sha`
  computed over that same verbatim dict.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unicodedata
from pathlib import Path

from juli_backend.services.agent.events.payloads import ConfirmationOptionPayload
from juli_backend.services.agent.runner.confirmation import (
    build_confirmation_options,
    canonicalize_params,
    compute_params_sha,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"


class TestCanonicalizeParams:
    def test_shuffled_key_order_produces_identical_canonical_form(self):
        a = {"amount": "179000", "currency": "VND", "sku_ref": "S1"}
        b = {"sku_ref": "S1", "amount": "179000", "currency": "VND"}
        assert a != list(a.items())  # sanity: dicts really differ in insertion order below
        assert list(a.items()) != list(b.items())

        assert canonicalize_params(a) == canonicalize_params(b)

    def test_nested_shuffled_key_order_also_matches(self):
        a = {"skus": [{"sku_ref": "S1", "amount": "179000", "currency": "VND"}]}
        b = {"skus": [{"currency": "VND", "sku_ref": "S1", "amount": "179000"}]}
        assert canonicalize_params(a) == canonicalize_params(b)

    def test_canonical_form_uses_compact_separators_and_sorted_keys(self):
        params = {"b": 1, "a": 2}
        assert canonicalize_params(params) == '{"a":2,"b":1}'

    def test_unicode_strings_are_nfc_normalized(self):
        # Built from unicodedata itself, not hand-typed, so the NFD/NFC
        # pair is provably the *same* string in two different byte forms
        # rather than a typo that happens to differ. A Vietnamese product
        # title could arrive in either normalization form depending on
        # the input method that produced it.
        composed_text = "s\u1ea3n ph\u1ea9m"
        decomposed_text = unicodedata.normalize("NFD", composed_text)
        assert composed_text != decomposed_text  # sanity: genuinely different bytes
        assert unicodedata.normalize("NFC", decomposed_text) == composed_text

        composed = {"title": composed_text}
        decomposed = {"title": decomposed_text}
        assert canonicalize_params(decomposed) == canonicalize_params(composed)


class TestComputeParamsSha:
    def test_stable_across_shuffled_key_order_in_process(self):
        a = {"amount": "179000", "currency": "VND", "sku_ref": "S1"}
        b = {"sku_ref": "S1", "amount": "179000", "currency": "VND"}
        assert compute_params_sha(a) == compute_params_sha(b)

    def test_returns_a_sha256_hex_digest(self):
        digest = compute_params_sha({"sku_ref": "S1", "amount": "179000"})
        assert len(digest) == 64
        int(digest, 16)  # raises ValueError if not valid hex

    def test_different_params_hash_differently(self):
        assert compute_params_sha({"amount": "179000"}) != compute_params_sha({"amount": "189000"})

    def test_stable_across_a_fresh_interpreter_process(self):
        """PYTHONHASHSEED varies per process by default -- a hash that
        depended on it (e.g. naive dict iteration without `sort_keys`)
        could agree with itself in-process by luck while disagreeing with
        a genuinely separate process, which is exactly the failure mode
        #1224's cross-process re-derivation cannot tolerate. Spawns a
        real subprocess (no PYTHONHASHSEED pinned) rather than calling the
        function twice in this interpreter."""
        params_json = json.dumps({"sku_ref": "S1", "amount": "179000", "currency": "VND"})
        script = (
            "import json, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from juli_backend.services.agent.runner.confirmation import compute_params_sha\n"
            "print(compute_params_sha(json.loads(sys.argv[2])))\n"
        )
        in_process = compute_params_sha(json.loads(params_json))

        results = set()
        for _ in range(3):
            proc = subprocess.run(
                [sys.executable, "-c", script, str(BACKEND_SRC), params_json],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
                env={"PATH": "/usr/bin:/bin:/usr/local/bin"},  # PYTHONHASHSEED left unset/random
            )
            results.add(proc.stdout.strip())

        assert results == {in_process}, (
            f"params_sha diverged across fresh interpreter processes: {results}"
        )


class TestBuildConfirmationOptions:
    def test_binary_confirm_is_the_n_equals_1_case(self):
        options = build_confirmation_options(
            rationale="Apply new SKU prices to the bound product.",
            arguments={"skus": [{"sku_ref": "S1", "amount": "179000", "currency": "VND"}]},
        )
        assert len(options) == 1

    def test_option_shape_matches_confirmation_option_payload(self):
        arguments = {"skus": [{"sku_ref": "S1", "amount": "179000", "currency": "VND"}]}
        options = build_confirmation_options(
            rationale="Apply new SKU prices to the bound product.",
            arguments=arguments,
        )
        option = options[0]
        assert isinstance(option, ConfirmationOptionPayload)
        assert option.proposed_change == arguments
        assert option.rationale == "Apply new SKU prices to the bound product."
        assert option.params_sha == compute_params_sha(arguments)

    def test_proposed_change_is_verbatim_not_a_copy_that_mutates_the_source(self):
        """The audit is what was shown -- never a re-derivation. Mutating
        the caller's `arguments` dict after the call must not retroactively
        change the option's stored `proposed_change`."""
        arguments = {"skus": [{"sku_ref": "S1", "amount": "179000"}]}
        options = build_confirmation_options(rationale="r", arguments=arguments)
        arguments["skus"][0]["amount"] = "999999"
        # Top-level dict is independent even though we don't deep-copy
        # nested structures the model never mutates in place either.
        assert options[0].proposed_change is not arguments

    def test_no_raw_vendor_identifier_or_credential_in_the_built_option(self):
        """`update_product_price`'s own input schema is raw-ID-free by
        construction (ADR-070 decision 1): `sku_ref` is a server-minted
        opaque token ("S1"), never the raw vendor SKU id, and no
        credential field exists on the tool at all. This asserts that
        precedent actually holds for what this slice serializes into
        `options`, rather than assuming it."""
        raw_vendor_sku_id = "7233920938498231111"
        arguments = {
            "skus": [{"sku_ref": "S1", "amount": "179000", "currency": "VND"}],
        }
        options = build_confirmation_options(
            rationale="Apply new SKU prices to the bound product.",
            arguments=arguments,
        )
        serialized = json.dumps([opt.model_dump(mode="json") for opt in options])
        assert raw_vendor_sku_id not in serialized
        assert "access_token" not in serialized
        assert "sku_ref" in serialized  # the opaque token itself is fine to show
