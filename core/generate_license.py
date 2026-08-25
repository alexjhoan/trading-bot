#!/usr/bin/env python3
"""
=============================================================================
🔑 GENERADOR DE LICENCIAS CRIPTOGRÁFICAS - QUANT TRADING BOT
=============================================================================
Este script es de uso exclusivo del DESARROLLADOR / ADMINISTRADOR.
Permite generar llaves de validación criptográficas (HMAC-SHA256) vinculadas
al Hardware ID de la máquina del cliente, fecha de expiración y cuentas MT5.

Uso:
  1. Modo Interactivo:
     python generate_license.py

  2. Modo Línea de Comandos:
     py generate_license.py --key-id "KID-eyJod2lkIjoiMDNCQUY2NDZFMzY2NjAyNzVFMDlGRjdBOTIwNUIzNjUyQjlDRjc4MzhBNzJEQTU5Rjg3MTVGREIzM0MzMUIyMiIsImFjYyI6NDMxNTQ4OTN9" --client "alex" --days 30
=============================================================================
"""
import os
import sys
import argparse
from datetime import datetime, timedelta, timezone

# Resolución robusta de rutas para ejecutarse desde raíz o desde dentro de /core
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
core_dir = os.path.join(current_dir, "core") if not current_dir.endswith("core") else current_dir
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)

try:
    from core.licensing import (
        get_hardware_id,
        generate_client_key_id,
        parse_client_key_id,
        generate_license_token,
        verify_license_token,
        MASTER_LICENSE_SECRET
    )
except ImportError:
    from licensing import (
        get_hardware_id,
        generate_client_key_id,
        parse_client_key_id,
        generate_license_token,
        verify_license_token,
        MASTER_LICENSE_SECRET
    )


def interactive_mode():
    print("\n" + "=" * 65)
    print(" 🔐 GENERADOR DE LICENCIAS CRIPTOGRÁFICAS - QUANT TRADING BOT")
    print("=" * 65)

    local_key_id = generate_client_key_id()
    print(f"\n👉 Pega el KEY ID que te envió el cliente:")
    print(f"   (o presiona ENTER para probar con el KEY ID de esta PC)")
    key_input = input("KEY ID > ").strip()

    if not key_input:
        key_input = local_key_id

    machine_id, extracted_account = parse_client_key_id(key_input)

    print(f"\n  🔍 [DATOS EXTRAÍDOS DEL KEY ID]:")
    print(f"  ├─ Hardware ID: {machine_id}")
    if extracted_account > 0:
        print(f"  └─ Cuenta MT5:  #{extracted_account} (Detectada automáticamente)")
    else:
        print(f"  └─ Cuenta MT5:  Cualquiera / No vinculada")

    allowed_accounts = [extracted_account] if extracted_account > 0 else []

    print("\n👉 Nombre o Identificador del Cliente (ej: Usuario1):")
    client_name = input("Nombre > ").strip() or "Trader"

    print("\n👉 Duración de la Licencia:")
    print("  [1] 30 días (1 Mes)")
    print("  [2] 90 días (3 Meses)")
    print("  [3] 180 días (6 Meses)")
    print("  [4] 365 días (1 Año)")
    print("  [5] Fecha personalizada (YYYY-MM-DD)")
    choice = input("Opción (1-5, Default: 1) > ").strip()

    now_utc = datetime.now(timezone.utc)
    if choice == "2":
        exp_date = (now_utc + timedelta(days=90)).strftime("%Y-%m-%d")
    elif choice == "3":
        exp_date = (now_utc + timedelta(days=180)).strftime("%Y-%m-%d")
    elif choice == "4":
        exp_date = (now_utc + timedelta(days=365)).strftime("%Y-%m-%d")
    elif choice == "5":
        print("Ingresa fecha límite (Formato: YYYY-MM-DD):")
        exp_input = input("Fecha > ").strip()
        exp_date = exp_input if exp_input else (now_utc + timedelta(days=90)).strftime("%Y-%m-%d")
    else:
        exp_date = (now_utc + timedelta(days=30)).strftime("%Y-%m-%d")

    default_acc_text = str(extracted_account) if extracted_account > 0 else "Cualquiera"
    print(f"\n👉 Cuentas MT5 Autorizadas [Default actual: {default_acc_text}]:")
    print("   (Presiona ENTER para aceptar o escribe cuentas separadas por comas)")
    acc_input = input("Cuentas MT5 > ").strip()
    if acc_input:
        allowed_accounts = []
        for acc in acc_input.replace(";", ",").split(","):
            acc_str = acc.strip()
            if acc_str.isdigit():
                allowed_accounts.append(int(acc_str))

    token = generate_license_token(
        machine_id=machine_id,
        client_name=client_name,
        expires_at_iso=exp_date,
        allowed_accounts=allowed_accounts
    )

    print("\n" + "=" * 65)
    print(" ✅ LLAVE DE LICENCIA GENERADA CON ÉXITO")
    print("=" * 65)
    print(f"Cliente:      {client_name}")
    print(f"Hardware ID:  {machine_id}")
    print(f"Expiración:   {exp_date}")
    print(f"Cuentas MT5:  {allowed_accounts if allowed_accounts else 'Todas'}")
    print("-" * 65)
    print("🔑 COPIA Y ENTREGA ESTA LLAVE AL CLIENTE:")
    print(f"\n{token}\n")
    print("=" * 65)


def cli_mode():
    parser = argparse.ArgumentParser(description="Generador de Licencias Quant Trading Bot")
    parser.add_argument("--key-id", type=str, help="KEY ID completo enviado por el cliente (KID-...)")
    parser.add_argument("--machine-id", type=str, help="Hardware ID de la PC del cliente")
    parser.add_argument("--client", type=str, default="Cliente", help="Nombre del cliente")
    parser.add_argument("--days", type=int, default=90, help="Días de vigencia a partir de hoy")
    parser.add_argument("--expires", type=str, help="Fecha de expiración exacta (YYYY-MM-DD)")
    parser.add_argument("--accounts", type=str, help="Cuentas MT5 permitidas separadas por comas")
    parser.add_argument("--get-my-id", action="store_true", help="Muestra el KEY ID de esta máquina")

    args = parser.parse_args()

    if args.get_my_id:
        print(f"KEY ID: {generate_client_key_id()}")
        return

    machine_id = ""
    allowed_accounts = []

    if args.key_id:
        machine_id, extracted_acc = parse_client_key_id(args.key_id)
        if extracted_acc > 0:
            allowed_accounts.append(extracted_acc)
    elif args.machine_id:
        machine_id = args.machine_id
    else:
        machine_id = get_hardware_id()

    if args.expires:
        expires_at = args.expires
    else:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=args.days)).strftime("%Y-%m-%d")

    if args.accounts:
        allowed_accounts = []
        for acc in args.accounts.replace(";", ",").split(","):
            acc_str = acc.strip()
            if acc_str.isdigit():
                allowed_accounts.append(int(acc_str))

    token = generate_license_token(
        machine_id=machine_id,
        client_name=args.client,
        expires_at_iso=expires_at,
        allowed_accounts=allowed_accounts
    )
    print(token)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cli_mode()
    else:
        interactive_mode()
