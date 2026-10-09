"""Configurações lembradas entre execuções.

Só guarda dados não sensíveis (caminhos, labels, motivo, local, TSA). Senha do
A1 e PIN do A3 nunca são gravados.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SETTINGS_PATH = Path.home() / "Library" / "Application Support" / "HollyAssinador" / "config.json"

FIELDS: dict[str, type] = {
    "cert_type": str,
    "a1_file": str,
    "a3_module": str,
    "a3_token_label": str,
    "a3_cert_label": str,
    "a3_key_label": str,
    "reason": str,
    "location": str,
    "tsa_url": str,
    "appearance": str,
}


def load(path: Path | None = None) -> dict:
    path = path or SETTINGS_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    values = {
        key: data[key]
        for key, kind in FIELDS.items()
        if isinstance(data.get(key), kind)
    }
    if values.get("cert_type") not in (None, "A1", "A3"):
        del values["cert_type"]
    if values.get("appearance") not in (None, "invisible", "footer"):
        del values["appearance"]
    return values


def save(values: dict, path: Path | None = None) -> None:
    path = path or SETTINGS_PATH
    data = {key: values[key] for key in FIELDS if key in values}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
