"""Rubric registry for the judge (#1460, HE-D/P-EVAL-17).

A rubric is declarative: a `prompt`, a tuple of `anchors` (few-shot examples),
a `model` id, and the canary IDs that must gate it before it ever scores a real
record. `rubric_hash` is derived from exactly those three fields — the ones
that define what question the rubric is asking. Editing any of them forces a
fresh advisory period: the calibration a previous version earned (#1461's
promotion path, not built here) does not transfer to a version asking a
different question. A judge scored by the same model class that produced the
output is not an independent reward in the first place; changing the question
without resetting the clock would compound that with false confidence.

This module never writes `state: "calibrated"`. It only:

- computes `rubric_hash` from `(prompt, anchors, model)`,
- persists `(rubric_hash, state)` per rubric id, and
- resets `state` to `"advisory"` the moment a load observes a hash it has not
  seen before (including a rubric loaded for the first time ever).

Promotion — the only path that could ever write `"calibrated"` — is #1461's
job, gated on kappa against human labels over a four-week holdout. Nothing here
builds it, and nothing here can promote a rubric.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Named `rubric_defs/`, not `rubrics/` — a same-named sibling directory
#: shadows `eval/rubrics.py` as a namespace package the moment this module is
#: absent from `sys.path` resolution order (identical hazard to
#: `eval.canaries` / `canary_corpus/`; see that module's comment).
RUBRIC_DIR = Path(__file__).resolve().parent / "rubric_defs"
STATE_DIR = RUBRIC_DIR / "_state"

ADVISORY = "advisory"
#: Never written by `load_rubric`. Reserved for #1461's promotion path; a test
#: may seed it directly to prove the reset-on-edit behaviour, since this module
#: has no other way to produce it.
CALIBRATED = "calibrated"
STATES = (ADVISORY, CALIBRATED)


class RubricNotFoundError(LookupError):
    """No rubric definition exists at the expected path. Fail-closed."""


@dataclass(frozen=True)
class Rubric:
    id: str
    prompt: str
    anchors: tuple[str, ...]
    model: str
    canary_ids: tuple[str, ...]
    rubric_hash: str
    state: str


def compute_rubric_hash(prompt: str, anchors: Any, model: str) -> str:
    """Hash over exactly the fields that define the question being asked.
    Deliberately excludes `canaryIds` and any scorer/metadata field: adding a
    canary or fixing a typo in a description must not, by itself, void
    calibration the way changing the prompt, anchors, or model does.
    """
    canonical = json.dumps(
        {"prompt": prompt, "anchors": list(anchors), "model": model},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _definition_path(rubric_id: str, rubric_dir: Path) -> Path:
    return rubric_dir / f"{rubric_id}.json"


def _state_path(rubric_id: str, state_dir: Path) -> Path:
    return state_dir / f"{rubric_id}.json"


def load_rubric_definition(rubric_id: str, rubric_dir: Path = RUBRIC_DIR) -> dict[str, Any]:
    path = _definition_path(rubric_id, rubric_dir)
    if not path.is_file():
        raise RubricNotFoundError(f"no rubric definition at {path}")
    return json.loads(path.read_text())


def load_rubric(
    rubric_id: str,
    *,
    rubric_dir: Path = RUBRIC_DIR,
    state_dir: Path = STATE_DIR,
) -> Rubric:
    """Load a rubric and reconcile its persisted state against its current hash.

    Every rubric ships `state: advisory` until #1461 calibrates it. This
    function is the one place that can *reset* a rubric back to advisory —
    triggered purely by the hash changing, never by anything else — so a
    prompt/anchor/model edit can never quietly keep riding a prior
    calibration.
    """
    definition = load_rubric_definition(rubric_id, rubric_dir)
    prompt = definition["prompt"]
    anchors = tuple(definition.get("anchors", ()))
    model = definition["model"]
    canary_ids = tuple(definition.get("canaryIds", ()))
    current_hash = compute_rubric_hash(prompt, anchors, model)

    state_path = _state_path(rubric_id, state_dir)
    if state_path.is_file():
        stored = json.loads(state_path.read_text())
        stored_hash = stored.get("rubricHash")
        stored_state = stored.get("state", ADVISORY)
    else:
        stored_hash = None
        stored_state = ADVISORY

    if stored_hash != current_hash:
        # First load ever, or prompt/anchors/model changed since the state was
        # last persisted. Either way any prior calibration is void.
        state = ADVISORY
    else:
        state = stored_state

    state_dir.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"rubricId": rubric_id, "rubricHash": current_hash, "state": state}, indent=2)
        + "\n"
    )

    return Rubric(
        id=rubric_id,
        prompt=prompt,
        anchors=anchors,
        model=model,
        canary_ids=canary_ids,
        rubric_hash=current_hash,
        state=state,
    )


__all__ = [
    "ADVISORY",
    "CALIBRATED",
    "RUBRIC_DIR",
    "STATES",
    "STATE_DIR",
    "Rubric",
    "RubricNotFoundError",
    "compute_rubric_hash",
    "load_rubric",
    "load_rubric_definition",
]
