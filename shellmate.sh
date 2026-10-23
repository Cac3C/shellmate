# ShellMate bash 集成：source 本文件后使用 shm
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  __SHM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  __SHM_ROOT="$PWD"
fi

shm() {
  PYTHONPATH="$__SHM_ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 -m shellmate "$@"
}

__shm_ctrl_g() {
  if [ -n "${READLINE_LINE:-}" ]; then
    READLINE_LINE="shm $READLINE_LINE"
  else
    READLINE_LINE="shm repl"
  fi
  READLINE_POINT=${#READLINE_LINE}
}

bind -x '"\C-g":__shm_ctrl_g' 2>/dev/null || true
