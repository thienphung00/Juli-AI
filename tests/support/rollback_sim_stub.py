#!/usr/bin/env python3
"""Multi-call stub for the production rollback simulation (fast-track P57, D66).

Symlinked into a temp ``bin/`` dir as systemctl, systemd-run, journalctl, nginx, curl,
sleep, mv and the database tools, ahead of the real PATH. It models just enough of the
VPS for infra/scripts/rollback-release.sh to run end to end with no root, no systemd,
no nginx and no network:

* ``systemd-run`` "starts" a candidate: it records the unit and binds its ``--port`` in
  ``$SIM_STATE/ports/`` -- and refuses a port that is already bound, so a rollback that
  starts on the live slot fails exactly as the real bind would.
* ``curl`` answers loopback URLs from whichever unit holds the port (and the release
  dir that unit runs), and public URLs through the upstream nginx last LOADED, so a
  switch that was never reloaded is visible.
* the database tools (psql, pg_dump, pg_restore, alembic) log DB-TOUCH and fail.

Behaviour knobs: ``<release>/.sim-behaviour`` lines (``start=fail``, ``health=503``,
``shape=bad``) and ``$SIM_STATE/flags/<name>`` files (``nginx-t-fail``,
``public-<lane>-fail``, ``restart-fail-<unit>``, ``banner-omit-<queue>``).
Every call is appended to ``$SIM_STATE/calls.log``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

STATE = Path(os.environ["SIM_STATE"])
NGINX_DIR = Path(os.environ.get("NGINX_UPSTREAM_DIR", "/nonexistent"))
UNIT_DIR = Path(os.environ.get("SYSTEMD_UNIT_DIR", "/nonexistent"))
PUBLIC_HOSTS = {"api.app-juli.com": "api", "demo.app-juli.com": "demo", "app-juli.com": "landing"}
DB_TOOLS = {"psql", "pg_dump", "pg_restore", "alembic"}

HTML = (
    '<!doctype html><html><head><link rel="stylesheet" href="/_next/static/css/app.css">'
    '<script src="/_next/static/chunks/main.js"></script></head><body>{release}</body></html>'
)


def log(line: str) -> None:
    with (STATE / "calls.log").open("a") as fh:
        fh.write(line + "\n")


def flag(name: str) -> bool:
    return (STATE / "flags" / name).exists()


def unit_path(name: str) -> Path:
    return STATE / "units" / f"{name.removesuffix('.service')}.json"


def load_unit(name: str) -> dict | None:
    p = unit_path(name)
    return json.loads(p.read_text()) if p.exists() else None


def save_unit(name: str, data: dict) -> None:
    unit_path(name).write_text(json.dumps(data))


def behaviour(release: str) -> dict[str, str]:
    p = Path(release) / ".sim-behaviour"
    if not p.exists():
        return {}
    return dict(line.split("=", 1) for line in p.read_text().split() if "=" in line)


def next_invocation() -> str:
    counter = STATE / "invocation-counter"
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    return f"inv{n:04d}"


def free_port_of(name: str) -> None:
    data = load_unit(name)
    if data and data.get("port"):
        port_file = STATE / "ports" / str(data["port"])
        if port_file.exists() and port_file.read_text() == name.removesuffix(".service"):
            port_file.unlink()


# --------------------------------------------------------------------------------------


def systemctl(args: list[str]) -> int:
    quiet = "--quiet" in args
    args = [a for a in args if a not in ("--quiet", "--no-pager", "--full")]
    if not args:
        return 0
    verb, rest = args[0], args[1:]
    if verb == "stop":
        for name in rest:
            free_port_of(name)
            data = load_unit(name)
            if data:
                data["active"] = False
                data["port"] = None
                save_unit(name, data)
        return 0
    if verb in ("reset-failed", "daemon-reload", "status"):
        return 0
    if verb == "reload" and rest == ["nginx"]:
        if flag("nginx-reload-fail"):
            return 1
        loaded = STATE / "nginx-loaded"
        loaded.mkdir(exist_ok=True)
        for conf in NGINX_DIR.glob("*-upstream.conf"):
            shutil.copyfile(conf, loaded / conf.name)
        return 0
    if verb == "restart":
        name = rest[0].removesuffix(".service")
        if flag(f"restart-fail-{name}"):
            return 1
        data = load_unit(name) or {"lane": None, "port": None, "release": None}
        data.update(active=True, invocation=next_invocation())
        save_unit(name, data)
        return 0
    if verb == "is-active":
        data = load_unit(rest[0])
        active = bool(data and data.get("active"))
        if not quiet:
            print("active" if active else "inactive")
        return 0 if active else 3
    if verb == "cat":
        unit_file = UNIT_DIR / f"{rest[0].removesuffix('.service')}.service"
        if unit_file.exists():
            print(unit_file.read_text())
            return 0
        return 1
    if verb == "show":
        name = rest[-1]
        data = load_unit(name)
        print(data.get("invocation", "") if data and data.get("active") else "")
        return 0
    return 0


def systemd_run(args: list[str]) -> int:
    unit = None
    props: dict[str, str] = {}
    i = 0
    while i < len(args) and args[i].startswith("--"):
        a = args[i]
        if a.startswith("--unit="):
            unit = a.split("=", 1)[1]
        elif a.startswith("--property="):
            key, _, value = a.split("=", 1)[1].partition("=")
            props[key] = value
        i += 1
    argv = args[i:]
    assert unit, "systemd-run without --unit"
    port = argv[argv.index("--port") + 1] if "--port" in argv else None
    workdir = props.get("WorkingDirectory", "")
    release = workdir if "/apps/" not in workdir else workdir.split("/apps/", 1)[0]
    lane = unit.split("-")[1]  # juli-<lane>-candidate-<port>
    binary = Path(argv[0])
    data = {"lane": lane, "port": None, "release": release, "active": False, "argv": argv}
    port_file = STATE / "ports" / str(port)
    if not (binary.is_file() and os.access(binary, os.X_OK)):
        log(f"SIM: {unit} exec failed ({binary} missing)")
    elif behaviour(release).get("start") == "fail":
        log(f"SIM: {unit} crashed on start")
    elif port_file.exists():
        log(f"SIM: PORT-CONFLICT {unit} could not bind :{port} (held by {port_file.read_text()})")
    else:
        port_file.write_text(unit)
        data.update(port=port, active=True)
    save_unit(unit, data)
    return 0  # Type=simple: systemd-run succeeds even when the process dies right after


def journalctl(args: list[str]) -> int:
    name = None
    for a in args:
        if a.startswith("_SYSTEMD_INVOCATION_ID="):
            inv = a.split("=", 1)[1]
            for p in (STATE / "units").glob("*.json"):
                if json.loads(p.read_text()).get("invocation") == inv:
                    name = p.stem
    if "-u" in args:
        name = args[args.index("-u") + 1]
    if name != "juli-celery-worker":
        return 0
    lines = (UNIT_DIR / "juli-celery-worker.service").read_text().splitlines()
    text = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    match = re.search(r"-Q\s+([A-Za-z0-9_,]+)", text)
    for queue in match.group(1).split(",") if match else []:
        if not flag(f"banner-omit-{queue}"):
            print(f"                .> {queue}          exchange={queue}(direct) key={queue}")
    return 0


def respond(lane: str, release: str, path: str) -> tuple[int, str, str]:
    b = behaviour(release)
    if lane == "api":
        if path == "/health":
            code = int(b.get("health", "200"))
            status = "ok" if code == 200 else "down"
            if b.get("shape") == "bad":
                status = "degraded"  # 200, wrong body: the shape check must fail
            return code, json.dumps({"status": status}), "application/json"
        return 404, "{}", "application/json"
    if path.endswith(".css"):
        return 200, "body{color:#000}" + " " * 200, "text/css"
    if path.endswith(".js"):
        return 200, "console.log(1);" + " " * 200, "application/javascript"
    code = int(b.get("http", "200"))
    return code, HTML.format(release=release), "text/html; charset=utf-8"


def curl(args: list[str]) -> int:
    out = fmt = None
    url = ""
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "--output"):
            out = args[i + 1]
            i += 2
            continue
        if a in ("-w", "--write-out"):
            fmt = args[i + 1]
            i += 2
            continue
        if a in ("-m", "--max-time", "-H", "--header", "-A"):
            i += 2
            continue
        if a.startswith("http://") or a.startswith("https://"):
            url = a
        i += 1
    parts = urlsplit(url)
    path = parts.path or "/"
    code, body, ctype = 0, "", ""
    if parts.hostname == "127.0.0.1":
        port_file = STATE / "ports" / str(parts.port)
        if port_file.exists():
            data = load_unit(port_file.read_text()) or {}
            code, body, ctype = respond(data["lane"], data["release"], path)
    elif parts.hostname in PUBLIC_HOSTS:
        lane = PUBLIC_HOSTS[parts.hostname]
        loaded = STATE / "nginx-loaded" / f"{lane}-upstream.conf"
        match = (
            re.search(r"server\s+127\.0\.0\.1:(\d+);", loaded.read_text())
            if loaded.exists()
            else None
        )
        port_file = STATE / "ports" / (match.group(1) if match else "none")
        if flag(f"public-{lane}-fail"):
            code, body, ctype = 502, "<html>bad gateway</html>", "text/html"
        elif port_file.exists():
            data = load_unit(port_file.read_text()) or {}
            code, body, ctype = respond(data["lane"], data["release"], path)
        else:
            code, body, ctype = 502, "<html>bad gateway</html>", "text/html"
    log(f"curl {url} -> {code or 'refused'}")
    if code and out and out != "/dev/null":
        Path(out).write_text(body)
    elif code and not out:
        sys.stdout.write(body)
    if fmt:
        sys.stdout.write(
            fmt.replace("%{http_code}", f"{code:03d}")
            .replace("%{size_download}", str(len(body)))
            .replace("%{content_type}", ctype)
        )
    return 0 if code else 7


def mv(args: list[str]) -> int:
    flags = [a for a in args if a.startswith("-")]
    paths = [a for a in args if not a.startswith("-")]
    if any("T" in f for f in flags):
        os.replace(paths[0], paths[1])  # GNU -T semantics: rename over DEST itself
        return 0
    os.execv("/bin/mv", ["mv", *args])
    return 1


def main() -> int:
    name = Path(sys.argv[0]).name
    args = sys.argv[1:]
    if name != "mv":
        log(" ".join([name, *args]))
    if name in DB_TOOLS:
        log(f"DB-TOUCH {name}")
        print(f"SIM: {name} must never run during a rollback", file=sys.stderr)
        return 99
    if name == "systemctl":
        return systemctl(args)
    if name == "systemd-run":
        return systemd_run(args)
    if name == "journalctl":
        return journalctl(args)
    if name == "nginx":
        return 1 if flag("nginx-t-fail") else 0
    if name == "curl":
        return curl(args)
    if name == "sleep":
        time.sleep(min(float(args[0]) if args else 0.0, 0.02))
        return 0
    if name == "mv":
        return mv(args)
    print(f"SIM: unknown stub {name}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
