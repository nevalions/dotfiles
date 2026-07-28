#!/usr/bin/env bash
#
# stop-stacks.sh — stop the docker containers a herdr `run` tab leaves behind.
#
# Closing a workspace kills its pane processes and nothing else: everything
# started with `docker run -d` or `compose up -d` belongs to the docker daemon,
# not to the pane, so the stacks keep running (and keep their RAM) until they
# are stopped by hand. This is that hand.
#
# Driven by the "Stop Local Stacks" quick action (prefix Down), which passes one
# of the keys below. Also usable directly:
#
#   stop-stacks.sh stills-bank
#   stop-stacks.sh all --dry-run
#
# `stop`, not `down`: containers and volumes stay, so the next `up` is fast and
# no database is thrown away. Use `docker compose down` by hand for that.
#
# Not -e: a stack that is absent or already stopped must not abort the rest.
set -uo pipefail

CODE="${CODE_DIR:-$HOME/code}"
DRY_RUN=0
TARGET=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        *) TARGET="$arg" ;;
    esac
done

STOPPED=()
SKIPPED=()

run() {
    if (( DRY_RUN )); then
        echo "would run: $*"
        return 0
    fi
    "$@" >/dev/null 2>&1
}

# Is any container of this compose project running? Avoids `compose stop`
# printing errors for a stack that was never brought up.
compose_running() {
    local dir="$1" file="${2:-}" out
    [[ -d "$dir" ]] || return 1
    if [[ -n "$file" ]]; then
        out="$(cd "$dir" && docker compose -f "$file" ps -q 2>/dev/null)"
    else
        out="$(cd "$dir" && docker compose ps -q 2>/dev/null)"
    fi
    [[ -n "$out" ]]
}

stop_compose() {
    local label="$1" dir="$2" file="${3:-}"
    if ! compose_running "$dir" "$file"; then
        SKIPPED+=("$label")
        return
    fi
    if [[ -n "$file" ]]; then
        run env -C "$dir" docker compose -f "$file" stop
    else
        run env -C "$dir" docker compose stop
    fi
    STOPPED+=("$label")
}

stop_container() {
    local label="$1" name="$2"
    if [[ -z "$(docker ps -q -f "name=^${name}$" 2>/dev/null)" ]]; then
        SKIPPED+=("$label")
        return
    fi
    run docker stop "$name"
    STOPPED+=("$label")
}

stop_stills_bank()  { stop_compose "stills-bank"  "$CODE/stills-bank"; }
stop_news_writer()  { stop_compose "news-writer"  "$CODE/news-writer"; }
stop_news()         { stop_compose "news"         "$CODE/news-backend" "docker-compose.dev.yml"; }
stop_stream()       { stop_container "stream"     "stream-cms-pg"; }

# statsboard has two: the redis the run pane starts with a bare `docker run -d`,
# and a test database from docker-compose.test-db-only.yml that is started by
# hand. Both are stopped together — neither survives a workspace close for a
# reason worth keeping.
stop_statsboard() {
    stop_container "statsboard redis" "statsboards-redis"
    stop_compose "statsboard test db" "$CODE/statsboard/statsboards-backend" "docker-compose.test-db-only.yml"
}

case "$TARGET" in
    stills-bank) stop_stills_bank ;;
    news-writer) stop_news_writer ;;
    news)        stop_news ;;
    statsboard)  stop_statsboard ;;
    stream)      stop_stream ;;
    all|"")
        stop_stills_bank
        stop_news_writer
        stop_news
        stop_statsboard
        stop_stream
        ;;
    *)
        echo "unknown stack: $TARGET" >&2
        echo "expected one of: stills-bank news-writer news statsboard stream all" >&2
        exit 2
        ;;
esac

summary="stopped: ${STOPPED[*]:-none}"
[[ ${#SKIPPED[@]} -gt 0 ]] && summary="$summary | already down: ${SKIPPED[*]}"
echo "$summary"

# The quick action runs through `sh -c` with nowhere to show stdout, so the
# result is reported as a notification instead.
if (( ! DRY_RUN )) && command -v herdr >/dev/null 2>&1; then
    herdr notification show "Local stacks stopped" --body "$summary" >/dev/null 2>&1 || true
fi
