"""
Configuration loader
"""
import yaml
from pathlib import Path
from typing import Dict, Any, List


class Config:
    """Configuration manager"""
    
    def __init__(self, config_dir: str = "configs"):
        self.config_dir = Path(config_dir)
        self._cameras = None
        self._zones = None
        self._models = None
        self._policy = None
    
    def load_cameras(self) -> List[Dict[str, Any]]:
        """Load camera configurations"""
        if self._cameras is None:
            with open(self.config_dir / "cameras.yaml", "r") as f:
                data = yaml.safe_load(f)
                self._cameras = data.get("cameras", [])
        return self._cameras
    
    def load_zones(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load zone configurations"""
        if self._zones is None:
            with open(self.config_dir / "zones.yaml", "r") as f:
                data = yaml.safe_load(f)
                self._zones = data.get("zones", {})
        return self._zones
    
    def load_models(self) -> Dict[str, Any]:
        """Load model configurations"""
        if self._models is None:
            with open(self.config_dir / "models.yaml", "r") as f:
                self._models = yaml.safe_load(f)
        return self._models
    
    def get_camera_config(self, camera_id: str) -> Dict[str, Any]:
        """Get configuration for a specific camera"""
        cameras = self.load_cameras()
        for cam in cameras:
            if cam["camera_id"] == camera_id:
                return cam
        raise ValueError(f"Camera {camera_id} not found in configuration")
    
    def get_zones_for_camera(self, camera_id: str) -> List[Dict[str, Any]]:
        """Get zones for a specific camera"""
        zones = self.load_zones()
        return zones.get(camera_id, [])

    def load_policy(self) -> Dict[str, Any]:
        """Load identity policy configuration"""
        if self._policy is None:
            policy_path = self.config_dir / "policy.yaml"
            if policy_path.exists():
                with open(policy_path, "r") as f:
                    data = yaml.safe_load(f) or {}
                    self._policy = data.get("policy", {})
            else:
                self._policy = {}
        return self._policy
