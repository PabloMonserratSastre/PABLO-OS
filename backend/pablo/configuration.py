"""Private provider settings and atomic, conservative request budgets."""

import json
import math
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

from pydantic import Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError

from .db import DB, BudgetPeriod, ServiceConfig
from .integrations import seal, unseal
from .schemas import Strict


class ProviderSettings(Strict):
    base_url: str = Field(default="https://api.openai.com/v1", max_length=500)
    model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=2000)
    embed_model: str = Field(default="", max_length=200)
    monthly_budget_usd: float = Field(default=0, ge=0, le=10000, allow_inf_nan=False)
    input_cost_per_million: float = Field(default=0, ge=0, le=1000, allow_inf_nan=False)
    output_cost_per_million: float = Field(default=0, ge=0, le=10000, allow_inf_nan=False)


def validate_base(value):
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.scheme not in {"https", "http"}):
        raise ValueError("Indica una URL HTTPS de proveedor válida.")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("HTTP solo está permitido para un proveedor local.")
    return value.rstrip("/")


def provider_config(db=None):
    own = db is None
    db = db or DB()
    credential_error = ""
    try:
        row = db.get(ServiceConfig, "provider")
        config = row.value.copy() if row else {}
        try:
            secret = unseal(row.encrypted) if row and row.encrypted else {}
        except ValueError:
            secret = {}
            credential_error = "No se pueden leer las credenciales del proveedor. Vuelve a guardarlas en Ajustes. Tus datos y tu contraseña de acceso se conservan."
    except OperationalError:
        config, secret = {}, {}
    finally:
        if own:
            db.close()
    defaults = ProviderSettings().model_dump(exclude={"api_key"})
    defaults.update({
        "base_url": os.getenv("AI_BASE_URL", defaults["base_url"]),
        "model": os.getenv("AI_MODEL", ""),
        "embed_model": os.getenv("AI_EMBED_MODEL", ""),
    })
    defaults.update(config)
    defaults["api_key"] = "" if credential_error else secret.get("api_key", os.getenv("AI_API_KEY", ""))
    defaults["credential_error"] = credential_error
    return defaults


def public_provider(db):
    config = provider_config(db)
    key = config.pop("api_key")
    budget = db.get(BudgetPeriod, datetime.now(timezone.utc).strftime("%Y-%m"))
    return config | {
        "key_present": bool(key), "configured": bool(config["model"] and key),
        "spent_usd": budget.actual_micro / 1_000_000 if budget else 0,
        "committed_usd": budget.committed_micro / 1_000_000 if budget else 0,
        "budget_note": "Límite basado en las tarifas que introduces; las peticiones sin respuesta conservan su reserva.",
    }


def save_provider(db, body):
    config = body.model_dump(exclude={"api_key"})
    config["base_url"] = validate_base(body.base_url)
    row = db.get(ServiceConfig, "provider")
    if row and row.value.get("base_url", "").rstrip("/") != config["base_url"] and not body.api_key:
        raise ValueError("Al cambiar de proveedor introduce su clave. No se reutilizará la clave del proveedor anterior.")
    if row is None:
        row = ServiceConfig(id="provider", value={}, encrypted="")
        db.add(row)
    row.value = config
    if body.api_key is not None:
        row.encrypted = seal({"api_key": body.api_key.strip()})
    db.flush()


def reserve_request(config, payload):
    """Charge an upper allowance before network I/O, serialized by a DB update."""
    cap = int(config.get("monthly_budget_usd", 0) * 1_000_000)
    in_price = config.get("input_cost_per_million", 0)
    out_price = config.get("output_cost_per_million", 0)
    if cap and (in_price <= 0 or out_price <= 0):
        raise ValueError("Configura ambas tarifas de tokens para activar el límite de gasto.")
    # One token per UTF-8 byte plus ample protocol overhead bounds supported text requests.
    input_allowance = len(json.dumps(payload, ensure_ascii=False).encode()) + 4096
    output_allowance = payload.get("max_completion_tokens", payload.get("max_tokens", 0))
    amount = math.ceil(input_allowance * in_price + output_allowance * out_price)
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    with DB() as db:
        if not db.get(BudgetPeriod, period):
            try:
                db.add(BudgetPeriod(id=period))
                db.commit()
            except IntegrityError:
                db.rollback()
        query = update(BudgetPeriod).where(BudgetPeriod.id == period)
        if cap:
            query = query.where(BudgetPeriod.committed_micro + amount <= cap)
        changed = db.execute(query.values(committed_micro=BudgetPeriod.committed_micro + amount))
        if not changed.rowcount:
            raise ValueError("Presupuesto mensual agotado: no se ha enviado la petición al proveedor.")
        db.commit()
    return period, amount


def settle_request(config, reservation, usage):
    period, amount = reservation
    if not isinstance(usage, dict) or not usage:
        return  # Unknown result retains the full reservation.
    incoming = usage.get("prompt_tokens", usage.get("input_tokens", usage.get("total_tokens", 0)))
    outgoing = usage.get("completion_tokens", usage.get("output_tokens", 0))
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
           for value in (incoming, outgoing)):
        return  # Malformed accounting must not release a conservative reservation.
    actual = math.ceil(max(0, incoming) * config["input_cost_per_million"]
                       + max(0, outgoing) * config["output_cost_per_million"])
    with DB() as db:
        db.execute(update(BudgetPeriod).where(BudgetPeriod.id == period).values(
            committed_micro=BudgetPeriod.committed_micro - amount + actual,
            actual_micro=BudgetPeriod.actual_micro + actual,
        ))
        db.commit()
