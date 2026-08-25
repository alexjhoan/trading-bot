import os
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import re

NEWS_CACHE_FILE = "calendar_news.json"
FOREX_FACTORY_CALENDAR_URL = "https://nss.forexfactory.com/website/v1/weekly-calendar.json"

# Mapeo de prefijos o sufijos a códigos de divisas estándar
STANDARD_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "CNY", "XAU", "XAG", "BTC", "ETH"]


def extract_currencies_from_symbol(symbol: str) -> List[str]:
    """
    Extrae las divisas relevantes de un símbolo de trading usando Regex.
    Soporta Forex (EURUSD, EURJPY_r), Índices (US30_r, GER40, UK100, JP225), Metales y Criptos.
    """
    if not symbol:
        return ["USD"]

    clean_sym = symbol.upper()
    # Remover sufijos de broker comunes
    clean_sym = re.sub(
        r"([._-])?(RAW|PRO|ECN|STP|CASH|PLUS|MINI|MICRO|STD|ZERO|VIP|[a-z])$",
        "",
        clean_sym,
        flags=re.IGNORECASE,
    )
    clean_sym = clean_sym.replace("/", "").replace("\\", "").strip()

    currencies = []

    # 1. Índices bursátiles mundiales
    if any(k in clean_sym for k in ["US30", "US500", "US100", "NAS100", "SPX", "DJ30", "DOW", "NDX"]):
        currencies.append("USD")
    elif any(k in clean_sym for k in ["GER40", "GER30", "DE40", "DE30", "DAX", "EU50", "FRA40"]):
        currencies.append("EUR")
    elif any(k in clean_sym for k in ["UK100", "FTSE"]):
        currencies.append("GBP")
    elif any(k in clean_sym for k in ["JP225", "NIKKEI", "JPN225"]):
        currencies.append("JPY")
    elif any(k in clean_sym for k in ["AUS200", "ASX200"]):
        currencies.append("AUD")
    elif any(k in clean_sym for k in ["HK50", "HSI", "CHINA50"]):
        currencies.extend(["USD", "CNY"])

    # 2. Metales, Energías y Cripto
    if any(k in clean_sym for k in ["XAU", "GOLD", "XAG", "SILVER", "OIL", "WTI", "BRENT", "BTC", "ETH", "SOL", "XRP"]):
        if "USD" not in currencies:
            currencies.append("USD")

    # 3. Pares Forex estándar de 6 letras (ej. EURUSD, AUDNZD, EURJPY)
    match_forex = re.match(r"^([A-Z]{3})([A-Z]{3})", clean_sym)
    if match_forex:
        c1, c2 = match_forex.group(1), match_forex.group(2)
        if c1 in STANDARD_CURRENCIES and c1 not in currencies:
            currencies.append(c1)
        if c2 in STANDARD_CURRENCIES and c2 not in currencies:
            currencies.append(c2)

    # 4. Chequeo general de divisas estándar
    for c in STANDARD_CURRENCIES:
        if c in clean_sym and c not in currencies:
            currencies.append(c)

    return currencies if currencies else ["USD", "EUR"]


