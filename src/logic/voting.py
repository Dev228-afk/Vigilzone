"""
K-of-N temporal voting logic
"""
from collections import deque
from typing import Dict, Tuple


class KofNVoter:
    """
    K-of-N temporal confirmation
    Keeps track of last N triggers and confirms if K are true
    """
    
    def __init__(self, k: int = 3, n: int = 5):
        self.k = k
        self.n = n
        self.buffer = deque(maxlen=n)
    
    def vote(self, trigger: bool) -> Tuple[bool, int]:
        """
        Add a new observation and check if threshold is met
        Args:
            trigger: Whether current frame triggered
        Returns:
            (confirmed, hits) - confirmed is True if K-of-N threshold met
        """
        self.buffer.append(trigger)
        hits = sum(self.buffer)
        confirmed = hits >= self.k
        return confirmed, hits
    
    def reset(self):
        """Clear the buffer"""
        self.buffer.clear()
    
    def get_stats(self) -> Dict[str, int]:
        """Get current voting statistics"""
        return {
            "k": self.k,
            "n": self.n,
            "hits": sum(self.buffer),
            "buffer_size": len(self.buffer)
        }
