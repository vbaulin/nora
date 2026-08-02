#!/usr/bin/env python3
"""Resolve a GPS point against the official MAPA/FEGA SIGPAC recinto layer."""

import argparse
import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_ENDPOINT = "https://sigpac-hubcloud.es/wms"
DEFAULT_LAYER = "AU.Sigpac:recinto"
DEFAULT_RADIUS_DEGREES = 0.0005
SIGPAC_VIEWER = "https://sigpac.mapa.gob.es/fega/visor/"


def _code_and_name(value):
    text = str(value or "").strip()
    if " - " not in text:
        return text, None
    code, name = text.split(" - ", 1)
    return code.strip(), name.strip()


def _optional_number(value, number_type=float):
    if value in (None, ""):
        return None
    try:
        return number_type(value)
    except (TypeError, ValueError):
        return None


def _viewer_url(reference):
    query = {
        "provincia": reference["province_code"],
        "municipio": reference["municipality_code"],
        "agregado": reference["aggregate"],
        "zona": reference["zone"],
        "poligono": reference["polygon"],
        "parcela": reference["parcel"],
        "recinto": reference["recinto"],
    }
    return f"{SIGPAC_VIEWER}?{urllib.parse.urlencode(query)}"


def normalize_feature(feature):
    """Return stable English keys while retaining the official raw properties."""
    properties = dict((feature or {}).get("properties") or {})
    province_code, province_name = _code_and_name(properties.get("provincia"))
    municipality_code, municipality_name = _code_and_name(properties.get("municipio"))
    use_code, use_name = _code_and_name(properties.get("uso_sigpac"))
    reference = {
        "province_code": province_code,
        "municipality_code": municipality_code,
        "aggregate": _optional_number(properties.get("agregado"), int),
        "zone": _optional_number(properties.get("zona"), int),
        "polygon": _optional_number(properties.get("poligono"), int),
        "parcel": _optional_number(properties.get("parcela"), int),
        "recinto": _optional_number(properties.get("recinto"), int),
    }
    reference_text = ":".join(str(reference[key]) for key in (
        "province_code",
        "municipality_code",
        "aggregate",
        "zone",
        "polygon",
        "parcel",
        "recinto",
    ))
    return {
        **reference,
        "reference": reference_text,
        "province": province_name,
        "municipality": municipality_name,
        "use_code": use_code,
        "use": use_name,
        "area_ha": _optional_number(properties.get("superficie_ha")),
        "slope_percent": _optional_number(properties.get("pendiente")),
        "irrigation_coefficient": _optional_number(properties.get("coef_regadio")),
        "admissibility": properties.get("admisibilidad"),
        "incidents": properties.get("incidencias") or [],
        "region": properties.get("region"),
        "altitude_m": _optional_number(properties.get("altitud")),
        "viewer_url": _viewer_url(reference),
        "raw_properties": properties,
    }


def build_get_feature_info_url(
    latitude,
    longitude,
    endpoint=DEFAULT_ENDPOINT,
    radius_degrees=DEFAULT_RADIUS_DEGREES,
):
    latitude = float(latitude)
    longitude = float(longitude)
    radius = float(radius_degrees)
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": DEFAULT_LAYER,
        "QUERY_LAYERS": DEFAULT_LAYER,
        "STYLES": "",
        "CRS": "CRS:84",
        "BBOX": ",".join(str(value) for value in (
            longitude - radius,
            latitude - radius,
            longitude + radius,
            latitude + radius,
        )),
        "WIDTH": 101,
        "HEIGHT": 101,
        "I": 50,
        "J": 50,
        "INFO_FORMAT": "application/json",
        "FEATURE_COUNT": 10,
    }
    return f"{endpoint}?{urllib.parse.urlencode(params)}"


def select_candidate(candidates, expected_use_code=None):
    expected = str(expected_use_code or "").strip().upper()
    matches = candidates
    if expected:
        matches = [
            candidate
            for candidate in candidates
            if str(candidate.get("use_code") or "").upper() == expected
        ]
    if len(matches) == 1:
        return "selected", matches[0]
    if expected and not matches:
        return "use_code_mismatch", None
    if len(candidates) == 1 and not expected:
        return "selected", candidates[0]
    if not candidates:
        return "not_found", None
    return "ambiguous", None


def query_sigpac(
    latitude,
    longitude,
    expected_use_code=None,
    endpoint=DEFAULT_ENDPOINT,
    timeout=30,
    opener=urllib.request.urlopen,
):
    latitude = float(latitude)
    longitude = float(longitude)
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Invalid latitude/longitude")
    url = build_get_feature_info_url(latitude, longitude, endpoint=endpoint)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "nano-os-agent-vineyard-provisioner/1.0"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"SIGPAC request failed at {endpoint}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"SIGPAC returned non-JSON data from {endpoint}") from exc
    candidates = [normalize_feature(feature) for feature in payload.get("features") or []]
    status, selected = select_candidate(candidates, expected_use_code)
    selection_basis = None
    if selected is not None:
        selection_basis = "expected_use_code" if expected_use_code else "single_candidate"
    return {
        "status": status,
        "selected": selected,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "selection_basis": selection_basis,
        "review_required": len(candidates) != 1,
        "expected_use_code": str(expected_use_code or "").strip().upper() or None,
        "query_coordinates": {
            "latitude": latitude,
            "longitude": longitude,
        },
        "service": {
            "provider": "MAPA/FEGA",
            "standard": "OGC WMS 1.3.0 GetFeatureInfo",
            "endpoint": endpoint,
            "layer": DEFAULT_LAYER,
            "crs": "CRS:84",
            "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "authoritative_status": "orientative_non_binding",
        },
        "query_url": url,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--expected-use-code")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero status unless one recinto is selected.",
    )
    args = parser.parse_args()
    result = query_sigpac(
        args.latitude,
        args.longitude,
        expected_use_code=args.expected_use_code,
        endpoint=args.endpoint,
        timeout=args.timeout,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    if args.strict and result["status"] != "selected":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
