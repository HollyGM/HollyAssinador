from __future__ import annotations

import getpass
import sys
from pathlib import Path

import pkcs11
from pkcs11 import Attribute, ObjectClass


def main():
    if len(sys.argv) != 2:
        print("Uso: python probe_pkcs11.py /caminho/modulo.dylib")
        raise SystemExit(2)

    module = Path(sys.argv[1]).expanduser().resolve()
    if not module.exists():
        raise SystemExit(f"Módulo não encontrado: {module}")

    lib = pkcs11.lib(str(module))
    slots = list(lib.get_slots(token_present=True))

    if not slots:
        print("Nenhum token detectado pelo módulo.")
        return

    print(f"Tokens detectados: {len(slots)}")
    for i, slot in enumerate(slots, 1):
        token = slot.get_token()
        print()
        print(f"[{i}] Token label: {token.label}")
        print(f"    Fabricante: {token.manufacturer_id}")
        print(f"    Modelo: {token.model}")
        print(f"    Serial: {token.serial}")

    print()
    selected = input("Número do token para inspecionar [1]: ").strip() or "1"
    token = slots[int(selected) - 1].get_token()
    pin = getpass.getpass("PIN (deixe vazio se o módulo autenticar externamente): ")

    kwargs = {}
    if pin:
        kwargs["user_pin"] = pin

    try:
        with token.open(**kwargs) as session:
            print("\nCertificados:")
            found = False
            for obj in session.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE}):
                found = True
                label = obj.get(Attribute.LABEL, "")
                obj_id = obj.get(Attribute.ID, b"")
                print(f"  label={label!r} id={bytes(obj_id).hex() if obj_id else ''}")
            if not found:
                print("  (nenhum certificado listado)")

            print("\nChaves privadas:")
            found = False
            for obj in session.get_objects({Attribute.CLASS: ObjectClass.PRIVATE_KEY}):
                found = True
                label = obj.get(Attribute.LABEL, "")
                obj_id = obj.get(Attribute.ID, b"")
                print(f"  label={label!r} id={bytes(obj_id).hex() if obj_id else ''}")
            if not found:
                print("  (nenhuma chave privada listada)")
    except Exception as exc:
        raise SystemExit(f"Falha ao abrir/inspecionar token: {exc}") from exc


if __name__ == "__main__":
    main()
