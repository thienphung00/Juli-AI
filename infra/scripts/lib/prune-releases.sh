#!/usr/bin/env bash
# Shared release-worktree retention for deploy-release.sh and deploy-demo-release.sh.
#
# Why this is shared rather than inlined per script: ~/releases/<short-sha>/ is a
# single pool used by every lane (App Review api+web, Demo, and Landing when it
# ships). A prune that only knows about its own lane will delete a worktree
# another lane is live on. That is not hypothetical -- on 2026-08-07 an App
# Review deploy removed the worktree ~/releases/demo-current pointed at while
# juli-demo was serving from it. The Demo kept answering 200 for HTML while
# `next start` returned 500 for every hashed chunk that was still in the build
# manifest but gone from disk, so demo.app-juli.com rendered with no CSS and no
# JavaScript until the next deploy.
#
# Retention model -- keep a release if ANY of these hold, delete otherwise:
#   1. Some service is live on it: it is the target of a ~/releases/*current
#      symlink (current, demo-current, landing-current, ...). Derived from the
#      symlinks themselves so a new lane needs no change here.
#   2. It is among the newest <keep> entries of a deploy-history log. This is
#      what keeps `rollback-release.sh` / `rollback-demo-release.sh` able to
#      resolve a target -- without it, pruning can delete the very release a
#      rollback would return to.
#   3. It is the release being deployed right now (passed in explicitly; it is
#      not written to the history log until after the health check passes).
#
# Ordering note: candidates are never ranked by path. Release directories are
# named by short SHA, which is hex -- lexicographic order carries no relation to
# deploy time, so the previous `sort -r | tail -n +N` selected an arbitrary
# subset and could delete the newest release while keeping ancient ones.
#
# Portability: sourced by scripts that run on the VPS (bash 5) but also executed
# directly by tests on macOS (bash 3.2). No mapfile, no associative arrays.
#
# shellcheck shell=bash

# Resolve a path to its physical location, following symlinks. Empty output if
# the path does not exist.
_prune_resolve() {
    local path="$1"
    [ -e "${path}" ] || return 0
    if [ -d "${path}" ]; then
        (cd "${path}" 2>/dev/null && pwd -P)
    else
        printf '%s\n' "${path}"
    fi
}

# Release dirs a service is currently serving from -- one per *current symlink.
_prune_live_dirs() {
    local releases_root="$1" link target
    for link in "${releases_root}"/*current; do
        [ -L "${link}" ] || continue
        target="$(_prune_resolve "${link}")"
        if [ -n "${target}" ]; then printf '%s\n' "${target}"; fi
    done
}

# Newest <keep> distinct release dirs per deploy-history log. Both deploy and
# ROLLBACK-TO lines carry the release dir in field 3.
_prune_recent_dirs() {
    local releases_root="$1" keep="$2" log
    for log in "${releases_root}"/*deploy-history.log; do
        [ -f "${log}" ] || continue
        awk '$3 != "" { print $3 }' "${log}" \
            | awk '{ line[NR] = $0 }
                   END { for (i = NR; i > 0; i--) if (!seen[line[i]]++) print line[i] }' \
            | head -n "${keep}"
    done
}

# prune_release_worktrees <canonical_root> <releases_root> <keep> [release_dir]
#
# Removes every release worktree under <releases_root> that is not protected by
# the retention model above. Prints one KEEP/REMOVE line per release so the
# decision is auditable in deploy logs.
prune_release_worktrees() {
    local canonical_root="$1"
    local releases_root="$2"
    local keep="$3"
    local release_dir="${4:-}"

    local log logs_found=0
    for log in "${releases_root}"/*deploy-history.log; do
        if [ -f "${log}" ]; then logs_found=1; fi
    done
    if [ "${logs_found}" -eq 0 ]; then
        echo "SKIP: no deploy-history log under ${releases_root} — refusing to prune" \
            "without a recency signal (nothing deleted)."
        return 0
    fi

    local protected_raw protected="" entry resolved
    protected_raw="$(
        _prune_live_dirs "${releases_root}"
        _prune_recent_dirs "${releases_root}" "${keep}"
        if [ -n "${release_dir}" ]; then _prune_resolve "${release_dir}"; fi
    )"
    while IFS= read -r entry; do
        [ -n "${entry}" ] || continue
        resolved="$(_prune_resolve "${entry}")"
        [ -n "${resolved}" ] || continue
        protected="${protected}${resolved}"$'\n'
    done <<EOF
${protected_raw}
EOF

    local releases_real
    releases_real="$(_prune_resolve "${releases_root}")"

    local candidate candidate_real
    while IFS= read -r candidate; do
        [ -n "${candidate}" ] || continue
        candidate_real="$(_prune_resolve "${candidate}")"
        [ -n "${candidate_real}" ] || continue

        # Only ever touch direct children of the releases root.
        case "${candidate_real}" in
            "${releases_real}"/*) ;;
            *) continue ;;
        esac
        if [ "${candidate_real}" = "${releases_real}" ]; then continue; fi

        if printf '%s' "${protected}" | grep -Fxq "${candidate_real}"; then
            echo "KEEP:   ${candidate_real}"
            continue
        fi

        echo "REMOVE: ${candidate_real}"
        git -C "${canonical_root}" worktree remove --force "${candidate_real}" \
            || rm -rf "${candidate_real}"
    done <<EOF
$(git -C "${canonical_root}" worktree list --porcelain | awk '/^worktree /{ print $2 }')
EOF
}
