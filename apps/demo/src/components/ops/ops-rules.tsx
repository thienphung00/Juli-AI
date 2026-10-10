"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { createOpsRulesFetch } from "../../lib/ops/view-fetch";
import { deleteShopRule, fetchShopRules, putShopRule } from "../../lib/quyet-dinh/api-client";
import type { ShopRules } from "../../lib/quyet-dinh/types";
import { readAuthSession } from "../../lib/supabase-auth";
import { RulesEditor } from "../quyet-dinh/rules-editor";
import { C, card } from "./ops-shell";

/**
 * D25.14: the shop's seller rules, edited by the team in Cài đặt shop with the
 * seller's own editor (every value written as "Đội ngũ Juli đặt", audited).
 * The seller later sees and keeps editing the same rules on their Quy tắc page.
 * Approving cards stays the seller's; Xem như shop stays read-only.
 */
export function OpsRules({ shopId, canEdit, baseFetch }: { readonly shopId: string; readonly canEdit: boolean; readonly baseFetch?: typeof fetch }) {
  const fetchImpl = useMemo(() => createOpsRulesFetch({ shopId, baseFetch }), [shopId, baseFetch]);
  const [rules, setRules] = useState<ShopRules | null>(null);
  const [failed, setFailed] = useState(false);
  const auth = useMemo(() => ({ token: readAuthSession()?.accessToken ?? "", shopId, fetchImpl }), [shopId, fetchImpl]);

  const load = useCallback(() => {
    fetchShopRules(auth)
      .then(setRules)
      .catch(() => setFailed(true));
  }, [auth]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div data-testid="ops-rules" style={card}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Quy tắc</h2>
      <span style={{ fontSize: 12, color: C.muted2 }}>
        Đội ngũ đặt trước, seller xem và sửa tiếp trong Quy tắc của mình. Mọi thay đổi được ghi nhật ký.
      </span>
      {failed ? <p role="alert">Không tải được Quy tắc.</p> : null}
      {rules ? (
        <fieldset disabled={!canEdit} style={{ border: 0, margin: 0, padding: 0, minWidth: 0 }}>
          <RulesEditor
            fixedSetBy="team"
            headingLevel={3}
            key={JSON.stringify(rules)}
            onDelete={async (key, scope) => {
              await deleteShopRule(auth, key, scope);
              load();
            }}
            onSave={async (key, value, _setBy, scope) => {
              await putShopRule(auth, key, value, "team", scope);
              load();
            }}
            rules={rules}
          />
        </fieldset>
      ) : null}
    </div>
  );
}
