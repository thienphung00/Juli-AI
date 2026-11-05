"""A shop no seller has taken yet can be handed over by invite (Ops "Mời seller")."""

from juli_backend.services.ops.overview import is_team_owned


def test_a_contract_shop_owner_without_email_counts_as_not_yet_handed_over():
    assert is_team_owned(None) is True


def test_a_staff_account_counts_as_not_yet_handed_over_and_a_seller_does_not():
    assert is_team_owned("ops@app-juli.com") is True
    assert is_team_owned("Ops@App-Juli.com") is True
    assert is_team_owned("seller@example.com") is False
