# Runbook: SSH hardening on the production VPS (issue #1448)

**Executed by:** the owner, by hand, on the host. **Not** by an agent, and not by CI.
**Host:** the production VPS, Ubuntu 24.04.4 LTS. **Epic:** #1449. **Issue:** #1448.
**Estimated time:** 40 minutes, most of it spent reading five public keys carefully.

Everything below is a command you paste into a root shell on the host. Nothing here has been
run. The audit that produced the findings was read-only and is not repeated — the state
recorded in #1448 is the starting state this runbook assumes.

---

## Before you start

Two things need to be true before the first command, and neither of them is on the host.

**You can reach the provider's web console.** Log into the provider control panel now and
confirm the VNC/serial console opens and gives you a login prompt. Every step in this runbook
is reversible over SSH, but reversible-over-SSH is only worth something while SSH still works.
The console is the path back if it does not. If you cannot open the console, stop — do the
rest of this on a day when you can.

**You know which key is yours.** On your laptop:

```bash
ssh-keygen -lf ~/.ssh/juli_vps_tool.pub
```

Write the `SHA256:...` fingerprint down somewhere you can see it. You will need it in Part 3,
and the one irreversible mistake available in this runbook is deleting the line that holds it.

---

## Part 0 — The ordering argument, and why it is not the obvious order

The host has no non-root accounts. Root is `without-password`, so root cannot be
password-authenticated no matter what the password setting says. `PasswordAuthentication` is
`yes` — but it is `yes` by inheritance, never written down anywhere, because that is the
OpenSSH upstream default and `/etc/ssh/sshd_config.d/` is empty. Nothing in the config reads
as wrong. Today, nothing *is* wrong: there is no account for which a password would be
accepted.

