"""Copy-move forgery detector using ORB keypoints, shift clustering, and patch correlation."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import cv2
from PIL import Image

from app.schemas import BoundingBox, DetectorResult

MAX_PROCESS_DIM = 1600
MIN_IMAGE_DIM = 64
MAX_HAMMING_DIST = 28
MIN_CLUSTER_MATCHES = 8
SHIFT_BIN_SIZE = 16  # pixels in processing space
SPATIAL_LINK_RADIUS = 28.0  # max distance between keypoints in the same local object
MIN_PATCH_CORR = 0.88
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _clamp_box(
    x: int, y: int, w: int, h: int, page_w: int, page_h: int, page_idx: int
) -> BoundingBox | None:
    x1 = max(0, min(x, page_w - 1))
    y1 = max(0, min(y, page_h - 1))
    x2 = max(x1 + 1, min(x + w, page_w))
    y2 = max(y1 + 1, min(y + h, page_h))
    if x2 <= x1 or y2 <= y1:
        return None
    return BoundingBox(page=page_idx, x=x1, y=y1, w=x2 - x1, h=y2 - y1)


def _patch_ncc(
    gray: np.ndarray, box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]
) -> float:
    """Compute normalized cross-correlation between two patches."""
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    patch_a = gray[ay : ay + ah, ax : ax + aw].astype(np.float32)
    patch_b = gray[by : by + bh, bx : bx + bw].astype(np.float32)
    if patch_a.size == 0 or patch_b.size == 0:
        return 0.0
    if patch_a.shape != patch_b.shape:
        patch_b = cv2.resize(patch_b, (aw, ah), interpolation=cv2.INTER_AREA)

    a_centered = patch_a - float(np.mean(patch_a))
    b_centered = patch_b - float(np.mean(patch_b))
    denom = float(np.sqrt(np.sum(a_centered * a_centered) * np.sum(b_centered * b_centered)))
    if denom < 1e-6:
        return 0.0
    return float(np.sum(a_centered * b_centered) / denom)


def _cluster_by_proximity(
    pairs: list[tuple[tuple[float, float], tuple[float, float], int]],
    radius: float = SPATIAL_LINK_RADIUS,
) -> list[list[tuple[tuple[float, float], tuple[float, float], int]]]:
    """Group matched pairs into spatially connected clusters based on source keypoint proximity."""
    n = len(pairs)
    visited = [False] * n
    clusters: list[list[tuple[tuple[float, float], tuple[float, float], int]]] = []
    r_sq = radius * radius

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        queue = [i]
        group = [pairs[i]]
        while queue:
            curr = queue.pop()
            cx, cy = pairs[curr][0]
            for j in range(n):
                if visited[j]:
                    continue
                jx, jy = pairs[j][0]
                if (cx - jx) ** 2 + (cy - jy) ** 2 <= r_sq:
                    visited[j] = True
                    queue.append(j)
                    group.append(pairs[j])
        clusters.append(group)
    return clusters


def _analyze_page(
    page_path: Path, page_idx: int
) -> tuple[str, float, float, list[BoundingBox], str]:
    """Run ORB + shift-clustering copy-move analysis on a single rendered page."""
    with Image.open(page_path) as pil_img:
        gray_orig = np.asarray(pil_img.convert("L"), dtype=np.uint8)

    orig_h, orig_w = gray_orig.shape[:2]
    if orig_h < MIN_IMAGE_DIM or orig_w < MIN_IMAGE_DIM:
        return (
            "inconclusive",
            0.0,
            0.1,
            [],
            f"Page {page_idx}: image too small ({orig_w}x{orig_h}) for copy-move analysis.",
        )

    if float(np.std(gray_orig)) < 2.0:
        return (
            "inconclusive",
            0.0,
            0.1,
            [],
            f"Page {page_idx}: blank or uniform image; copy-move analysis is inconclusive.",
        )

    scale = 1.0
    max_dim = max(orig_h, orig_w)
    if max_dim > MAX_PROCESS_DIM:
        scale = MAX_PROCESS_DIM / float(max_dim)
        proc_w = max(1, int(round(orig_w * scale)))
        proc_h = max(1, int(round(orig_h * scale)))
        gray = cv2.resize(gray_orig, (proc_w, proc_h), interpolation=cv2.INTER_AREA)
    else:
        proc_w, proc_h = orig_w, orig_h
        gray = gray_orig

    orb = cv2.ORB_create(nfeatures=2500, scaleFactor=1.2, nlevels=8, fastThreshold=12)
    keypoints, descriptors = orb.detectAndCompute(gray, None)

    if descriptors is None or len(keypoints) < MIN_CLUSTER_MATCHES * 2:
        return (
            "inconclusive",
            0.0,
            0.25,
            [],
            f"Page {page_idx}: insufficient visual keypoints ({0 if descriptors is None else len(keypoints)}) for copy-move matching.",
        )

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    knn_matches = matcher.knnMatch(descriptors, descriptors, k=4)

    min_spatial_dist = max(40.0, 0.04 * min(proc_w, proc_h))
    shift_bins: dict[
        tuple[int, int], list[tuple[tuple[float, float], tuple[float, float], int]]
    ] = defaultdict(list)

    for candidates in knn_matches:
        for m in candidates:
            if m.queryIdx == m.trainIdx:
                continue
            if m.distance > MAX_HAMMING_DIST:
                continue
            pt1 = keypoints[m.queryIdx].pt
            pt2 = keypoints[m.trainIdx].pt
            dx = pt2[0] - pt1[0]
            dy = pt2[1] - pt1[1]
            dist = float(np.hypot(dx, dy))
            if dist < min_spatial_dist:
                continue
            if (dx < 0) or (dx == 0 and dy < 0):
                pt1, pt2 = pt2, pt1
                dx, dy = -dx, -dy
            bin_key = (int(round(dx / SHIFT_BIN_SIZE)), int(round(dy / SHIFT_BIN_SIZE)))
            shift_bins[bin_key].append((pt1, pt2, int(m.distance)))
            break

    boxes: list[BoundingBox] = []
    best_corr = 0.0
    best_cluster_size = 0
    inv_scale = 1.0 / scale
    pad = 16

    sorted_bins = sorted(shift_bins.items(), key=lambda kv: len(kv[1]), reverse=True)
    seen_regions: list[tuple[int, int, int, int]] = []

    for _, bin_pairs in sorted_bins:
        if len(bin_pairs) < MIN_CLUSTER_MATCHES:
            continue

        # Split each shift bin into spatially contiguous local clusters
        # so repeated table rows at regular spacing do not merge into one giant box.
        for pairs in _cluster_by_proximity(bin_pairs):
            if len(pairs) < MIN_CLUSTER_MATCHES:
                continue

            pts1 = np.array([p[0] for p in pairs], dtype=np.float32)
            pts2 = np.array([p[1] for p in pairs], dtype=np.float32)

            x1_min, y1_min = np.min(pts1, axis=0)
            x1_max, y1_max = np.max(pts1, axis=0)
            x2_min, y2_min = np.min(pts2, axis=0)
            x2_max, y2_max = np.max(pts2, axis=0)

            w1 = float(x1_max - x1_min)
            h1 = float(y1_max - y1_min)
            w2 = float(x2_max - x2_min)
            h2 = float(y2_max - y2_min)
            # Reject thin 1D lines or single-line text strips
            if min(w1, w2) < 32.0 or min(h1, h2) < 26.0:
                continue

            bx1 = max(0, int(x1_min) - pad)
            by1 = max(0, int(y1_min) - pad)
            bw1 = min(proc_w - bx1, int(w1) + 2 * pad)
            bh1 = min(proc_h - by1, int(h1) + 2 * pad)

            bx2 = max(0, int(x2_min) - pad)
            by2 = max(0, int(y2_min) - pad)
            bw2 = min(proc_w - bx2, int(w2) + 2 * pad)
            bh2 = min(proc_h - by2, int(h2) + 2 * pad)

            # Reject self-overlapping periodic matches (e.g. stacked table rows)
            inter_w = max(0, min(bx1 + bw1, bx2 + bw2) - max(bx1, bx2))
            inter_h = max(0, min(by1 + bh1, by2 + bh2) - max(by1, by2))
            inter_area = inter_w * inter_h
            min_box_area = max(1, min(bw1 * bh1, bw2 * bh2))
            if inter_area / float(min_box_area) > 0.15:
                continue

            ncc = _patch_ncc(gray, (bx1, by1, bw1, bh1), (bx2, by2, bw2, bh2))
            if ncc < MIN_PATCH_CORR:
                continue

            already_covered = any(
                abs(bx1 - sx) < 25 and abs(by1 - sy) < 25 for (sx, sy, _, _) in seen_regions
            )
            if already_covered:
                continue
            seen_regions.append((bx1, by1, bw1, bh1))
            seen_regions.append((bx2, by2, bw2, bh2))

            best_corr = max(best_corr, ncc)
            best_cluster_size = max(best_cluster_size, len(pairs))

            for rx, ry, rw, rh in ((bx1, by1, bw1, bh1), (bx2, by2, bw2, bh2)):
                orig_box = _clamp_box(
                    int(round(rx * inv_scale)),
                    int(round(ry * inv_scale)),
                    max(1, int(round(rw * inv_scale))),
                    max(1, int(round(rh * inv_scale))),
                    orig_w,
                    orig_h,
                    page_idx,
                )
                if orig_box is not None:
                    boxes.append(orig_box)

    if not boxes:
        # Exact duplicated two-dimensional ink components: useful for sparse stamps
        # where ORB has too few distinctive keypoints. Repeated logos remain benign alternatives.
        _, _, stats, _ = cv2.connectedComponentsWithStats((gray_orig < 100).astype(np.uint8))
        candidates=[tuple(map(int,r[:4])) for r in stats[1:] if r[2]>=32 and r[3]>=32 and 0.15<=r[2]/r[3]<=6 and r[4]>=300 and r[2]*r[3]<0.15*orig_w*orig_h]
        for i,a in enumerate(candidates[:100]):
            for b in candidates[i+1:100]:
                if a[2:]!=b[2:] or np.hypot(a[0]-b[0],a[1]-b[1])<max(a[2],a[3]): continue
                ax,ay,w,h=a; bx,by,_,_=b
                if not np.array_equal(gray_orig[ay:ay+h,ax:ax+w],gray_orig[by:by+h,bx:bx+w]): continue
                pair=[_clamp_box(x,y,w,h,orig_w,orig_h,page_idx) for x,y,w,h in (a,b)]
                return "suspicious",0.65,0.75,[b for b in pair if b is not None],f"Page {page_idx}: exact duplicated ink component; repeated logos or stamps may be legitimate."
    if boxes:
        # Contextual reliability check: header/footer logos or 3+ repetitive layout elements
        # cannot be assumed to be forgery from pixel similarity alone.
        margin_branding_only = True
        for i in range(0, len(boxes), 2):
            if i + 1 >= len(boxes):
                margin_branding_only = False
                break
            b1, b2 = boxes[i], boxes[i + 1]
            c1_y = (b1.y + b1.h * 0.5) / float(orig_h)
            c2_y = (b2.y + b2.h * 0.5) / float(orig_h)
            in_margin_1 = c1_y < 0.18 or c1_y > 0.82
            in_margin_2 = c2_y < 0.18 or c2_y > 0.82
            if not (in_margin_1 and in_margin_2):
                margin_branding_only = False
                break

        repetitive_grid = len(boxes) >= 6  # 3+ duplicated pairs suggests repetitive layout/watermarks

        if margin_branding_only or repetitive_grid:
            reason = (
                "header/footer margin placement (consistent with repeated branding/logos)"
                if margin_branding_only
                else "repetitive multi-instance layout pattern"
            )
            detail = (
                f"Page {page_idx}: detected {len(boxes) // 2} duplicated region pair(s) "
                f"(max cluster={best_cluster_size} matches, patch NCC={best_corr:.2f}), "
                f"but {reason} prevents determining whether this is unauthorized cloning or legitimate repetition."
            )
            return "inconclusive", 0.22, 0.40, boxes, detail

        raw_score = (
            0.42
            + min(0.22, (best_cluster_size - MIN_CLUSTER_MATCHES) * 0.015)
            + min(0.14, (best_corr - MIN_PATCH_CORR) * 0.8)
        )
        score = float(np.clip(raw_score, 0.40, 0.80))
        confidence = float(np.clip(0.50 + (best_corr - MIN_PATCH_CORR) * 1.2, 0.50, 0.72))
        detail = (
            f"Page {page_idx}: found {len(boxes) // 2} duplicated region pair(s) in document body "
            f"(max cluster={best_cluster_size} matches, patch NCC={best_corr:.2f}). "
            "Note: pixel duplication alone cannot distinguish unauthorized cloning from legitimate repeated stamps or logos without a reference template."
        )
        return "suspicious", score, confidence, boxes, detail

    return (
        "passed",
        0.05,
        0.70,
        [],
        f"Page {page_idx}: no consistent copy-move region clusters detected across {len(keypoints)} keypoints.",
    )


class CopyMoveDetector:
    """Copy-move detector implementing the shared Detector protocol."""

    name = "copy_move"

    def analyze(
        self, source: Path, pages: list[Path], fields: dict[str, Any]
    ) -> list[DetectorResult]:
        target_pages = list(pages) if pages else []
        if not target_pages:
            try:
                src = Path(source)
                if src.exists() and src.is_file() and src.suffix.lower() in IMAGE_EXTENSIONS:
                    target_pages = [src]
            except TypeError:
                target_pages = []

        if not target_pages:
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="error",
                    evidence="No rendered page images available for copy-move analysis.",
                    boxes=[],
                )
            ]

        all_boxes: list[BoundingBox] = []
        page_details: list[str] = []
        max_score = 0.0
        confidences: list[float] = []
        statuses: list[str] = []

        for idx, page_path in enumerate(target_pages):
            try:
                p = Path(page_path)
                if not p.exists() or not p.is_file():
                    statuses.append("error")
                    page_details.append(f"Page {idx}: file missing ({p.name}).")
                    continue
                status, score, conf, boxes, detail = _analyze_page(p, idx)
                statuses.append(status)
                max_score = max(max_score, score)
                confidences.append(conf)
                all_boxes.extend(boxes)
                page_details.append(detail)
            except Exception as exc:
                statuses.append("error")
                page_details.append(f"Page {idx}: copy-move analysis failed ({exc}).")

        if "suspicious" in statuses:
            final_status = "suspicious"
        elif "inconclusive" in statuses:
            final_status = "inconclusive"
        elif "passed" in statuses:
            final_status = "passed"
        else:
            final_status = "error"

        final_conf = float(np.mean(confidences)) if confidences else 0.0
        return [
            DetectorResult(
                name=self.name,
                score=round(max_score, 4),
                confidence=round(final_conf, 4),
                status=final_status,
                evidence=" ".join(page_details),
                boxes=all_boxes,
            )
        ]


def analyze(
    source: Path, pages: list[Path], fields: dict[str, Any]
) -> list[DetectorResult]:
    """Module-level entry point matching the Detector protocol."""
    return CopyMoveDetector().analyze(source, pages, fields)
