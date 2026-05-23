"""Genera y carga el catálogo base de usuarios y productos.

El catálogo es **estable entre días**: se genera una sola vez (determinista por
seed) y se reutiliza para todas las fechas. Los eventos referencian estas
entidades por `user_id` y `product_id`.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

from data_generation.schemas import (
    AGE_BUCKETS,
    BROWSERS,
    COUNTRIES,
    DEVICE_TYPES,
    PRODUCT_CATEGORIES,
)

# Distribuciones realistas (pesos paralelos a las listas en schemas.py)
COUNTRY_WEIGHTS = [0.40, 0.25, 0.15, 0.10, 0.03, 0.02, 0.02, 0.01, 0.01, 0.01]
DEVICE_WEIGHTS = [0.70, 0.25, 0.05]  # mobile / desktop / tablet
AGE_WEIGHTS = [0.18, 0.32, 0.22, 0.14, 0.09, 0.05]

# Subcategorías por categoría (para realismo)
SUBCATEGORIES = {
    "electronics": ["smartphones", "laptops", "headphones", "cameras", "wearables"],
    "clothing": ["men", "women", "kids", "shoes", "accessories"],
    "home": ["kitchen", "decor", "furniture", "bedding", "appliances"],
    "sports": ["fitness", "outdoor", "team_sports", "swimming", "cycling"],
    "books": ["fiction", "non_fiction", "children", "comics", "textbooks"],
    "beauty": ["skincare", "makeup", "haircare", "fragrance", "tools"],
    "toys": ["educational", "plush", "action_figures", "board_games", "puzzles"],
    "food": ["snacks", "beverages", "gourmet", "organic", "bakery"],
}


@dataclass
class Catalog:
    """Snapshot inmutable de users + products usado por el generador."""

    users: list[dict] = field(default_factory=list)
    products: list[dict] = field(default_factory=list)

    @property
    def user_ids(self) -> list[str]:
        return [u["user_id"] for u in self.users]

    @property
    def product_ids(self) -> list[str]:
        return [p["product_id"] for p in self.products]

    def products_by_category(self) -> dict[str, list[dict]]:
        idx: dict[str, list[dict]] = {c: [] for c in PRODUCT_CATEGORIES}
        for p in self.products:
            idx[p["category"]].append(p)
        return idx


def _weighted_choice(rng: random.Random, options: list[str], weights: list[float]) -> str:
    return rng.choices(options, weights=weights, k=1)[0]


def generate_users(
    n: int, seed: int, signup_window_days: int = 730
) -> list[dict]:
    """Genera `n` usuarios con distribuciones sesgadas pero realistas."""
    rng = random.Random(seed)
    fake = Faker()
    Faker.seed(seed)

    today = date.today()
    users: list[dict] = []
    for i in range(n):
        signup_offset_days = rng.randint(0, signup_window_days)
        signup_date = (today - timedelta(days=signup_offset_days)).isoformat()
        users.append(
            {
                "user_id": f"U{i:08d}",
                "signup_date": signup_date,
                "country": _weighted_choice(rng, COUNTRIES, COUNTRY_WEIGHTS),
                "age_bucket": _weighted_choice(rng, AGE_BUCKETS, AGE_WEIGHTS),
                "device_preference": _weighted_choice(rng, DEVICE_TYPES, DEVICE_WEIGHTS),
                "is_premium": rng.random() < 0.12,  # ~12% premium
            }
        )
    return users


def generate_products(n: int, seed: int) -> list[dict]:
    """Genera `n` productos repartidos entre las 8 categorías."""
    rng = random.Random(seed + 1)  # seed distinto para no correlacionar con users
    fake = Faker()
    Faker.seed(seed + 1)

    today = date.today()
    products: list[dict] = []
    for i in range(n):
        category = rng.choice(PRODUCT_CATEGORIES)
        subcategory = rng.choice(SUBCATEGORIES[category])
        # Precio sigue una log-normal aprox: la mayoría barato, cola larga
        price = round(rng.lognormvariate(mu=3.2, sigma=0.9), 2)
        price = min(max(price, 0.5), 5000.0)
        created_offset_days = rng.randint(0, 1095)  # hasta 3 años
        products.append(
            {
                "product_id": f"P{i:06d}",
                "category": category,
                "subcategory": subcategory,
                "name": f"{fake.color_name()} {subcategory.replace('_', ' ').title()} {i:06d}",
                "price": price,
                "stock": rng.randint(0, 1000),
                "brand": fake.company()[:60],
                "rating": round(rng.triangular(1.0, 5.0, 4.2), 1),
                "created_at": (today - timedelta(days=created_offset_days)).isoformat(),
            }
        )
    return products


def write_jsonl(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_or_load_catalog(
    base_dir: Path,
    n_users: int = 50_000,
    n_products: int = 2_000,
    seed: int = 42,
    rebuild: bool = False,
) -> Catalog:
    """Carga el catálogo desde disco; si no existe (o `rebuild=True`), lo genera."""
    users_path = base_dir / "users.jsonl"
    products_path = base_dir / "products.jsonl"

    if rebuild or not users_path.exists() or not products_path.exists():
        users = generate_users(n_users, seed=seed)
        products = generate_products(n_products, seed=seed)
        write_jsonl(users_path, users)
        write_jsonl(products_path, products)
    else:
        users = read_jsonl(users_path)
        products = read_jsonl(products_path)

    return Catalog(users=users, products=products)
