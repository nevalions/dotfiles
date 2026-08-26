if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi
export ZSH="$HOME/.oh-my-zsh"

export EDITOR=nvim

# COSMIC + NVIDIA Wayland
export COSMIC_DISABLE_DIRECT_SCANOUT=true
export WLR_NO_HARDWARE_CURSORS=1
export GBM_BACKEND=nvidia-drm
export __GLX_VENDOR_LIBRARY_NAME=nvidia

alias v="nvim"
alias vs="sudo -E nvim"

alias cl="clear"
alias mux="tmuxinator"
alias b="bat"
alias bl="bat --language=log"
alias bn="bat --style=numbers,grid"
alias bs="sudo bat"

# Git
alias gc="git commit -m"
alias gca="git commit -a -m"
alias gP="git push origin HEAD"
alias gp="git pull origin"
alias gst="git status"
alias glog="git log --graph --topo-order --pretty='%w(100,0,6)%C(yellow)%h%C(bold)%C(black)%d %C(cyan)%ar %C(green)%an%n%C(bold)%C(white)%s %N' --abbrev-commit"
alias gdiff="git diff"
alias gco="git checkout"
alias gb='git branch'
alias gba='git branch -a'
alias gadd='git add'
alias ga='git add -p'
alias gr='git remote'

unalias gcoall 2>/dev/null
unalias gres 2>/dev/null

confirm_action() {
  local prompt="$1"
  local answer
  read "answer?$prompt [y/N]: "
  [[ "$answer" =~ ^[Yy]$ ]]
}

gcoall() {
  confirm_action 'Discard all unstaged tracked changes in this repo?' || return 1
  git restore --worktree -- .
}

gres() {
  if [[ "$*" == *--hard* ]]; then
    confirm_action 'Run git reset --hard and lose local changes?' || return 1
  fi
  git reset "$@"
}

alias k="kubectl"
alias ka="kubectl apply -f"
alias kg="kubectl get"
alias kd="kubectl describe"
alias kdel="kubectl delete"
alias kl="kubectl logs"
alias kgpo="kubectl get pod"
alias kgd="kubectl get deployments"
alias kc="kubectx"
alias kns="kubens"
alias kl="kubectl logs -f"
alias ke="kubectl exec -it"
alias kcns='kubectl config set-context --current --namespace'
alias podname=''

alias tr4="tree -a -L 4 -I '.git'"
alias tr3="tree -a -L 3 -I '.git'"
alias tr2="tree -a -L 2 -I '.git'"
alias tr1="tree -a -L 1 -I '.git'"

alias obo='cd ~/vault && FILE=$(find . -type f -name "*.md" | fzf --preview "bat --color=always {}" | tr -d "\n"); [ -n "$FILE" ] && nvim "$FILE"'

alias lg="lazygit"

# Optional monitoring and disk tools
has() {
  command -v "$1" >/dev/null 2>&1
}

if has btm; then
  alias bt='btm'
fi

if has dust; then
  alias dux='dust'
fi

if has dua; then
  alias duai='dua i'
fi

if has iotop; then
  alias io='sudo iotop -oPa'
fi

# Safer delete defaults for interactive shells
alias rm='rm -I --preserve-root'

if has trash-put; then
  alias del='trash-put'
fi

trash_empty() {
  confirm_action 'Empty all files from Trash?' || return 1

  if has trash-empty; then
    trash-empty
  elif has gio; then
    gio trash --empty
  else
    echo 'No trash empty command found (install trash-cli or gio).' >&2
    return 127
  fi
}

alias tempty='trash_empty'

HISTFILE=~/.history
HISTSIZE=10000
SAVEHIST=50000

# VI Mode!!!
# bindkey jj vi-cmd-mode
# Eza
alias l="eza -l --icons --git -a"
alias lt="eza --tree --level=1 --long --icons --git -a"
alias lt2="eza --tree --level=2 --long --icons --git -a"
alias lt3="eza --tree --level=3 --long --icons --git -a"
alias ltree="eza --tree --level=2  --icons --git -a"


### FZF ###
export FZF_DEFAULT_COMMAND="fd --type f --exclude .git --exclude $HOME/share --follow"
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

find_with_exclusions() {
    find "$1" -type "$2" \
        -not -path '*/.git/*' \
        -not -path './share/*' \
        -not -path './.local/*' \
        -not -path '*/yay/*' \
        -not -path '*/.cache/*' \
        -not -path '*/venv/*' \
        -not -path '*/.mozilla/*' \
        -not -path '*/.var/*' \
        -not -path '*/.oh-my-zsh/*' \
        -not -path '*__pycache__*' \
        -not -path '*/.npm/*' \
        -not -path "$HOME/share/*" \
        -not -path "$HOME/.local/*"
}

if_dir_lt() {
  local dir="$1"
  if [ -n "$dir" ]; then
    cd "$dir" && lt
  fi
}

