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

alias lg="lazygit"

HISTFILE=~/.history
HISTSIZE=10000
SAVEHIST=50000

# VI Mode!!!
# bindkey jj vi-cmd-mode

### FZF ###
export FZF_DEFAULT_COMMAND='fd --type f --hidden --follow'
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh
# navigation
cx() { cd "$@" && l; }
fcd() { cd "$(find . -type d -not -path '*/.*' | fzf)" && l; }
f() { echo "$(find . -type f -not -path '*/.*' | fzf)" | pbcopy }
fv() { nvim "$(find . -type f -not -path '*/.*' | fzf)" }

# Eza
alias l="eza -l --icons --git -a"
alias lt="eza --tree --level=2 --long --icons --git"
alias ltree="eza --tree --level=2  --icons --git"

ZSH_THEME="powerlevel10k/powerlevel10k"

plugins=(git zsh-autosuggestions zsh-syntax-highlighting fast-syntax-highlighting tmuxinator)

source $ZSH/oh-my-zsh.sh
# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh
eval "$(zoxide init --cmd cd zsh)"



# . "$HOME/.atuin/bin/env"
eval "$(atuin init zsh --disable-up-arrow)"
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

export PATH="$HOME/.local/share/gem/ruby/3.3.0/bin:$PATH"
# fpath+=(~/.config/tmuxinator/completions)
# autoload -Uz compinit && compinit
