#!/usr/bin/env bash
input=$(cat)

cwd_full=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // ""')
dir=$(basename "$cwd_full")
model=$(echo "$input" | jq -r '.model.display_name // ""')
ctx_size=$(echo "$input" | jq -r '.context_window.context_window_size // 0')
used_pct=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
transcript=$(echo "$input" | jq -r '.transcript_path // ""')

fmt_tok() {
  local n="${1:-0}"
  if [ "$n" -ge 1000000 ]; then
    awk -v n="$n" 'BEGIN{printf "%.1fM", n/1000000}'
  elif [ "$n" -ge 1000 ]; then
    echo "$(( n / 1000 ))k"
  else
    echo "$n"
  fi
}

main_tok=0
if [ -n "$transcript" ] && [ -f "$transcript" ]; then
  hash=$(printf '%s' "$transcript" | md5sum | awk '{print $1}')
  cache="/tmp/claude-statusline-tokens-${USER}-${hash}"
  size=$(stat -c %s "$transcript" 2>/dev/null || echo 0)
  cached_size=-1
  cached_tok=0
  if [ -f "$cache" ]; then
    read -r cached_size cached_tok < "$cache"
  fi
  if [ "$size" = "$cached_size" ]; then
    main_tok=$cached_tok
  else
    main_tok=$(jq -r 'select(.message.usage) | .message.usage
      | (.input_tokens // 0)
      + (.cache_creation_input_tokens // 0)
      + (.cache_read_input_tokens // 0)
      + (.output_tokens // 0)' "$transcript" 2>/dev/null \
      | awk '{s+=$1} END{print s+0}')
    printf '%s %s\n' "$size" "$main_tok" > "$cache"
  fi
fi

sub_tok=0
tokens_file="$cwd_full/memory/tokens.jsonl"
if [ -f "$tokens_file" ]; then
  sub_tok=$(jq -r 'select(.tokens > 0) | .tokens' "$tokens_file" 2>/dev/null \
    | awk '{s+=$1} END{print s+0}')
fi

total_tok=$(( main_tok + sub_tok ))

# Derive used tokens from percentage and max size
total=$(( ctx_size * used_pct / 100 ))

# Format as K tokens
if [ "$total" -ge 1000 ]; then
  ctx="$(( total / 1000 ))k"
else
  ctx="$total"
fi
if [ "$ctx_size" -ge 1000 ]; then
  ctx_max="$(( ctx_size / 1000 ))k"
else
  ctx_max="$ctx_size"
fi

# ANSI colors
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
RED=$'\033[31m'
RESET=$'\033[0m'

# Color thresholds based on token count
if [ "$total" -ge 750000 ]; then
  color="$RED"
elif [ "$total" -ge 500000 ]; then
  color="$YELLOW"
else
  color="$GREEN"
fi

# Progress bar
bar_width=10
filled=$(( used_pct * bar_width / 100 ))
empty=$(( bar_width - filled ))
bar=""
for ((i=0; i<filled; i++)); do bar+="▓"; done
for ((i=0; i<empty; i++)); do bar+="░"; done

# Warning symbol
warn=""
if [ "$total" -ge 500000 ]; then
  warn=" ⚠"
fi

status="$dir"

if [ -n "$model" ]; then
  status="$status | $model"
fi

# Peak hours: 5:00 AM – 11:00 AM Pacific Time
pt_hour=$(TZ='America/Los_Angeles' date +%H)
pt_min=$(TZ='America/Los_Angeles' date +%M)
peak=""
if [ "$pt_hour" -ge 5 ] && [ "$pt_hour" -lt 11 ]; then
  mins_left=$(( (11 - pt_hour - 1) * 60 + (60 - pt_min) ))
  h=$(( mins_left / 60 ))
  m=$(( mins_left % 60 ))
  if [ "$h" -gt 0 ]; then
    peak=" | ${YELLOW}PEAK ${h}h${m}m left${RESET}"
  else
    peak=" | ${YELLOW}PEAK ${m}m left${RESET}"
  fi
else
  # Time until peak starts (5:00 AM PT)
  if [ "$pt_hour" -ge 11 ]; then
    mins_to=$(( (24 - pt_hour + 5 - 1) * 60 + (60 - pt_min) ))
  else
    mins_to=$(( (5 - pt_hour - 1) * 60 + (60 - pt_min) ))
  fi
  h=$(( mins_to / 60 ))
  m=$(( mins_to % 60 ))
  if [ "$h" -gt 0 ]; then
    peak=" | ${GREEN}peak in ${h}h${m}m${RESET}"
  else
    peak=" | ${GREEN}peak in ${m}m${RESET}"
  fi
fi

spent=""
if [ "$total_tok" -gt 0 ]; then
  spent_str="Σ $(fmt_tok "$total_tok") (main $(fmt_tok "$main_tok") sub $(fmt_tok "$sub_tok"))"
  spent=" | $spent_str"
fi

printf "%s | ${color}[%s] %s/%s${warn}${RESET}%s%b" "$status" "$bar" "$ctx" "$ctx_max" "$spent" "$peak"
