import os
from sqlalchemy import create_engine, text

owner = os.environ["DATABASE_DIRECT_URL"].replace("+asyncpg", "")
app = os.environ["DATABASE_URL"].replace("+asyncpg", "")

# Two real shop ids, read as the owner (which is RLS-exempt) purely to pick targets.
with create_engine(owner).connect() as c:
    shops = [r[0] for r in c.execute(text("select id from shops order by created_at limit 2")).fetchall()]
if len(shops) < 2:
    raise SystemExit(f"need two shops to prove isolation; found {len(shops)}")
mine, theirs = shops[0], shops[1]
print("scope set to      :", mine)
print("querying rows of  :", theirs)

with create_engine(app).connect() as c:
    c.execute(text("select set_config('app.current_shop_id', :s, false)"), {"s": str(mine)})
    print("connected role    :", c.execute(text("select current_user")).scalar())
    own = c.execute(text("select count(*) from shops where id = cast(:s as uuid)"), {"s": str(mine)}).scalar()
    other = c.execute(text("select count(*) from shops where id = cast(:s as uuid)"), {"s": str(theirs)}).scalar()
    print("own shop visible  :", own,   "  <- expect 1")
    print("other shop visible:", other, "  <- MUST be 0")
    for t in ("workflow_runs", "action_cards", "tiktok_credentials"):
        n = c.execute(text(f"select count(*) from {t} where shop_id = cast(:s as uuid)"), {"s": str(theirs)}).scalar()
        print(f"  {t:<20} rows of the other tenant: {n}  <- MUST be 0")
