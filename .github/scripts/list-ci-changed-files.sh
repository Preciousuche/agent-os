#!/usr/bin/env bash
#
# Write the list of files a CI run should classify to <output-file>.
#
# For a pull_request event that means the base..head diff. Everything else
# (push, workflow_dispatch, anything new) writes the `.ci/run-all` sentinel
# that classify-ci-changes.sh reads as "run every job".
#
# The diff is best-effort by design. `actions/checkout` fetches only
# `refs/heads/*` and `refs/tags/*`; when it cannot resolve `refs/pull/<n>/merge`
# — a fork PR whose workflow run is released after the PR was merged and
# closed, for one — it silently falls back to the default branch and the head
# sha is nowhere in the local object database. Classification is an
# optimisation, so an unresolvable sha must widen the run to everything rather
# than exit 128 and fail CI on a step that decides nothing.
set -euo pipefail

event_name="${1-}"
base_sha="${2-}"
head_sha="${3-}"
output_file="${4:?usage: list-ci-changed-files.sh <event> <base-sha> <head-sha> <output-file>}"

run_all() {
  printf '.ci/run-all\n' > "${output_file}"
}

# Is the object present locally *and* a commit we can diff?
have_commit() {
  local sha="${1}"
  [[ -n "${sha}" ]] || return 1
  git cat-file -e "${sha}^{commit}" 2>/dev/null
}

# Pull a single commit the checkout did not fetch. Harmless when it fails —
# the caller falls back to running everything.
try_fetch_commit() {
  local sha="${1}"
  [[ -n "${sha}" ]] || return 1
  git fetch --no-tags --quiet origin "${sha}" 2>/dev/null || return 1
  have_commit "${sha}"
}

resolve_commit() {
  local sha="${1}"
  have_commit "${sha}" || try_fetch_commit "${sha}"
}

if [[ "${event_name}" != "pull_request" ]]; then
  run_all
else
  # A plain string, not an array: bash 3.2 treats an empty array as unset
  # under `set -u`, and these scripts also run under the Windows Git Bash.
  missing=""
  for sha in "${base_sha}" "${head_sha}"; do
    resolve_commit "${sha}" || missing="${missing} ${sha:-<empty>}"
  done

  if [[ -n "${missing}" ]]; then
    echo "::warning::Cannot resolve pull request commit(s):${missing}." \
      "Running every CI job instead of classifying the diff."
    run_all
  elif ! git diff --name-only "${base_sha}" "${head_sha}" > "${output_file}"; then
    echo "::warning::git diff ${base_sha}..${head_sha} failed." \
      "Running every CI job instead of classifying the diff."
    run_all
  fi
fi

echo "Changed files:"
sed 's/^/  /' "${output_file}"
