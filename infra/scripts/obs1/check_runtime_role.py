import os
from sqlalchemy import create_engine, text

app = os.environ["DATABASE_URL"].replace("+asyncpg", "")
with create_engine(app).connect() as c:
    print("connected role     :", c.execute(text("select current_user")).scalar())
    r = c.execute(text(
        "select rolsuper, rolbypassrls, rolcanlogin from pg_roles where rolname = current_user"
    )).fetchone()
    print("superuser          :", r[0])
    print("bypassrls          :", r[1], "  <- must be False")
    print("canlogin           :", r[2])
    owned = c.execute(text("""
        select count(*) from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where c.relkind in ('r','p')
          and n.nspname in ('public','bronze','silver','gold','ops')
          and pg_get_userbyid(c.relowner) = current_user
    """)).scalar()
    print("tables owned       :", owned, "  <- must be 0")
    forced = c.execute(text("""
        select count(*) from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where c.relkind = 'r' and n.nspname='public' and c.relrowsecurity
    """)).scalar()
    print("RLS-enabled tables :", forced)