class NewsManager:
    """
    Gestor de Calendario Económico en Tiempo Real.
    Descarga y almacena en caché local (calendar_news.json) el calendario semanal de Forex Factory.
    Filtra noticias por divisa, impacto y proximidad temporal.
    """

    def __init__(self, cache_file: str = NEWS_CACHE_FILE, cache_ttl_seconds: int = 1800):
        self.cache_file = cache_file
        self.cache_ttl_seconds = cache_ttl_seconds  # 30 minutos de TTL
        self.last_fetch_time: float = 0.0
        self.events_cache: List[Dict[str, Any]] = []
        self._load_cached_news()

    def _load_cached_news(self) -> None:
        """Carga los datos del archivo local si existe."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.events_cache = data
                        self.last_fetch_time = os.path.getmtime(self.cache_file)
            except Exception as e:
                print(f"[NewsManager] Error leyendo caché local: {e}")

    def fetch_calendar(self, force: bool = False) -> Tuple[bool, str]:
        """
        Descarga el calendario semanal de Forex Factory y lo guarda en calendar_news.json.
        """
        now = time.time()
        if not force and self.events_cache and (now - self.last_fetch_time) < self.cache_ttl_seconds:
            return True, f"Caché vigente ({len(self.events_cache)} eventos)"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        try:
            req = urllib.request.Request(FOREX_FACTORY_CALENDAR_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.getcode() in (200, 201):
                    raw_content = resp.read().decode("utf-8")
                    data = json.loads(raw_content)
                    if isinstance(data, list):
                        self.events_cache = data
                        self.last_fetch_time = now
                        with open(self.cache_file, "w", encoding="utf-8") as f:
                            f.write(raw_content)
                        return True, f"Calendario actualizado exitosamente ({len(data)} eventos)"
                    else:
                        return False, "Formato de calendario no esperado"
        except Exception as e:
            # Si falla la red o DNS, mantener la caché local
            if self.events_cache:
                return True, f"Usando caché local previa tras fallo de red: {e}"
            return False, f"Fallo al obtener calendario económico: {e}"

    def get_upcoming_events_for_symbol(
        self,
        symbol: str,
        window_minutes_ahead: int = 45,
        window_minutes_behind: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Devuelve eventos económicos relevantes para las divisas del par dentro de una ventana temporal.
        """
        # Refrescar silenciosamente si la caché expiró
        if not self.events_cache or (time.time() - self.last_fetch_time) > self.cache_ttl_seconds:
            self.fetch_calendar(force=False)

        if not self.events_cache:
            return []

        currencies = extract_currencies_from_symbol(symbol)
        now_dt = datetime.now(timezone.utc)
        relevant_events = []

        for ev in self.events_cache:
            country = str(ev.get("country", "")).upper()
            if country not in currencies:
                continue

            # Parsear fecha del evento
            date_str = ev.get("date", "")
            if not date_str:
                continue

            try:
                # Soporta formatos ISO como "2026-08-24T14:30:00-04:00" o "2026-08-24T18:30:00Z"
                if "Z" in date_str:
                    event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                else:
                    event_dt = datetime.fromisoformat(date_str)

                # Normalizar a UTC si tiene offset
                event_utc = event_dt.astimezone(timezone.utc)
                diff_minutes = (event_utc - now_dt).total_seconds() / 60.0

                # Comprobar si está dentro de la ventana de evaluación
                if -window_minutes_behind <= diff_minutes <= window_minutes_ahead:
                    ev_copy = dict(ev)
                    ev_copy["minutes_until"] = round(diff_minutes, 1)
                    relevant_events.append(ev_copy)
            except Exception:
                continue

        # Ordenar por cercanía en el tiempo
        relevant_events.sort(key=lambda x: abs(x.get("minutes_until", 999)))
        return relevant_events

    def format_news_summary_for_ai(self, symbol: str) -> str:
        """
        Genera una síntesis en una sola línea optimizada para tokens de IA.
        Ejemplo: "[ALERTA] Habla Powell (USD) en 12 min - Impacto HIGH"
        """
        events = self.get_upcoming_events_for_symbol(symbol, window_minutes_ahead=45, window_minutes_behind=15)
        if not events:
            # Buscar el próximo evento relevante en el día
            currencies = extract_currencies_from_symbol(symbol)
            return f"Sin noticias de alto impacto en los próximos 45 min para {', '.join(currencies)}."

        # Buscar eventos de alto impacto primero
        high_impact = [e for e in events if str(e.get("impact", "")).lower() in ("high", "alto")]
        if high_impact:
            ev = high_impact[0]
            mins = ev.get("minutes_until", 0)
            title = ev.get("title", "Noticia de alto impacto")
            country = ev.get("country", "USD")
            if mins > 0:
                return f"[ALERTA] {title} ({country}) en {int(mins)} min - Impacto HIGH."
            else:
                return f"[ALERTA RECIENTE] {title} ({country}) publicada hace {abs(int(mins))} min - Impacto HIGH."

        # Si no hay alto impacto, revisar medio
        medium_impact = [e for e in events if str(e.get("impact", "")).lower() in ("medium", "medio")]
        if medium_impact:
            ev = medium_impact[0]
            mins = ev.get("minutes_until", 0)
            title = ev.get("title", "Noticia")
            country = ev.get("country", "USD")
            return f"[PRECAUCIÓN] {title} ({country}) en {int(mins)} min - Impacto MEDIUM."

        return f"Sin noticias de alto impacto en los próximos 45 min."


# Instancia global
news_manager = NewsManager()
