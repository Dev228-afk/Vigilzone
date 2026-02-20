"""
Simple IoU-based tracker for person detections
"""
import numpy as np
from typing import List, Tuple, Optional


def compute_iou(box1: List[float], box2: List[float]) -> float:
    """
    Compute IoU between two boxes [x1, y1, x2, y2]
    """
    x1_min, y1_min, x1_max, y1_max = box1
    x2_min, y2_min, x2_max, y2_max = box2
    
    # Intersection
    inter_x_min = max(x1_min, x2_min)
    inter_y_min = max(y1_min, y2_min)
    inter_x_max = min(x1_max, x2_max)
    inter_y_max = min(y1_max, y2_max)
    
    inter_width = max(0, inter_x_max - inter_x_min)
    inter_height = max(0, inter_y_max - inter_y_min)
    inter_area = inter_width * inter_height
    
    # Union
    box1_area = (x1_max - x1_min) * (y1_max - y1_min)
    box2_area = (x2_max - x2_min) * (y2_max - y2_min)
    union_area = box1_area + box2_area - inter_area
    
    if union_area == 0:
        return 0.0
    
    return inter_area / union_area


class IOUTracker:
    """Simple IoU-based tracker"""
    
    def __init__(self, iou_threshold: float = 0.3, max_age: int = 30):
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.tracks = {}  # track_id -> {"box": [x1,y1,x2,y2], "age": int}
        self.next_id = 1
    
    def update(self, detections: List[Tuple[List[float], float]]) -> List[Tuple[List[float], float, int]]:
        """
        Update tracker with new detections
        Args:
            detections: List of (box, confidence) where box is [x1, y1, x2, y2]
        Returns:
            List of (box, confidence, track_id)
        """
        # Age existing tracks
        for track_id in list(self.tracks.keys()):
            self.tracks[track_id]["age"] += 1
            if self.tracks[track_id]["age"] > self.max_age:
                del self.tracks[track_id]
        
        if not detections:
            return []
        
        # Match detections to existing tracks
        matched_tracks = set()
        results = []
        
        for box, conf in detections:
            best_iou = 0
            best_track_id = None
            
            for track_id, track_data in self.tracks.items():
                if track_id in matched_tracks:
                    continue
                
                iou = compute_iou(box, track_data["box"])
                if iou > best_iou and iou > self.iou_threshold:
                    best_iou = iou
                    best_track_id = track_id
            
            if best_track_id is not None:
                # Update existing track
                self.tracks[best_track_id]["box"] = box
                self.tracks[best_track_id]["age"] = 0
                matched_tracks.add(best_track_id)
                results.append((box, conf, best_track_id))
            else:
                # Create new track
                new_id = self.next_id
                self.next_id += 1
                self.tracks[new_id] = {"box": box, "age": 0}
                results.append((box, conf, new_id))
        
        return results