The next planned change to this host (epic #1449) creates the first named sudo user. The
moment that account exists, it is password-authenticatable from the public internet, on port
22 open to Anywhere, with no fail2ban and no rate limiting. The vulnerability is not created
by the SSH config; it is created by the user account, against an SSH config that was already
holding the door open.

So the order is inverted from the one that feels natural:

1. **`PasswordAuthentication no` first** — this runbook.
2. Named user + their key second — #1449.
3. `PermitRootLogin no` third, after the new login is confirmed in a second session — #1449.

Doing (2) before (1) opens a window that (1) closes for free. Both changes are equally
reversible — one is a file in a drop-in directory, the other is a line in `/etc/passwd` — so
the safe order costs nothing. There is no argument for the other order except that it is the
one you would think of first.

This runbook is step (1) alone, plus the two things that make step (1) meaningful: knowing who
holds root's keys, and rate-limiting the port.

---

## Part 1 — The two-session rule

Every sshd change in this runbook follows the same shape. It is worth reading once before you
need it, because the point of the rule is that you follow it when you are in a hurry.

**Terminal A** is the session you already have. It made the change. *Do not close it.* A live
root shell is a working authentication that no config reload can revoke — sshd never
re-authenticates an established session. As long as Terminal A is open you can undo anything.

**Terminal B** is a brand new connection from your laptop, opened *after* the reload, that
proves the new config still lets you in.

The full cycle, every time:

```bash
# Terminal A, on the host — validate the config BEFORE asking sshd to load it.
sshd -t && echo "CONFIG OK"
```

`sshd -t` parses the config and prints nothing on success. If it prints an error, fix the file
and run it again. Do not proceed to the reload with a failing `-t`.

```bash
# Terminal A, on the host — reload, never restart.
systemctl reload ssh
```

`reload` sends SIGHUP: the listener re-reads its config, established sessions are untouched.
`restart` tears the daemon down and brings it back, and if the new config is bad it does not
come back. Never type `restart` in this runbook.

> **Ubuntu 24.04 caveat.** This release may run sshd under socket activation, in which case
> `ssh.service` is not a long-lived daemon and `reload` on it is a no-op. Check with
> `systemctl is-active ssh.socket`. If it reports `active`, the config is re-read for every
> new connection and there is nothing to reload — but run `systemctl reload ssh` anyway; it is
> harmless either way, and the verification below is what actually tells you the change took.

```bash
# Terminal B, on your LAPTOP — a genuinely new connection.
ssh -i ~/.ssh/juli_vps_tool -o IdentitiesOnly=yes root@<host> 'id; uptime'
```

`IdentitiesOnly=yes` stops your agent from silently trying a different key and giving you a
false pass. If this prints `uid=0(root)`, the change is safe. **Only now** may you close
Terminal A.

If Terminal B fails, do not debug it in Terminal B. Go back to Terminal A — still open, still
root — and run the rollback for whatever you just changed (Part 6). Debug afterwards.

---

## Part 2 — Turn off password authentication

The change is one new file. `/etc/ssh/sshd_config.d/` is currently empty and the stock Ubuntu
`sshd_config` has its `Include /etc/ssh/sshd_config.d/*.conf` on the first line — and sshd
takes the *first* value it sees for any keyword. A drop-in therefore wins over everything in
the main file, and nothing in the main file has to be edited.

Two keywords, not one. `PasswordAuthentication no` alone is not sufficient: PAM's
keyboard-interactive path can still collect a password and hand it to sshd, which is a
different code path with a different switch. Turn off both or you have turned off neither.

```bash
cat > /etc/ssh/sshd_config.d/10-juli-hardening.conf <<'EOF'
# Issue #1448 — set explicitly rather than inherited from the OpenSSH default.
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
LogLevel VERBOSE
EOF
chmod 644 /etc/ssh/sshd_config.d/10-juli-hardening.conf
```

`PubkeyAuthentication yes` is already the effective value; writing it down means the next
person reading this file can see that key auth is intentional rather than inherited too.
`LogLevel VERBOSE` makes sshd log the fingerprint of the key used on more events than `INFO`
does — you want that in place before Part 3, and it is the only way future key attribution
stays possible.

Note `PermitRootLogin` is deliberately absent. See Part 7.

**Apply it** using the full Part 1 cycle: `sshd -t`, then `systemctl reload ssh`, then a new
session from your laptop. Do not skip the new session because the change "looks trivial."

**Verify it worked.** `sshd -T` prints the fully resolved effective config — what the daemon
actually believes, includes and defaults folded in — which is exactly what the acceptance
criterion asks for:

```bash
sshd -T | grep -E '^(passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|permitrootlogin|loglevel)'
```

Expected:

```
permitrootlogin without-password
pubkeyauthentication yes
passwordauthentication no
kbdinteractiveauthentication no
loglevel VERBOSE
```

Then prove it from the outside, which is the verification that counts. From your laptop:

```bash
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no root@<host>
```

This must fail immediately with `Permission denied (publickey).` — the server refusing to
offer password auth at all. If it instead prompts you for a password, the change did not take
effect: the drop-in is not being included, or you edited it after the reload. Go back.

**Undo.** The drop-in is the entire change, so removing it is a complete undo:

```bash
rm /etc/ssh/sshd_config.d/10-juli-hardening.conf
sshd -t && systemctl reload ssh
sshd -T | grep -E '^(passwordauthentication|loglevel)'   # back to yes / INFO
```

---

## Part 3 — Account for root's five authorized keys

Root's `authorized_keys` has five entries. One is assumed to be `juli_vps_tool`; the other four
have never been enumerated. Until each one has a name attached, "root access to production" is
a set of unknown size.

Do not paste key material into an issue, a PR, a chat, or this document. Fingerprints and
comments are safe to record and are all you need. (Public keys are not secrets in the
cryptographic sense — but the list of who can reach root is operational information, and there
is no reason to publish it.)

**Take a backup first.** Every subsequent step in this part edits the file that is currently
letting you in.

```bash
cp -a /root/.ssh/authorized_keys /root/.ssh/authorized_keys.bak.$(date +%F)
ls -l /root/.ssh/
```

The backup must be `-rw-------` (`cp -a` preserves that). If the mode drifts, sshd will refuse
the directory later.

**Enumerate.** `ssh-keygen -lf` prints one line per entry — bit length, fingerprint, comment,
algorithm — and no key material:

```bash
ssh-keygen -lf /root/.ssh/authorized_keys
```

Output looks like `256 SHA256:AbCd... some-comment (ED25519)`, in the same order as the lines
in the file, so entry *n* here is line *n* there. The comment is whatever the key's creator
typed and may be a laptop hostname, an email, an old CI job name, or nothing at all. It is a
hint, not evidence.

**Attribute by last use.** sshd logs the fingerprint of the key that authenticated each
successful login, so the journal can tell you which of the five are actually in service:

```bash
journalctl -u ssh --since '-90d' --no-pager \
  | grep -oE 'Accepted publickey for [^ ]+ from [0-9a-f.:]+ .*SHA256:[A-Za-z0-9+/]+' \
  | sed -E 's/.*from ([0-9a-f.:]+).*(SHA256:[A-Za-z0-9+\/]+)/\2 \1/' \
  | sort | uniq -c | sort -rn
```

If `journalctl` comes back thin, try the rsyslog copy, which often has a longer retention:

```bash
grep -h 'Accepted publickey' /var/log/auth.log /var/log/auth.log.1 2>/dev/null \
  | grep -oE 'SHA256:[A-Za-z0-9+/]+' | sort | uniq -c | sort -rn
zgrep -h 'Accepted publickey' /var/log/auth.log.*.gz 2>/dev/null \
  | grep -oE 'SHA256:[A-Za-z0-9+/]+' | sort | uniq -c | sort -rn
```

Read the absence of a fingerprint carefully. **A key that does not appear in the logs is not
proven unused — it is unproven either way.** Journal retention on a default Ubuntu install is
often only a few weeks, and log rotation discards the rest. "It has not been used since the
window my logs cover" is the strongest claim available, and it is a reason to ask the holder,
not a reason to assume the key is dead.

**Write the table down.** In the issue, or in a note beside this file — five rows, and no row
left blank:

| # | Type | Fingerprint (SHA256, first 12 chars) | Comment | Last seen in logs | Who holds it | Keep? |
|---|------|--------------------------------------|---------|-------------------|--------------|-------|

A key stays only if you can name a person or system that holds it *and* say why it still needs
root. "Probably mine" is not an answer; if you cannot tell, remove it — a locked-out
collaborator can send you a new public key in thirty seconds, and an unaccounted root key
cannot be un-had.

**Remove the unaccounted ones.** This is the dangerous step: deleting the wrong line locks you
out of a host whose only other door is the provider console. Confirm your own fingerprint from
"Before you start" is *not* among the lines you are about to touch, and read the file once more
before you save it.

Comment the line out rather than deleting it — `authorized_keys` ignores lines beginning with
`#`, so a comment is a full disable that leaves the evidence in place and is a one-character
undo:

```bash
# Replace <FINGERPRINT> with a fingerprint you decided to remove. Run once per key.
# Dry run first: this prints the line numbers it WOULD comment out, and changes nothing.
ssh-keygen -lf /root/.ssh/authorized_keys | grep -n '<FINGERPRINT>'
```

Then edit by hand — `vi /root/.ssh/authorized_keys`, prefix that line with `# disabled
2026-09-02 issue #1448 — ` and save. Hand-editing is deliberate here; a `sed -i` that matches
one character too few will silently mangle a key you meant to keep.

**Verify.** `authorized_keys` is read fresh on every connection, so there is nothing to reload
and the change is live the instant you save. That cuts both ways: the moment you save, a wrong
edit is already in effect. So verify immediately, from a new session on your laptop, with
Terminal A still open:

```bash
# host
ssh-keygen -lf /root/.ssh/authorized_keys    # should now list only the keys you kept
# laptop, new terminal
ssh -i ~/.ssh/juli_vps_tool -o IdentitiesOnly=yes root@<host> 'echo STILL IN'
```

**Undo.** Restore the backup:

```bash
cp -a /root/.ssh/authorized_keys.bak.$(date +%F) /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
ssh-keygen -lf /root/.ssh/authorized_keys    # five entries again
```

---

## Part 4 — fail2ban on sshd

With passwords off, a brute-force against root cannot succeed. fail2ban is still worth
installing, for two reasons: it stops the constant scan traffic from filling your auth log and
burying the lines you actually want to read in Part 3, and it is already in place before #1449
adds a named account — which is the moment the port stops being merely noisy.

```bash
apt-get update && apt-get install -y fail2ban
```

Never edit `jail.conf`; it is replaced on upgrade. All local settings go in `jail.local`.

**Know your own IP before you enable anything.** From your laptop:

```bash
curl -s https://ifconfig.me; echo
```

Put it in `ignoreip` below. It is not a substitute for the unban procedure — home IPs move —
but it removes the most likely way to lock yourself out during the ten minutes you are testing.

```bash
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
# ufw owns the filter table on this host. Let fail2ban insert ufw rules rather than
# raw iptables rules, which ufw will otherwise clobber on its next reload.
banaction = ufw
banaction_allports = ufw

[sshd]
enabled  = true
backend  = systemd
# With PasswordAuthentication off, most probes now end in a pre-auth disconnect rather
# than a failed password. "normal" mode may not count those; aggressive does.
mode     = aggressive
maxretry = 5
findtime = 10m
bantime  = 1h
ignoreip = 127.0.0.1/8 ::1 <YOUR-IP>/32
EOF
```

`banaction = ufw` matters on this host specifically. ufw owns the filter table; a fail2ban that
writes bare iptables rules has them silently discarded the next time ufw reloads, and you get a
jail that reports bans it is not enforcing.

```bash
systemctl enable --now fail2ban
systemctl status fail2ban --no-pager
fail2ban-client status sshd
```

**Verify it is actually banning, not merely running.** A green `systemctl status` proves the
daemon started; it proves nothing about whether the filter matches this host's log lines. Test
the matching against real logs:

```bash
fail2ban-regex systemd-journal /etc/fail2ban/filter.d/sshd.conf \
  --journalmatch "_SYSTEMD_UNIT=ssh.service" | tail -20
```

The `Lines: ... matched` count must be non-zero. A public port 22 sees probe traffic within
minutes, so zero matches means the filter is not reading your logs — check `backend` and
whether `ssh.service` is the right unit name on this box (it may be `ssh.socket`-spawned; try
`_COMM=sshd` as the journalmatch instead).

Then watch it work for real. Bans arrive on their own from background scan traffic:

```bash
fail2ban-client status sshd     # Currently banned / Total banned, after a few minutes
ufw status numbered | grep -i deny
```

Do not test this by hammering the port from your own laptop. If you must, do it from a machine
you do not need — a phone hotspot, a cloud shell — never from the IP holding Terminal A.

**Unban yourself.** If you do trip it:

```bash
fail2ban-client set sshd unbanip <YOUR-IP>
fail2ban-client unban --all           # everything, if you are not sure which IP
```

If you are banned and have no session at all, the ban is a firewall rule, not a config: reach
the provider console and run `fail2ban-client unban --all` there, or `systemctl stop fail2ban`
followed by `ufw reload` to clear the inserted rules.

**Undo.**

```bash
systemctl disable --now fail2ban
ufw status numbered | grep -i f2b     # confirm no leftover ban rules
apt-get remove -y fail2ban            # only if you want it gone entirely
```

**If you decide not to run fail2ban**, the acceptance criterion accepts that — but it wants the
decision written down. Record it as a comment on #1448 saying what rate-limits SSH instead
(provider-level filtering, an IP allowlist on 22, `MaxAuthTries`) and why that is enough.
An empty jail and no note is the one outcome the criterion rejects.

---

## Part 5 — Confirm the final state

Run all four. Every one should match.

```bash
sshd -T | grep -E '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication)'
ssh-keygen -lf /root/.ssh/authorized_keys | wc -l    # equals the number of rows you kept
fail2ban-client status sshd | head -5
ufw status verbose | head -10                        # still default deny (incoming)
```

Then, from the laptop, one last new session — key auth succeeds, password auth is refused:

```bash
ssh -i ~/.ssh/juli_vps_tool -o IdentitiesOnly=yes root@<host> 'echo FINAL OK'
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no root@<host>   # Permission denied (publickey).
```

Post the `sshd -T` output and the key table to #1448 and close it.

---

## Part 6 — Rollback, from one remaining session

Written for the worst realistic case: Terminal A is the only session you have, something is
wrong, and you do not yet know which change caused it. Run these in order. Each is independent;
none of them needs a second session; none of them drops the session you are typing into.

```bash
# 1. Undo the sshd config change entirely.
rm -f /etc/ssh/sshd_config.d/10-juli-hardening.conf
sshd -t && systemctl reload ssh
sshd -T | grep passwordauthentication          # expect: yes

# 2. Restore all five root keys.
ls /root/.ssh/authorized_keys.bak.*
cp -a /root/.ssh/authorized_keys.bak.<DATE> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
ssh-keygen -lf /root/.ssh/authorized_keys | wc -l    # expect: 5

# 3. Stop fail2ban and clear any bans it inserted.
systemctl stop fail2ban
ufw reload
ufw status numbered | grep -i f2b              # expect: no output

# 4. Confirm the door is open again before you close this session.
systemctl is-active ssh; ss -tlnp | grep ':22'
```

Only after step 4 shows sshd listening should you try a new session — and if it fails even
now, stop touching the host and use the provider console. Reloading sshd repeatedly while
guessing does not converge.

`systemctl reload ssh` never drops your session. `restart` might. Under rollback pressure the
temptation to type `restart` is strongest and the cost is highest.

---

## Part 7 — Not covered here

**`PermitRootLogin no`.** Deliberately out of scope. It requires a named sudo user to exist
first — setting it with no other account is exactly the lockout this runbook is built to avoid.
It belongs to epic #1449, as step (3) of the ordering in Part 0, and it only happens after the
new user's login is confirmed in a second session. `PermitRootLogin` stays at
`without-password` when you are done here, and that is the intended end state of this issue.

**Creating the named sudo user.** Also #1449. This runbook makes that change safe; it does not
make it.

**Anything about Postgres on this host.** There is none. The database is managed Supabase.
Any hardening advice you find elsewhere about `listen_addresses`, `pg_hba.conf`, or firewalling
5432 on this VPS is advice about a service that is not installed — do not act on it, and do not
open a hole to "fix" it.

**Moving SSH off port 22, or restricting 22 to an IP allowlist.** Both defensible, neither is
here. A port change is security theatre against anything that scans (which is everything), and
an allowlist against a home IP that moves is a lockout waiting for a lease renewal. If you want
either, file it and do it on its own, with the console confirmed open.

**Key rotation.** Accounting for the five keys is in scope; issuing new ones and retiring old
ones on a schedule is not. It needs a policy first, and the policy needs #1449's named accounts
to have somewhere to land.
