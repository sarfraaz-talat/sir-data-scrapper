"""
Checkpoint management for tracking processing progress
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from .utils import ensure_dir


class CheckpointManager:
    """Manages checkpoints for download, parse, and DB stages."""
    
    def __init__(self, checkpoint_dir: Path = Path("data/checkpoints")):
        self.checkpoint_dir = ensure_dir(checkpoint_dir)
        self.latest_file = self.checkpoint_dir / "latest.json"
        self.checkpoints_dir = ensure_dir(self.checkpoint_dir / "history")
    
    def load_latest(self) -> Optional[Dict[str, Any]]:
        """Load the latest checkpoint."""
        if not self.latest_file.exists():
            return None
        
        try:
            with open(self.latest_file, 'r') as f:
                return json.load(f)
        except Exception:
            return None
    
    def save_checkpoint(
        self,
        state: str,
        assembly: str,
        stage: str,  # 'download', 'parse', 'db'
        status: str,  # 'completed', 'in_progress', 'failed'
        data: Dict[str, Any]
    ):
        """Save checkpoint for a constituency stage."""
        checkpoint = {
            'state': state,
            'assembly': assembly,
            'stage': stage,
            'status': status,
            'timestamp': datetime.utcnow().isoformat(),
            'data': data
        }
        
        # Update latest
        latest = self.load_latest() or {}
        if 'constituencies' not in latest:
            latest['constituencies'] = {}
        
        key = f"{state}/{assembly}"
        if key not in latest['constituencies']:
            latest['constituencies'][key] = {}
        
        latest['constituencies'][key][stage] = checkpoint
        latest['last_updated'] = datetime.utcnow().isoformat()
        
        # Save latest
        with open(self.latest_file, 'w') as f:
            json.dump(latest, f, indent=2)
        
        # Save timestamped copy
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        history_file = self.checkpoints_dir / f"{timestamp}_{state}_{assembly}_{stage}.json"
        with open(history_file, 'w') as f:
            json.dump(checkpoint, f, indent=2)
        
        return checkpoint
    
    def get_constituency_status(self, state: str, assembly: str) -> Dict[str, Any]:
        """Get status of a specific constituency."""
        latest = self.load_latest()
        if not latest:
            return {}
        
        key = f"{state}/{assembly}"
        return latest.get('constituencies', {}).get(key, {})
    
    def is_constituency_complete(self, state: str, assembly: str) -> bool:
        """Check if a constituency is fully processed (all stages complete)."""
        status = self.get_constituency_status(state, assembly)
        return (
            status.get('download', {}).get('status') == 'completed' and
            status.get('parse', {}).get('status') == 'completed' and
            status.get('db', {}).get('status') == 'completed'
        )
    
    def get_incomplete_constituencies(self) -> list:
        """Get list of constituencies that are not fully processed."""
        latest = self.load_latest()
        if not latest:
            return []
        
        incomplete = []
        for key, status in latest.get('constituencies', {}).items():
            if not self.is_constituency_complete(*key.split('/', 1)):
                incomplete.append(key)
        
        return incomplete

