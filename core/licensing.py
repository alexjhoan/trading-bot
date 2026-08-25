import os
import sys
import json
import time
import hmac
import base64
import hashlib
import platform
import subprocess
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

# Clave Secreta Maestra para la firma criptográfica HMAC-SHA256 de las licencias
# Esta clave es privada y asegura que ningún usuario pueda fabricar una licencia válida
MASTER_LICENSE_SECRET = os.environ.get("QUANT_BOT_LICENSE_SECRET", "QUANT_BOT_SECURE_KEY_v2_9981A7F2D04C")

STAMP_FILE = ".license_stamp"


def get_hardware_id() -> str:
    """
    Obtiene el Hardware ID único de la PC combinando el UUID de la placa base
    y el número de serie del disco principal con hash SHA-256.
    """
    system_name = platform.system()
    uuid_str = ""
    disk_serial_str = ""

    if system_name == "Windows":
        # 1. Obtener UUID de la Placa Base mediante PowerShell WMI/CIM
        try:
            cmd_uuid = ["powershell", "-NoProfile", "-Command", "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID"]
            res_uuid = subprocess.run(cmd_uuid, capture_output=True, text=True, timeout=4)
            if res_uuid.returncode == 0 and res_uuid.stdout.strip():
                uuid_str = res_uuid.stdout.strip()
        except Exception:
            pass

        # Fallback para UUID usando WMIC si PowerShell falla
        if not uuid_str:
            try:
                cmd_wmic = ["wmic", "csproduct", "get", "uuid"]
                res_wmic = subprocess.run(cmd_wmic, capture_output=True, text=True, timeout=4)
                lines = [line.strip() for line in res_wmic.stdout.splitlines() if line.strip() and "UUID" not in line.upper()]
                if lines:
                    uuid_str = lines[0]
            except Exception:
                pass

        # 2. Obtener Número de Serie del Disco Principal
        try:
            cmd_disk = ["powershell", "-NoProfile", "-Command", "(Get-CimInstance -ClassName Win32_PhysicalMedia | Select-Object -First 1).SerialNumber"]
            res_disk = subprocess.run(cmd_disk, capture_output=True, text=True, timeout=4)
            if res_disk.returncode == 0 and res_disk.stdout.strip():
                disk_serial_str = res_disk.stdout.strip()
        except Exception:
            pass

        if not disk_serial_str:
            try:
                cmd_disk_wmic = ["wmic", "diskdrive", "get", "serialnumber"]
                res_disk_wmic = subprocess.run(cmd_disk_wmic, capture_output=True, text=True, timeout=4)
                lines = [line.strip() for line in res_disk_wmic.stdout.splitlines() if line.strip() and "SERIALNUMBER" not in line.upper()]
                if lines:
                    disk_serial_str = lines[0]
            except Exception:
                pass

    elif system_name == "Linux":
        # En Linux leer machine-id o producto UUID
        try:
            for path in ["/etc/machine-id", "/var/lib/dbus/machine-id", "/sys/class/dmi/id/product_uuid"]:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        content = f.read().strip()
                        if content:
                            uuid_str = content
                            break
        except Exception:
            pass

    # Fallback universal si WMI/archivos no están disponibles
    if not uuid_str:
        import uuid
        uuid_str = f"NODE_{uuid.getnode()}"

    if not disk_serial_str:
        disk_serial_str = f"ARCH_{platform.machine()}_{platform.processor()}"

    raw_id = f"{uuid_str.strip().upper()}-{disk_serial_str.strip().upper()}"
    raw_bytes = raw_id.encode("utf-8")
    hardware_hash = hashlib.sha256(raw_bytes).hexdigest().upper()
    return hardware_hash


