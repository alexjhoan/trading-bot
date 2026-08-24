import os
import json
import time
import traceback
from datetime import datetime
from typing import Any, Dict, Optional, Union

# Directorio raíz para logs de Inteligencia Artificial
IA_LOG_ROOT = "ia-log"


def _mask_sensitive_data(url: str, headers: Dict[str, str]) -> tuple[str, Dict[str, str]]:
    """Oculta parcialmente claves de API sensibles en URLs y cabeceras para logs seguros."""
    masked_url = url
    if "key=" in masked_url:
        parts = masked_url.split("key=")
        prefix = parts[0] + "key="
        key_val = parts[1].split("&")[0]
        rest = parts[1][len(key_val):] if len(parts[1]) > len(key_val) else ""
        if len(key_val) > 8:
            masked_key = key_val[:4] + "..." + key_val[-4:]
        else:
            masked_key = "***"
        masked_url = prefix + masked_key + rest

    masked_headers = dict(headers or {})
    if "Authorization" in masked_headers:
        auth_val = str(masked_headers["Authorization"])
        if auth_val.startswith("Bearer "):
            token = auth_val[7:]
            if len(token) > 8:
                masked_headers["Authorization"] = f"Bearer {token[:4]}...{token[-4:]}"
            else:
                masked_headers["Authorization"] = "Bearer ***"

    return masked_url, masked_headers


class AILogger:
    """
    Gestor de logs de depuración para Inteligencia Artificial.
    Estructura organizada por semanas y días:
    ia-log/
      └── semana_WW_YYYY/
            └── YYYY-MM-DD.log
    """

    def __init__(self, root_dir: str = IA_LOG_ROOT):
        self.root_dir = root_dir

    def get_log_filepath(self, dt: Optional[datetime] = None) -> str:
        """Calcula y asegura la ruta del archivo de log diario dentro de la carpeta semanal correspondiente."""
        if dt is None:
            dt = datetime.now()

        # ISO Week number (%V) y año (%Y)
        week_num = dt.strftime("%V")
        year_str = dt.strftime("%Y")
        week_folder_name = f"semana_{week_num}_{year_str}"
        week_folder_path = os.path.join(self.root_dir, week_folder_name)

        # Crear carpeta semanal si no existe
        os.makedirs(week_folder_path, exist_ok=True)

        # Nombre del archivo diario: YYYY-MM-DD.log
        day_filename = f"{dt.strftime('%Y-%m-%d')}.log"
        return os.path.join(week_folder_path, day_filename)

    def log_interaction(
        self,
        event_type: str,
        symbol: str,
        provider: str,
        model: str,
        endpoint: str,
        request_headers: Dict[str, str],
        request_payload: Union[Dict[str, Any], str],
        response_status: int,
        duration_ms: float,
        raw_response: Optional[str] = None,
        parsed_response: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Registra una interacción completa con la API de IA (payload, request, headers, respuesta y errores)
        en el archivo de log del día actual.
        """
        now = datetime.now()
        filepath = self.get_log_filepath(now)
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        masked_endpoint, masked_headers = _mask_sensitive_data(endpoint, request_headers)

        # Formatear el payload de solicitud de manera legible
        if isinstance(request_payload, str):
            try:
                formatted_payload = json.dumps(json.loads(request_payload), indent=2, ensure_ascii=False)
            except Exception:
                formatted_payload = request_payload
        else:
            formatted_payload = json.dumps(request_payload, indent=2, ensure_ascii=False)

        # Formatear la respuesta de la IA
        if parsed_response:
            formatted_parsed = json.dumps(parsed_response, indent=2, ensure_ascii=False)
        else:
            formatted_parsed = "N/A"

        banner = "=" * 80
        divider = "-" * 80

        log_entry = [
            f"\n{banner}",
            f"🕒 [{timestamp_str}] EVENTO: {event_type} | PAR: {symbol or 'GLOBAL'} | MODELO: {model} ({provider})",
            banner,
            f"📍 Endpoint: {masked_endpoint}",
            f"⏱️  Duración: {duration_ms:.2f} ms | Estado HTTP: {response_status}",
            f"🔑 Cabeceras: {json.dumps(masked_headers, ensure_ascii=False)}",
        ]

        if extra_meta:
            log_entry.append(f"📊 Metadatos Adicionales: {json.dumps(extra_meta, ensure_ascii=False)}")

        log_entry.extend([
            f"\n📥 --- [PAYLOAD ENVIADO A LA IA] ---",
            formatted_payload,
            f"\n📤 --- [RESPUESTA RAW DE LA API] ---",
            raw_response if raw_response else "(Sin cuerpo raw)",
            f"\n🧠 --- [RESPUESTA PROCESADA / VEREDICTO IA] ---",
            formatted_parsed,
        ])

        if error:
            log_entry.extend([
                f"\n❌ --- [ERROR / EXCEPCIÓN DETECTADA] ---",
                str(error),
            ])

        log_entry.append(f"{divider}\n")
        full_text = "\n".join(log_entry)

        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(full_text)
        except Exception as file_err:
            print(f"[AILogger ERROR] No se pudo escribir en {filepath}: {file_err}")

        return filepath


# Instancia global reutilizable
ai_logger = AILogger()
