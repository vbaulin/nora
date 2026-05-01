#!/usr/bin/env python3
import colorsys
import json
import sys


def load_params():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def sample_with_pillow(path):
    from PIL import Image

    img = Image.open(path).convert("RGB")
    img.thumbnail((160, 120))
    return list(img.getdata())


def sample_with_cv2(path):
    import cv2

    img = cv2.imread(path)
    if img is None:
        raise RuntimeError("cv2 could not read image")
    img = cv2.resize(img, (160, 120))
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return [tuple(int(v) for v in px) for row in rgb for px in row]


def main():
    params = load_params()
    path = params.get("image_path") or params.get("path") or "/tmp/capture.jpg"

    try:
        try:
            pixels = sample_with_pillow(path)
            backend = "pillow"
        except Exception:
            pixels = sample_with_cv2(path)
            backend = "cv2"

        if not pixels:
            raise RuntimeError("no pixels sampled")

        total_r = total_g = total_b = 0
        total_h = total_s = total_v = 0.0
        green = purple = yellow = brown = 0

        for r, g, b in pixels:
            total_r += r
            total_g += g
            total_b += b
            h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            hue = h * 360.0
            total_h += hue
            total_s += s
            total_v += v
            if 65 <= hue <= 170 and s > 0.18:
                green += 1
            if (hue >= 260 or hue <= 25) and s > 0.20 and v < 0.65:
                purple += 1
            if 35 <= hue < 65 and s > 0.18:
                yellow += 1
            if 15 <= hue < 45 and s > 0.20 and v < 0.45:
                brown += 1

        n = float(len(pixels))
        purple_ratio = purple / n
        green_ratio = green / n
        yellow_ratio = yellow / n
        brown_ratio = brown / n
        ripeness = purple_ratio / max(0.01, purple_ratio + green_ratio)

        print(json.dumps({
            "status": "success",
            "image_path": path,
            "backend": backend,
            "mean_rgb": {
                "r": total_r / n,
                "g": total_g / n,
                "b": total_b / n,
            },
            "mean_hue": total_h / n,
            "mean_saturation": total_s / n,
            "mean_value": total_v / n,
            "green_ratio": green_ratio,
            "purple_ratio": purple_ratio,
            "yellow_ratio": yellow_ratio,
            "brown_ratio": brown_ratio,
            "ripeness_estimate": ripeness,
            "stress_estimate": min(1.0, yellow_ratio + brown_ratio),
        }))
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "image_path": path,
            "message": str(exc),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
