#!/usr/bin/env python3
import json
import math
import os
import sys


def centroid(vectors):
    n = len(vectors)
    if n == 0:
        return []
    width = len(vectors[0])
    return [sum(vec[i] for vec in vectors) / n for i in range(width)]


def main():
    try:
        params = json.load(sys.stdin)
    except Exception:
        params = {}

    samples = params.get("samples") or []
    labels = params.get("labels") or []
    save_path = params.get("save_path") or "/tmp/local_learn_model.json"

    if len(samples) != len(labels) or not samples:
        print(json.dumps({
            "status": "error",
            "message": "samples and labels must be non-empty lists of equal length",
        }))
        return

    grouped = {}
    for sample, label in zip(samples, labels):
        try:
            vector = [float(x) for x in sample]
        except Exception:
            print(json.dumps({"status": "error", "message": "sample contains non-numeric values"}))
            return
        if not vector or any(not math.isfinite(x) for x in vector):
            print(json.dumps({"status": "error", "message": "sample contains invalid numeric values"}))
            return
        grouped.setdefault(str(label), []).append(vector)

    dims = {len(vec) for vecs in grouped.values() for vec in vecs}
    if len(dims) != 1:
        print(json.dumps({"status": "error", "message": "all samples must have the same dimension"}))
        return

    model = {
        "type": "nearest_centroid",
        "dimension": next(iter(dims)),
        "labels": sorted(grouped),
        "centroids": {label: centroid(vecs) for label, vecs in grouped.items()},
        "counts": {label: len(vecs) for label, vecs in grouped.items()},
    }

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as handle:
        json.dump(model, handle)

    print(json.dumps({
        "status": "success",
        "model_path": save_path,
        "model_type": model["type"],
        "labels": model["labels"],
        "dimension": model["dimension"],
        "sample_count": len(samples),
    }))


if __name__ == "__main__":
    main()
