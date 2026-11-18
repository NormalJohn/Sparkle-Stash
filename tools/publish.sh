#!/usr/bin/env bash
set -euo pipefail
candidate=$(realpath "$1")
version=$(cat "$candidate/version")
[[ "$version" =~ ^[a-f0-9]{64}$ ]]
[[ -s "$candidate/Sparkle-Stash.stoverride" ]]
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
if [[ -n "$(git ls-remote --heads origin published)" ]]; then
    git fetch --depth 1 origin published
    git switch -C published FETCH_HEAD
else
    git switch --orphan published
fi
if [[ -f version ]] && [[ "$(cat version)" == "$version" ]]; then
    echo "Published files already match the tested candidate."
    exit 0
fi
mkdir -p "versions/$version"
cp -R "$candidate"/. "versions/$version/"
cp "$candidate"/*.stoverride "$candidate"/{version,upstream.json,LICENSE,LICENSE.fflate} .
git add -- .
git commit -m "Publish tested candidate ${version:0:12}"
git push origin HEAD:refs/heads/published
