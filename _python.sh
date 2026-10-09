#!/bin/bash
# Usado por run_dev.sh e build_macos.sh (via "source").
#
# Escolhe um Python 3.10+ que tenha tkinter. O python3 mais novo do Homebrew
# (3.13+) não inclui o tkinter; nesse caso o app abriria e falharia na hora.
# Para forçar um interpretador: PYTHON_BIN=/caminho/python3.12 ./build_macos.sh

_python_ok() {
  "$1" -c 'import sys, tkinter; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1
}

find_python() {
  local candidate
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if command -v "$PYTHON_BIN" >/dev/null 2>&1 && _python_ok "$PYTHON_BIN"; then
      command -v "$PYTHON_BIN"
      return 0
    fi
    echo "PYTHON_BIN=$PYTHON_BIN não é um Python 3.10+ com tkinter." >&2
    return 1
  fi
  for candidate in python3.12 python3.13 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && _python_ok "$candidate"; then
      command -v "$candidate"
      return 0
    fi
  done
  cat >&2 <<'MSG'
Nenhum Python 3.10+ com tkinter foi encontrado.
Instale um com:  brew install python@3.12 python-tk@3.12
MSG
  return 1
}
