if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi
export ZSH="$HOME/.oh-my-zsh"

export EDITOR=nvim

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

plugins=(git zsh-autosuggestions zsh-syntax-highlighting fast-syntax-highlighting tmuxinator)

source "$ZSH/oh-my-zsh.sh"
# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh
eval "$(zoxide init --cmd cd zsh)"

if command -v atuin &> /dev/null; then
  # . "$HOME/.atuin/bin/env"
  eval "$(atuin init zsh --disable-up-arrow)"
fi

export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

export PATH="$HOME/.local/share/gem/ruby/3.3.0/bin:$PATH"


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