# navigation
cx() { cd "$@" && ls -l; }
fhd() { 
  local dir=$(find_with_exclusions "$HOME" "d" | fzf)
  if_dir_lt "$dir"
}
fcd() {
  local dir=$(find_with_exclusions "." "d" | fzf)
  if_dir_lt "$dir"
}
f() { 
  local selected_file=$(find_with_exclusions "$(pwd)" "f" | fzf) 
  if [ -n "$selected_file" ]; then 
    echo "$selected_file" | wl-copy
  fi
}
fv() { 
  local selected_file=$(find_with_exclusions "." "f" | fzf) 
  if [ -n "$selected_file" ]; then
    nvim "$selected_file"
  fi
}

ZSH_THEME="powerlevel10k/powerlevel10k"

# git-auto-fetch: background `git fetch` so the p10k vcs segment can show
# ahead/behind without a manual fetch. Neither git nor p10k ever touches the
# network on its own. Disable per repo with `git-auto-fetch` (toggles
# .git/NO_AUTO_FETCH).
GIT_AUTO_FETCH_INTERVAL=300  # seconds between fetches per repo (default 60)

plugins=(git git-auto-fetch zsh-autosuggestions zsh-syntax-highlighting fast-syntax-highlighting tmuxinator)

source "$ZSH/oh-my-zsh.sh"
# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh

# Print a git status line when entering a repo, so `cd` alone shows ahead/behind
# without opening lazygit. p10k cannot do this on its own: its vcs segment is
# only recomputed in precmd, and `p10k display -r` merely repaints the cached
# prompt string, so a fetch that lands after the prompt is drawn stays invisible
# until the next command. This hook fetches (bounded, rate-limited) *before*
# printing, so the numbers shown are current. No p10k internals are used.
#
# Knobs: GIT_AUTO_FETCH_INTERVAL (shared with the git-auto-fetch plugin),
# GIT_CD_FETCH_TIMEOUT (hard cap on how long `cd` may block on the network),
# GIT_CD_STATUS=0 to disable. Per-repo opt-out: `git-auto-fetch` (NO_AUTO_FETCH)
# suppresses the fetch; the status line still prints from local refs.
if [[ -o interactive ]]; then
  zmodload zsh/datetime
  zmodload -F zsh/stat b:zstat
  autoload -Uz add-zsh-hook

  : ${GIT_CD_FETCH_TIMEOUT:=3}
  : ${GIT_CD_STATUS:=1}
  typeset -g _gcr_last=''

  _git_cd_report() {
    emulate -L zsh
    setopt local_options no_ksh_arrays extended_glob

    (( GIT_CD_STATUS )) || return 0

    local gitdir
    gitdir=$(command git rev-parse --git-dir 2>/dev/null) || { _gcr_last=''; return 0 }
    gitdir=${gitdir:A}
    # Report once per repo: moving between subdirs of the same repo stays quiet.
    [[ $gitdir == $_gcr_last ]] && return 0
    _gcr_last=$gitdir

    # Refresh remote refs first, honouring the plugin's rate limit and opt-out.
    if [[ -w $gitdir && ! -f $gitdir/NO_AUTO_FETCH ]] &&
       [[ ! -f $gitdir/FETCH_LOG || -w $gitdir/FETCH_LOG ]]; then
      local -i lastrun=$(zstat +mtime "$gitdir/FETCH_LOG" 2>/dev/null || echo 0)
      if (( EPOCHSECONDS - lastrun >= ${GIT_AUTO_FETCH_INTERVAL:-60} )); then
        date -R >! "$gitdir/FETCH_LOG"
        GIT_SSH_COMMAND="command ssh -o BatchMode=yes -o ConnectTimeout=3" \
        GIT_TERMINAL_PROMPT=0 \
          command timeout $GIT_CD_FETCH_TIMEOUT \
            git fetch --all --quiet >>"$gitdir/FETCH_LOG" 2>&1
      fi
    fi

    # One porcelain=v2 call for branch, upstream, ahead/behind and file states.
    local -i staged=0 unstaged=0 unmerged=0 untracked=0 ahead=0 behind=0
    local head='' upstream='' line xy
    while IFS= read -r line; do
      case $line in
        '# branch.head '*)     head=${line#'# branch.head '} ;;
        '# branch.upstream '*) upstream=${line#'# branch.upstream '} ;;
        '# branch.ab '*)
          local ab=(${=line#'# branch.ab '})
          ahead=${ab[1]#+} behind=${ab[2]#-} ;;
        [12]' '*)
          xy=${${(s: :)line}[2]}
          [[ $xy[1] != '.' ]] && (( staged++ ))
          [[ $xy[2] != '.' ]] && (( unstaged++ )) ;;
        'u '*) (( unmerged++ )) ;;
        '? '*) (( untracked++ )) ;;
      esac
    done < <(command git --no-optional-locks status --porcelain=v2 --branch 2>/dev/null)

    [[ -n $head ]] || return 0

    local -i stashes=$(command git rev-list --walk-reflogs --count refs/stash 2>/dev/null || print 0)

    # In-progress operations, which porcelain=v2 does not report.
    local action=''
    if [[ -d $gitdir/rebase-merge || -d $gitdir/rebase-apply ]]; then action=rebase
    elif [[ -f $gitdir/MERGE_HEAD ]];        then action=merge
    elif [[ -f $gitdir/CHERRY_PICK_HEAD ]];  then action=cherry-pick
    elif [[ -f $gitdir/REVERT_HEAD ]];       then action=revert
    elif [[ -f $gitdir/BISECT_LOG ]];        then action=bisect
    fi

    local out="%F{blue}${${gitdir:h}:t}%f"
    [[ $head == '(detached)' ]] &&
      out+=" %F{yellow}@$(command git rev-parse --short HEAD 2>/dev/null)%f" ||
      out+=" %F{76}$head%f"
    [[ -z $upstream ]] && out+=" %F{242}(no upstream)%f"
    (( behind ))    && out+=" %F{cyan}⇣$behind%f"
    (( ahead ))     && out+=" %F{cyan}⇡$ahead%f"
    (( staged ))    && out+=" %F{green}+$staged%f"
    (( unstaged ))  && out+=" %F{178}!$unstaged%f"
    (( untracked )) && out+=" %F{76}?$untracked%f"
    (( unmerged ))  && out+=" %F{red}~$unmerged%f"
    (( stashes ))   && out+=" %F{242}*$stashes%f"
    [[ -n $action ]] && out+=" %F{red}$action%f"
    (( staged + unstaged + untracked + unmerged == 0 )) && out+=" %F{green}✔%f"

    print -P -- " $out"
  }

  add-zsh-hook chpwd _git_cd_report
