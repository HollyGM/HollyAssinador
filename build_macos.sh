#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
source ./_python.sh

APP_NAME="HollyAssinador"
BUNDLE_ID="com.holly.assinador"
APP_PATH="dist/${APP_NAME}.app"
VERSION="$(tr -d '[:space:]' < VERSION)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Este script precisa ser executado no macOS."
  exit 1
fi

if [[ ! -d ".venv" ]]; then
  "$(find_python)" -m venv .venv
fi

source .venv/bin/activate
if ! python -c 'import sys, tkinter; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  echo "O .venv foi criado com um Python sem tkinter (ou anterior ao 3.10)." >&2
  echo "Apague a pasta .venv e rode de novo." >&2
  exit 1
fi
echo "Python: $(python -c 'import sys; print(sys.version.split()[0])')"

python -m pip install --upgrade pip wheel
python -m pip install -r requirements.txt

# O Finder pode recriar o .DS_Store enquanto a pasta é apagada; tenta mais de uma vez.
for _ in 1 2 3; do
  rm -rf build dist "${APP_NAME}.spec" 2>/dev/null && break
  sleep 1
done
rm -rf build dist "${APP_NAME}.spec"

pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --icon assets/HollyAssinador.icns \
  --collect-all pyhanko \
  --collect-all pyhanko_certvalidator \
  --hidden-import pkcs11 \
  --collect-all pypdfium2 \
  --collect-all pypdfium2_raw \
  app.py

# O PyInstaller grava versão 0.0.0 no Info.plist; ajusta para a do arquivo VERSION
# e assina de novo (ad hoc), pois alterar o plist invalida a assinatura do bundle.
python - "$APP_PATH/Contents/Info.plist" "$APP_NAME" "$VERSION" <<'PY'
import plistlib
import sys

caminho, nome, versao = sys.argv[1:4]
with open(caminho, "rb") as f:
    dados = plistlib.load(f)
dados.update({
    "CFBundleName": nome,
    "CFBundleDisplayName": nome,
    "CFBundleShortVersionString": versao,
    "CFBundleVersion": versao,
    "LSApplicationCategoryType": "public.app-category.productivity",
})
with open(caminho, "wb") as f:
    plistlib.dump(dados, f)
PY
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --strict "$APP_PATH"

# Autotestes dentro do próprio pacote: se faltar uma biblioteca nativa, o build falha aqui.
"$APP_PATH/Contents/MacOS/$APP_NAME" --self-test

echo
echo "Aplicativo criado em:"
echo "  $(pwd)/${APP_PATH}"
echo
echo "A assinatura é ad hoc: abre neste Mac, mas em outros o Gatekeeper vai reclamar."
echo "Para distribuição, assine e notarize o .app com seu certificado Apple Developer ID."