def generate_client_key_id(account_login: Optional[int] = None) -> str:
    """
    Genera un KEY ID unificado para el cliente que empaqueta automáticamente
    el Hardware ID de su PC y su número de cuenta MT5.
    Formato: KID-<Base64Url(JSON({hwid, acc}))>
    """
    hwid = get_hardware_id()
    login_val = 0
    if account_login and int(account_login) > 0:
        login_val = int(account_login)
    else:
        # Intentar obtener de MT5 si está inicializado
        try:
            import MetaTrader5 as mt5
            acc = mt5.account_info()
            if acc and acc.login:
                login_val = int(acc.login)
        except Exception:
            pass

    payload = {
        "hwid": hwid,
        "acc": login_val
    }
    payload_json = json.dumps(payload, separators=(',', ':'))
    b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")
    return f"KID-{b64}"


def parse_client_key_id(key_id_str: str) -> Tuple[str, int]:
    """
    Desempaqueta un KEY ID del cliente para extraer el Hardware ID y la Cuenta MT5.
    Soporta formatos:
      1. KID-<Base64Url>
      2. Formato directo HWID#ACC o HWID:ACC
      3. HWID simple (sin cuenta)
    Retorna:
      (machine_id: str, account_login: int)
    """
    if not key_id_str:
        return "", 0

    clean = key_id_str.strip()

    # Formato 1: KID-<Base64Url>
    if clean.startswith("KID-"):
        raw_b64 = clean[4:].strip()
        try:
            padded = raw_b64 + "=" * ((4 - len(raw_b64) % 4) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
            data = json.loads(decoded)
            hwid = str(data.get("hwid", "")).strip().upper()
            acc = int(data.get("acc", 0))
            return hwid, acc
        except Exception:
            pass

    # Formato 2: HWID#ACCOUNT o HWID:ACCOUNT
    if "#" in clean:
        parts = clean.split("#", 1)
        acc = int(parts[1].strip()) if parts[1].strip().isdigit() else 0
        return parts[0].strip().upper(), acc

    # Formato 3: Solo HWID
    return clean.upper(), 0


def get_verified_utc_timestamp() -> Tuple[float, str]:
    """
    Obtiene la fecha/hora UTC actual validada con protección anti-tampering (reloj atrasado).
    Realiza una comprobación ligera contra servidores de tiempo y el archivo de stamp local.
    """
    system_now = time.time()
    network_time = None

    # Intentar obtener hora de red mediante un HEAD HTTP ultraligero
    try:
        req = urllib.request.Request("http://worldtimeapi.org/api/timezone/Etc/UTC", headers={"User-Agent": "QuantBot/2.0"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "unixtime" in data:
                network_time = float(data["unixtime"])
    except Exception:
        pass

    # Comprobación contra el registro de última fecha local (Anti-Clock Tampering)
    last_known_timestamp = 0.0
    if os.path.exists(STAMP_FILE):
        try:
            with open(STAMP_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    last_known_timestamp = float(content)
        except Exception:
            pass

    effective_now = network_time if network_time is not None else system_now

    # Si la fecha del sistema o de red es menor que el último registro guardado,
    # significa que el usuario atrasó el reloj de Windows para saltarse la expiración
    if effective_now < (last_known_timestamp - 300):  # Margen de 5 minutos
        return effective_now, "FRAUDE_RELOJ: Se detectó que el reloj del sistema fue retrasado."

    # Actualizar stamp con la mayor fecha conocida
    try:
        new_stamp = max(effective_now, last_known_timestamp)
        with open(STAMP_FILE, "w", encoding="utf-8") as f:
            f.write(str(new_stamp))
    except Exception:
        pass

    return effective_now, "OK"


def generate_license_token(
    machine_id: str,
    client_name: str,
    expires_at_iso: str,
    allowed_accounts: List[int],
    secret_key: str = MASTER_LICENSE_SECRET
) -> str:
    """
    Genera un Token de Licencia criptográficamente firmado (HMAC-SHA256).
    Formato: Base64Url(JSON_PAYLOAD).Base64Url(HMAC_SHA256_SIGNATURE)
    """
    payload = {
        "machine_id": machine_id.strip().upper(),
        "client_name": client_name.strip(),
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "expires_at": expires_at_iso.strip(),
        "allowed_accounts": [int(acc) for acc in allowed_accounts]
    }

    payload_json = json.dumps(payload, separators=(',', ':'), sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")

    # Calcular firma HMAC-SHA256
    signature = hmac.new(
        secret_key.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")

    return f"{payload_b64}.{sig_b64}"


def verify_license_token(
    token: str,
    current_account_login: Optional[int] = None,
    current_machine_id: Optional[str] = None,
    secret_key: str = MASTER_LICENSE_SECRET
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Valida la integridad criptográfica, vigencia temporal, Machine ID y cuenta MT5 del token.

    Retorna:
      (is_valid: bool, status_message: str, payload_data: dict)
    """
    if not token or not token.strip():
        return False, "❌ No se ha configurado ninguna clave de licencia.", {}

    cleaned_token = token.strip()
    parts = cleaned_token.split(".")
    if len(parts) != 2:
        return False, "❌ La clave de licencia no tiene un formato válido.", {}

    payload_b64, sig_b64 = parts[0], parts[1]

    # 1. Verificar Firma Criptográfica HMAC-SHA256
    try:
        expected_sig = hmac.new(
            secret_key.encode("utf-8"),
            payload_b64.encode("utf-8"),
            hashlib.sha256
        ).digest()
        expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode("utf-8").rstrip("=")

        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            return False, "❌ Clave de licencia no válida o alterada (Firma digital incorrecta).", {}
    except Exception as e:
        return False, f"❌ Error verificando firma criptográfica: {e}", {}

    # 2. Decodificar Payload
    try:
        # Añadir padding Base64 si falta
        padded_b64 = payload_b64 + "=" * ((4 - len(payload_b64) % 4) % 4)
        payload_json = base64.urlsafe_b64decode(padded_b64).decode("utf-8")
        payload: Dict[str, Any] = json.loads(payload_json)
    except Exception as e:
        return False, f"❌ Error decodificando datos de la licencia: {e}", {}

    # 3. Validar Machine ID (Hardware Binding)
    actual_machine_id = current_machine_id or get_hardware_id()
    licensed_machine_id = str(payload.get("machine_id", "")).strip().upper()

    # Si la licencia no es wildcard ("*"), debe coincidir exactamente con el Hardware ID de la PC
    if licensed_machine_id != "*" and licensed_machine_id != actual_machine_id.upper():
        return False, f"❌ Licencia no autorizada para esta PC. (Hardware ID no coincide).", payload

    # 4. Validar Fecha de Expiración y Protección contra reloj atrasado
    expires_at_str = payload.get("expires_at", "")
    if not expires_at_str:
        return False, "❌ La licencia no tiene fecha de expiración especificada.", payload

    now_ts, clock_msg = get_verified_utc_timestamp()
    if clock_msg.startswith("FRAUDE_RELOJ"):
        return False, f"❌ {clock_msg}", payload

    try:
        # Soportar formato YYYY-MM-DD o ISO
        if len(expires_at_str) == 10:
            exp_dt = datetime.strptime(expires_at_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        else:
            exp_dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))

        exp_ts = exp_dt.timestamp()
        if now_ts > exp_ts:
            return False, f"❌ Licencia vencida (Expiró el {expires_at_str}). Contacte al desarrollador para renovar.", payload

        remaining_days = max(0, int((exp_ts - now_ts) / 86400))
    except Exception as e:
        return False, f"❌ Formato de fecha de expiración inválido: {e}", payload

    # 5. Validar Cuenta de Trading MT5 Autorizada (Account Login Binding)
    allowed_accounts = payload.get("allowed_accounts", [])
    if allowed_accounts and isinstance(allowed_accounts, list) and len(allowed_accounts) > 0:
        if current_account_login is not None and current_account_login > 0:
            if current_account_login not in allowed_accounts:
                return False, f"❌ Cuenta MT5 #{current_account_login} no autorizada en esta licencia (Permitidas: {allowed_accounts}).", payload

    client_name = payload.get("client_name", "Cliente")
    return True, f"✅ Licencia activa para '{client_name}' (Válida hasta {expires_at_str} | {remaining_days} días restantes).", payload