fi
if command -v atuin &> /dev/null; then
  # Per-host init flags (--disable-ai on Ansible-managed servers) are written
  # to ~/.config/atuin/init-flags by roles/atuin. This file is shared by every
  # machine, so they cannot be hardcoded here. Blank lines are dropped so an
  # empty flags file is harmless.
  atuin_flags=(--disable-up-arrow)
  if [[ -r ~/.config/atuin/init-flags ]]; then
    atuin_flags+=(${(f)"$(<~/.config/atuin/init-flags)"})
  fi
  atuin_flags=(${atuin_flags:#})
  eval "$(atuin init zsh $atuin_flags)"
  unset atuin_flags
fi

export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

export PATH="$(ruby -e 'print Gem.user_dir')/bin:$PATH"


# Load Angular CLI autocompletion.
if command -v ng &> /dev/null; then
source <(ng completion script)
fi

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion

export PATH=$PATH:$HOME/go/bin
export PATH="$HOME/.local/bin:$PATH"

# opencode
export PATH="$HOME/.opencode/bin:$PATH"

if command -v direnv >/dev/null 2>&1; then
  eval "$(direnv hook zsh)"
fi

# Claude Code MCP env vars
[[ -f ~/.env.claude ]] && source ~/.env.claude

# opencode wrapper that works with direnv exec
opencode() {
  local env_dir="$HOME/dotfiles/opencode/.config/opencode"
  local bin

  # Find the real opencode executable path (avoid recursion)
  bin="$(whence -p opencode 2>/dev/null)"

  if [[ -z "$bin" ]]; then
    echo "opencode: executable not found in PATH" >&2
    return 127
  fi

  if command -v direnv >/dev/null 2>&1 && [[ -d "$env_dir" ]]; then
    direnv exec "$env_dir" "$bin" "$@"
  else
    "$bin" "$@"
  fi
}

# ESP-IDF
export IDF_PATH=/home/linroot/esp-idf
export PATH="$IDF_PATH/tools:$PATH"

# ESP-IDF environment activation
idf() {
  source "$IDF_PATH/export.sh"
}

unset ESPPORT
# export ESPPORT=/dev/ttyUSB0

# Claude Code env
if [ -f "$HOME/.env.claude" ]; then
  set -a
  source "$HOME/.env.claude"
  set +a
fi

export _ZO_DOCTOR=0
eval "$(zoxide init --cmd cd zsh)"

# bun completions
[ -s "/home/linroot/.bun/_bun" ] && source "/home/linroot/.bun/_bun"

# bun
export BUN_INSTALL="$HOME/.bun"
export PATH="$BUN_INSTALL/bin:$PATH"

# k8s: merge existing kubeconfigs (skip missing so kubectl/k9s don't error)
kubeconfigs=""
for f in "$HOME/.kube/config" "$HOME/.kube/vas-tunnel.conf"; do
  [ -r "$f" ] && kubeconfigs="${kubeconfigs:+$kubeconfigs:}$f"
done
[ -n "$kubeconfigs" ] && export KUBECONFIG="$kubeconfigs"
unset kubeconfigs f
