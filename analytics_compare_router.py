# analytics_compare_router.py — Comparativa 6/12/18/24 meses (baseline = última analítica)
#
# Endpoint:
#   GET /analytics/compare/by-patient/{patient_id}
#
# Reglas:
# - Baseline = última analítica por fecha efectiva (exam_date si existe, si no created_at)
# - Ventanas: 6/12/18/24 meses desde baseline
# - Tolerancia: ±60 días (6/12) y ±90 días (18/24)
# - Tendencia por marcador (genérica): compara baseline vs ventana
#     "=" si |%| < 5%
#     "↑" si baseline > ventana
#     "↓" si baseline < ventana

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
import crud

from models import Analytic, Patient  # usa relación Analytic.markers


router = APIRouter(prefix="/analytics", tags=["Analytics-Compare"])


def _effective_date(a: Analytic) -> date:
    # Fecha efectiva = exam_date si existe; si no, created_at (date)
    if getattr(a, "exam_date", None):
        return a.exam_date
    ca = getattr(a, "created_at", None)
    if isinstance(ca, datetime):
        return ca.date()
    return date.today()


def _pick_baseline(analytics: List[Analytic]) -> Optional[Analytic]:
    if not analytics:
        return None
    # Orden por fecha efectiva, luego created_at
    def key(a: Analytic):
        ed = _effective_date(a)
        ca = getattr(a, "created_at", None) or datetime.utcnow()
        return (ed, ca)
    return sorted(analytics, key=key)[-1]


def _find_nearest_in_window(
    analytics: List[Analytic],
    target: date,
    tolerance_days: int,
    baseline_id: int,
) -> Optional[Analytic]:
    best = None
    best_delta = None

    for a in analytics:
        if a.id == baseline_id:
            continue
        d = _effective_date(a)
        delta = abs((d - target).days)
        if delta <= tolerance_days:
            if best_delta is None or delta < best_delta:
                best = a
                best_delta = delta

    return best


def _trend_symbol(baseline_val: Optional[float], past_val: Optional[float]) -> Optional[str]:
    if baseline_val is None or past_val is None:
        return None
    try:
        if past_val == 0:
            # si past_val es 0, tendencia solo por diferencia absoluta
            diff = baseline_val - past_val
            if abs(diff) < 1e-9:
                return "="
            return "↑" if diff > 0 else "↓"

        pct = (baseline_val - past_val) / abs(past_val)
        if abs(pct) < 0.05:
            return "="
        return "↑" if pct > 0 else "↓"
    except Exception:
        return None


def _build_markers_map(a: Analytic) -> Dict[str, float]:
    out: Dict[str, float] = {}
    try:
        for m in getattr(a, "markers", []) or []:
            name = (getattr(m, "name", None) or "").strip()
            val = getattr(m, "value", None)
            if not name:
                continue
            if val is None:
                continue
            try:
                out[name] = float(val)
            except Exception:
                continue
    except Exception:
        pass
    return out


@router.get("/compare/by-patient/{patient_id}")
def compare_by_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Seguridad: paciente debe pertenecer al médico
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")

    # Cargar analíticas (todas)
    analytics = (
        db.query(Analytic)
        .filter(Analytic.patient_id == patient_id)
        .all()
    )
    if not analytics:
        return {
            "patient_id": patient_id,
            "baseline": None,
            "windows": {"6m": None, "12m": None, "18m": None, "24m": None},
            "markers": {},
            "note": "No hay analíticas suficientes para comparar.",
        }

    baseline = _pick_baseline(analytics)
    if not baseline:
        return {
            "patient_id": patient_id,
            "baseline": None,
            "windows": {"6m": None, "12m": None, "18m": None, "24m": None},
            "markers": {},
            "note": "No hay analíticas suficientes para comparar.",
        }

    base_date = _effective_date(baseline)

    # Definición de ventanas
    windows_def: List[Tuple[str, int, int]] = [
        ("6m", 6, 60),
        ("12m", 12, 60),
        ("18m", 18, 90),
        ("24m", 24, 90),
    ]

    windows: Dict[str, Optional[Dict[str, Any]]] = {}
    selected_analytics: Dict[str, Optional[Analytic]] = {"baseline": baseline}

    for label, months, tol in windows_def:
        # target = base_date - months*30 aprox (sin dateutil para máxima compatibilidad)
        # Mejor: usamos 30 días/mes para la búsqueda cercana + tolerancia amplia.
        target = base_date - timedelta(days=30 * months)
        picked = _find_nearest_in_window(analytics, target, tol, baseline.id)
        selected_analytics[label] = picked
        windows[label] = (
            {"analytic_id": picked.id, "date": _effective_date(picked).isoformat()}
            if picked else None
        )

    baseline_info = {"analytic_id": baseline.id, "date": base_date.isoformat()}

    # Mapas de marcadores
    base_markers = _build_markers_map(baseline)

    window_markers: Dict[str, Dict[str, float]] = {}
    for label, _, _ in windows_def:
        a = selected_analytics.get(label)
        window_markers[label] = _build_markers_map(a) if a else {}

    # Unión de nombres
    all_names = set(base_markers.keys())
    for label in window_markers:
        all_names.update(window_markers[label].keys())

    # Construcción final
    markers_out: Dict[str, Any] = {}
    for name in sorted(all_names):
        bval = base_markers.get(name)
        row = {
            "baseline": bval,
            "6m": window_markers["6m"].get(name),
            "12m": window_markers["12m"].get(name),
            "18m": window_markers["18m"].get(name),
            "24m": window_markers["24m"].get(name),
            "trend": {
                "6m": _trend_symbol(bval, window_markers["6m"].get(name)),
                "12m": _trend_symbol(bval, window_markers["12m"].get(name)),
                "18m": _trend_symbol(bval, window_markers["18m"].get(name)),
                "24m": _trend_symbol(bval, window_markers["24m"].get(name)),
            },
        }
        markers_out[name] = row

    return {
        "patient_id": patient_id,
        "baseline": baseline_info,
        "windows": windows,
        "markers": markers_out,
        "tolerances": {"6m": 60, "12m": 60, "18m": 90, "24m": 90},
    }
