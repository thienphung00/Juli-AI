#!/usr/bin/env python3
"""Load a shop's contract KPI appendix from the reference ``kpi.json`` (ADR-117 §4).

The one-off path until Juli Ops has a contract form
(``juli_backend.services.shopee_kpi.contracts``):

    DATABASE_URL=postgresql://... python scripts/load_kpi_contract.py --shop-id <uuid> \
        --file ../juli-client-ops/clients/<client>/kpi.json --status sent \
        [--sent-on YYYY-MM-DD] [--signed-on YYYY-MM-DD] [--contract-ref REF] \
        [--email-ref "YYYY-MM-DD subject"] [--dry-run]

Running it again with the same file changes nothing; a changed status or date is
updated in place; changed terms insert a new version and need ``--email-ref``.
``--dry-run`` validates and rolls back. Prints the outcome and version only, never the
terms: they are client data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))


async def run(args: argparse.Namespace) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from juli_backend.core.config.runtime import async_database_url
    from juli_backend.services.shopee_kpi import ContractTermsError
    from juli_backend.services.shopee_kpi.contracts import (
        ContractFileError,
        load_contract,
        parse_contract_file,
    )

    try:
        contract = parse_contract_file(
            json.loads(Path(args.file).read_text(encoding="utf-8")),
            contract_ref=args.contract_ref,
        )
    except (ContractFileError, ContractTermsError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            try:
                result = await load_contract(
                    session,
                    uuid.UUID(args.shop_id),
                    contract,
                    status=args.status,
                    sent_on=args.sent_on,
                    signed_on=args.signed_on,
                    email_ref=args.email_ref,
                )
            except ContractFileError as exc:
                await session.rollback()
                print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 2
            if args.dry_run:
                await session.rollback()
            else:
                await session.commit()
    finally:
        await engine.dispose()
    print(
        f"{result.outcome}{' (dry run)' if args.dry_run else ''}: "
        f"contract_ref={contract.contract_ref} version={result.version} "
        f"contract_id={result.contract_id}"
        + (f" superseded={result.superseded_id}" if result.superseded_id else "")
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--shop-id", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--status", required=True, choices=("draft", "sent", "signed"))
    ap.add_argument("--sent-on", type=date.fromisoformat)
    ap.add_argument("--signed-on", type=date.fromisoformat)
    ap.add_argument("--contract-ref")
    ap.add_argument("--email-ref")
    ap.add_argument("--dry-run", action="store_true")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
