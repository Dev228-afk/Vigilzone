"""
Zone utilities for point-in-polygon checks
"""
import numpy as np
from typing import List, Tuple


def point_in_polygon(point: Tuple[float, float], polygon: List[List[float]]) -> bool:
    """
    Check if a point is inside a polygon using ray casting algorithm
    Args:
        point: (x, y) coordinates
        polygon: List of [x, y] coordinates defining the polygon
    Returns:
        True if point is inside polygon
    """
    x, y = point
    n = len(polygon)
    inside = False
    
    p1x, p1y = polygon[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    
    return inside


def bbox_centroid(bbox: List[float]) -> Tuple[float, float]:
    """
    Calculate centroid of bounding box [x1, y1, x2, y2]
    Returns: (cx, cy)
    """
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def check_bbox_in_zones(bbox: List[float], zones: List[dict]) -> Tuple[bool, str]:
    """
    Check if bbox centroid is in any zone
    Args:
        bbox: [x1, y1, x2, y2]
        zones: List of zone dicts with 'name' and 'points'
    Returns:
        (is_in_zone, zone_name)
    """
    centroid = bbox_centroid(bbox)
    
    for zone in zones:
        if point_in_polygon(centroid, zone['points']):
            return True, zone['name']
    
    return False, ""
