"""Generador de eventos sintéticos diarios para ShopStream.

Cada llamada a `generate_day()` produce ~800k eventos (configurable) para una
fecha específica, con distribuciones realistas:

- Picos de tráfico en hora pico (12-14h y 19-22h UTC).
- Distribución mobile/desktop/tablet sesgada al móvil.
- Embudo de conversión (page_view → product_view → cart_event → transaction).
- ~25% de sesiones son bounce (un único page_view).
- ~0.5% de sesiones son anómalas (volumen extremo, ritmo bot-like).

El generador es **streaming**: escribe línea a línea para no agotar RAM.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from data_generation.catalog import Catalog
from data_generation.schemas import (
    BROWSERS,
    CART_ACTIONS,
    DEVICE_TYPES,
    ELEMENT_TYPES,
    PAGE_TYPES,
)

# ---------------------------------------------------------------------------
# Parámetros de distribución (ajustables por configuración)
# ---------------------------------------------------------------------------

DEFAULT_TARGET_EVENTS = 800_000

# Probabilidades del embudo (cada nivel condicionado al anterior)
P_NOT_BOUNCE = 0.75            # 25% sesiones bounce
P_REACH_PRODUCT_VIEW = 0.40    # de las no-bounce, qué fracción llega a product_view
P_REACH_CART = 0.30            # de las que ven producto, qué fracción agrega al carrito
P_PURCHASE = 0.40              # de las que llegan al carrito, qué fracción compra

# Probabilidad de eventos paralelos durante la sesión
P_CLICK_PER_PAGE_VIEW = 0.6    # clics promedio por page_view
P_SEARCH_PER_SESSION = 0.35    # sesiones con al menos una búsqueda

# Anomalías
P_ANOMALOUS_SESSION = 0.005    # ~0.5% sesiones anómalas

# Distribución de horas (peso por hora 0-23): picos 12-14h y 19-22h
HOUR_WEIGHTS = [
    0.5, 0.3, 0.2, 0.15, 0.15, 0.2, 0.4, 0.7, 1.0, 1.3, 1.6, 1.8,
    2.2, 2.3, 2.0, 1.7, 1.6, 1.7, 2.0, 2.4, 2.3, 1.9, 1.3, 0.8,
]

PAGE_TYPE_BY_FUNNEL_STAGE = {
    "landing": ["home", "category", "search"],
    "browsing": ["category", "search", "product"],
    "consideration": ["product", "category"],
    "purchase": ["cart", "checkout"],
}

REFERRERS = [
    None, None, None,  # null = direct, peso alto
    "https://google.com/",
    "https://google.com/search",
    "https://facebook.com/",
    "https://instagram.com/",
    "https://twitter.com/",
    "https://shopstream.com/email-campaign",
]


@dataclass
class GeneratorConfig:
    target_events: int = DEFAULT_TARGET_EVENTS
    seed: int = 42
    sessions_per_active_user_lambda: float = 1.2  # poisson
    active_user_fraction: float = 0.50  # 50% del catálogo activo cada día


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _event_id(rng: random.Random) -> str:
    return "E" + "%016x" % rng.getrandbits(64)


def _session_id(rng: random.Random) -> str:
    return "S" + "%012x" % rng.getrandbits(48)


def _rng_hex(rng: random.Random, nbytes: int) -> str:
    """Hex determinista basado en el rng (sin os.urandom)."""
    return "%0*x" % (nbytes * 2, rng.getrandbits(nbytes * 8))


def _iso(ts: datetime) -> str:
    """Formatea timestamp UTC al formato ISO-8601 con 'Z' final."""
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond:06d}Z"


def _sample_hour(rng: random.Random) -> int:
    return rng.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]


def _poisson(rng: random.Random, lam: float) -> int:
    """Implementación simple de Poisson (Knuth)."""
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def _funnel_stage_for_session(rng: random.Random) -> str:
    """Decide cuán profundo entra la sesión en el embudo."""
    if rng.random() >= P_NOT_BOUNCE:
        return "bounce"
    if rng.random() >= P_REACH_PRODUCT_VIEW:
        return "browsing"
    if rng.random() >= P_REACH_CART:
        return "consideration"
    if rng.random() >= P_PURCHASE:
        return "cart_only"
    return "purchase"


def _page_url(page_type: str, rng: random.Random, product_id: str | None = None) -> str:
    if page_type == "home":
        return "https://shopstream.com/"
    if page_type == "category":
        cat = rng.choice(
            ["electronics", "clothing", "home", "sports", "books", "beauty", "toys", "food"]
        )
        return f"https://shopstream.com/category/{cat}"
    if page_type == "search":
        return "https://shopstream.com/search?q=" + _rng_hex(rng, 4)
    if page_type == "product" and product_id:
        return f"https://shopstream.com/product/{product_id}"
    if page_type == "cart":
        return "https://shopstream.com/cart"
    if page_type == "checkout":
        return "https://shopstream.com/checkout"
    return "https://shopstream.com/other/" + _rng_hex(rng, 3)


# ---------------------------------------------------------------------------
# Generador de sesiones / eventos
# ---------------------------------------------------------------------------

class SessionGenerator:
    """Genera todos los eventos de una sesión individual."""

    def __init__(
        self,
        rng: random.Random,
        user: dict,
        catalog: Catalog,
        run_date: date,
    ):
        self.rng = rng
        self.user = user
        self.catalog = catalog
        self.run_date = run_date
        self.products_by_cat = catalog.products_by_category()
        # Decisiones tomadas al inicio
        self.session_id = _session_id(rng)
        self.device_type = self._pick_device()
        self.browser = rng.choice(BROWSERS)
        self.country = user["country"]
        self.start_time = self._sample_start_time()
        self.is_anomalous = rng.random() < P_ANOMALOUS_SESSION
        self.stage = "anomalous" if self.is_anomalous else _funnel_stage_for_session(rng)

    def _pick_device(self) -> str:
        # 70% de las veces sigue su preferencia, 30% cambia
        if self.rng.random() < 0.7:
            return self.user["device_preference"]
        return self.rng.choice(DEVICE_TYPES)

    def _sample_start_time(self) -> datetime:
        hour = _sample_hour(self.rng)
        minute = self.rng.randint(0, 59)
        second = self.rng.randint(0, 59)
        microsecond = self.rng.randint(0, 999_999)
        return datetime.combine(
            self.run_date,
            time(hour, minute, second, microsecond),
            tzinfo=timezone.utc,
        )

    def _next_ts(self, prev_ts: datetime, min_gap_s: float, max_gap_s: float) -> datetime:
        if self.is_anomalous:
            # Anomalía: o muy rápido (bot) o muy lento
            if self.rng.random() < 0.5:
                gap = self.rng.uniform(0.05, 0.4)
            else:
                gap = self.rng.uniform(600, 3600)
        else:
            gap = self.rng.uniform(min_gap_s, max_gap_s)
        return prev_ts + timedelta(seconds=gap)

    def _emit_page_view(
        self, ts: datetime, page_type: str, product_id: str | None = None
    ) -> dict:
        time_on_page = (
            self.rng.uniform(2.0, 180.0)
            if not self.is_anomalous
            else self.rng.choice([self.rng.uniform(0.1, 1.0), self.rng.uniform(1800, 7200)])
        )
        return {
            "event_id": _event_id(self.rng),
            "event_type": "page_view",
            "user_id": self.user["user_id"],
            "session_id": self.session_id,
            "timestamp": _iso(ts),
            "page_url": _page_url(page_type, self.rng, product_id),
            "page_type": page_type,
            "time_on_page_seconds": round(time_on_page, 2),
            "referrer": self.rng.choice(REFERRERS),
            "device_type": self.device_type,
            "country": self.country,
        }

    def _emit_click(self, ts: datetime, page_url: str) -> dict:
        return {
            "event_id": _event_id(self.rng),
            "event_type": "click",
            "user_id": self.user["user_id"],
            "session_id": self.session_id,
            "timestamp": _iso(ts),
            "element_id": f"el_{self.rng.randint(1, 9999):04d}",
            "element_type": self.rng.choice(ELEMENT_TYPES),
            "page_url": page_url,
            "x_position": self.rng.randint(0, 1920),
            "y_position": self.rng.randint(0, 3000),
        }

    def _emit_search(self, ts: datetime) -> dict:
        words = ["shoes", "phone", "shirt", "laptop", "book", "kitchen", "cream", "ball"]
        query = " ".join(self.rng.sample(words, k=self.rng.randint(1, 3)))
        return {
            "event_id": _event_id(self.rng),
            "event_type": "search",
            "user_id": self.user["user_id"],
            "session_id": self.session_id,
            "timestamp": _iso(ts),
            "query": query,
            "results_count": self.rng.randint(0, 500),
        }

    def _emit_product_view(self, ts: datetime, product: dict) -> dict:
        time_on_page = (
            self.rng.uniform(5.0, 240.0)
            if not self.is_anomalous
            else self.rng.uniform(7000, 7200)
        )
        return {
            "event_id": _event_id(self.rng),
            "event_type": "product_view",
            "user_id": self.user["user_id"],
            "session_id": self.session_id,
            "timestamp": _iso(ts),
            "product_id": product["product_id"],
            "category": product["category"],
            "price": product["price"],
            "time_on_page_seconds": round(time_on_page, 2),
        }

    def _emit_cart_event(self, ts: datetime, product: dict, action: str) -> dict:
        return {
            "event_id": _event_id(self.rng),
            "event_type": "cart_event",
            "user_id": self.user["user_id"],
            "session_id": self.session_id,
            "timestamp": _iso(ts),
            "product_id": product["product_id"],
            "action": action,
        }

    def _pick_product(self) -> dict:
        # 60% de las veces busca en una categoría "favorita" del usuario
        return self.rng.choice(self.catalog.products)

    def generate(self) -> Iterator[dict]:
        """Yields todos los eventos de la sesión en orden temporal."""
        ts = self.start_time
        # Siempre arranca con un page_view de landing
        landing_type = self.rng.choices(["home", "category", "search"], weights=[5, 3, 2])[0]
        first_pv = self._emit_page_view(ts, landing_type)
        yield first_pv
        # Posibles clicks en la landing
        for _ in range(_poisson(self.rng, P_CLICK_PER_PAGE_VIEW)):
            ts = self._next_ts(ts, 1.0, 8.0)
            yield self._emit_click(ts, first_pv["page_url"])

        if self.stage == "bounce":
            return

        # Posible búsqueda
        if self.rng.random() < P_SEARCH_PER_SESSION:
            ts = self._next_ts(ts, 2.0, 15.0)
            yield self._emit_search(ts)
            ts = self._next_ts(ts, 1.0, 5.0)
            search_pv = self._emit_page_view(ts, "search")
            yield search_pv

        # Navegación por categoría
        ts = self._next_ts(ts, 3.0, 20.0)
        cat_pv = self._emit_page_view(ts, "category")
        yield cat_pv
        for _ in range(_poisson(self.rng, P_CLICK_PER_PAGE_VIEW * 1.5)):
            ts = self._next_ts(ts, 1.0, 6.0)
            yield self._emit_click(ts, cat_pv["page_url"])

        if self.stage == "browsing":
            return

        # Consideración: 1-4 product_views
        n_products_viewed = self.rng.randint(1, 4)
        cart_products: list[dict] = []
        for _ in range(n_products_viewed):
            product = self._pick_product()
            ts = self._next_ts(ts, 2.0, 15.0)
            yield self._emit_page_view(ts, "product", product["product_id"])
            ts = self._next_ts(ts, 0.5, 4.0)
            yield self._emit_product_view(ts, product)
            for _ in range(_poisson(self.rng, P_CLICK_PER_PAGE_VIEW * 0.8)):
                ts = self._next_ts(ts, 1.0, 6.0)
                yield self._emit_click(
                    ts, _page_url("product", self.rng, product["product_id"])
                )
            cart_products.append(product)

        if self.stage == "consideration":
            return

        # Agregar al carrito 1-N productos vistos
        if cart_products:
            n_to_cart = self.rng.randint(1, len(cart_products))
            for product in self.rng.sample(cart_products, k=n_to_cart):
                ts = self._next_ts(ts, 1.0, 8.0)
                yield self._emit_cart_event(ts, product, "add")
                if self.rng.random() < 0.15:
                    ts = self._next_ts(ts, 2.0, 15.0)
                    yield self._emit_cart_event(ts, product, "remove")
            ts = self._next_ts(ts, 2.0, 12.0)
            yield self._emit_page_view(ts, "cart")

        if self.stage in ("cart_only", "anomalous"):
            # Las anómalas siguen con muchos eventos extra
            if self.stage == "anomalous":
                for _ in range(self.rng.randint(40, 120)):
                    ts = self._next_ts(ts, 0.1, 2.0)
                    yield self._emit_click(ts, "https://shopstream.com/cart")
            return

        # Compra completada
        ts = self._next_ts(ts, 5.0, 30.0)
        yield self._emit_page_view(ts, "checkout")


# ---------------------------------------------------------------------------
# Orquestador a nivel de día
# ---------------------------------------------------------------------------

def generate_day(
    run_date: date,
    catalog: Catalog,
    config: GeneratorConfig,
    output_path: Path,
) -> dict:
    """Genera eventos para un día y los escribe a `output_path` en JSON Lines.

    Returns un dict con métricas: total_events, total_sessions, by_type, etc.
    """
    seed = _date_seed(run_date, config.seed)
    rng = random.Random(seed)

    # Decidir usuarios activos (subset estable por día)
    n_active = int(len(catalog.users) * config.active_user_fraction)
    active_users = rng.sample(catalog.users, k=n_active)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    metrics = {
        "run_date": run_date.isoformat(),
        "total_events": 0,
        "total_sessions": 0,
        "by_type": {t: 0 for t in ["page_view", "click", "search", "product_view", "cart_event"]},
        "bounce_sessions": 0,
        "anomalous_sessions": 0,
    }

    with output_path.open("w", encoding="utf-8") as f:
        while metrics["total_events"] < config.target_events:
            user = rng.choice(active_users)
            n_sessions = max(1, _poisson(rng, config.sessions_per_active_user_lambda))
            for _ in range(n_sessions):
                if metrics["total_events"] >= config.target_events:
                    break
                gen = SessionGenerator(rng, user, catalog, run_date)
                events_in_session = list(gen.generate())
                # Mezclar con eventos en orden por timestamp ya está garantizado
                for ev in events_in_session:
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                    metrics["total_events"] += 1
                    metrics["by_type"][ev["event_type"]] += 1
                metrics["total_sessions"] += 1
                if gen.stage == "bounce":
                    metrics["bounce_sessions"] += 1
                if gen.is_anomalous:
                    metrics["anomalous_sessions"] += 1

    return metrics


def _date_seed(run_date: date, base_seed: int) -> int:
    """Seed determinista por fecha (mismo seed produce mismos eventos)."""
    payload = f"{base_seed}:{run_date.isoformat()}".encode()
    return int(hashlib.sha256(payload).hexdigest()[:8], 16)
