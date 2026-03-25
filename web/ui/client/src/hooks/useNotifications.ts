/**
 * WebSocket notification hook for real-time alerts.
 * 
 * Usage:
 *   const { notifications, unreadCount, connect, disconnect, markAsRead } = useNotifications();
 *   
 *   useEffect(() => {
 *     connect(token, tenantId);
 *     return () => disconnect();
 *   }, [token, tenantId]);
 */

import { useState, useEffect, useCallback, useRef } from 'react';

export interface Notification {
  id: string;
  type: 'notification' | 'connection_established' | 'subscribed';
  notification_type?: 'incident' | 'broadcast' | 'test' | 'direct';
  title: string;
  message: string;
  data?: {
    incident_id?: number;
    severity?: number;
    camera_name?: string;
    [key: string]: unknown;
  };
  created_at: string;
  incident_id?: number;  // Top-level incident_id (from alert_id inclusion in backend)
  severity?: number;
  camera_name?: string;
  alert_id?: number;  // The actual Alert database ID for mark-as-read
}

export interface UseNotificationsReturn {
  notifications: Notification[];
  unreadCount: number;
  isConnected: boolean;
  error: string | null;
  connect: (token: string, tenantId: number) => void;
  disconnect: () => void;
  markAsRead: (notificationIds: number[]) => Promise<void>;
  markAllAsRead: () => Promise<void>;
  testWebSocket: (tenantId: number) => Promise<void>;
  clearNotifications: () => void;
}

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws/notifications/';

export function useNotifications(): UseNotificationsReturn {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const tokenRef = useRef<string | null>(null);
  const tenantIdRef = useRef<number | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 5;

  const connect = useCallback((token: string, tenantId: number) => {
    // Clean up existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    tokenRef.current = token;
    tenantIdRef.current = tenantId;
    setError(null);

    const wsUrl = `${WS_URL}?token=${token}&tenant_id=${tenantId}`;
    console.log('[WS] Connecting to:', wsUrl.replace(token, '***'));

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('[WS] Connected');
        setIsConnected(true);
        setError(null);
        reconnectAttempts.current = 0;

        // Start ping interval to keep connection alive
        const pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          } else {
            clearInterval(pingInterval);
          }
        }, 30000);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('[WS] Received:', data);

          if (data.type === 'connection_established' || data.type === 'subscribed') {
            // Connection confirmation - no need to add to notifications
            return;
          }

          if (data.type === 'pong') {
            // Ping response - connection is alive
            return;
          }

          if (data.type === 'notification') {
            const notification: Notification = {
              id: `ws-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
              ...data,
            };

            setNotifications(prev => [notification, ...prev].slice(0, 100)); // Keep last 100
            setUnreadCount(prev => prev + 1);

            // Play notification sound
            playNotificationSound();
          }
        } catch (err) {
          console.error('[WS] Failed to parse message:', err);
        }
      };

      ws.onerror = (event) => {
        console.error('[WS] Error:', event);
        setError('WebSocket connection error');
      };

      ws.onclose = (event) => {
        console.log('[WS] Disconnected:', event.code, event.reason);
        setIsConnected(false);
        wsRef.current = null;

        // Auto-reconnect if not intentionally closed
        if (event.code !== 1000 && reconnectAttempts.current < maxReconnectAttempts) {
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
          console.log(`[WS] Reconnecting in ${delay}ms... (attempt ${reconnectAttempts.current + 1})`);
          
          reconnectTimeoutRef.current = setTimeout(() => {
            reconnectAttempts.current++;
            if (tokenRef.current && tenantIdRef.current) {
              connect(tokenRef.current, tenantIdRef.current);
            }
          }, delay);
        }
      };

      wsRef.current = ws;
    } catch (err) {
      console.error('[WS] Failed to create WebSocket:', err);
      setError('Failed to connect to notification server');
    }
  }, []);

  const disconnect = useCallback(() => {
    reconnectAttempts.current = maxReconnectAttempts; // Prevent auto-reconnect
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    if (wsRef.current) {
      wsRef.current.close(1000, 'User disconnected');
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const markAsRead = useCallback(async (notificationIds: number[]) => {
    // Get token from localStorage directly
    const token = typeof window !== 'undefined' ? localStorage.getItem("accessToken") : null;
    
    if (!token) {
      console.error('[Notifications] No auth token found');
      return;
    }
    
    try {
      const response = await fetch('/api/notifications/mark-read/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
          'X-Tenant-ID': String(tenantIdRef.current || ''),
        },
        body: JSON.stringify({ notification_ids: notificationIds }),
      });

      if (response.ok) {
        setUnreadCount(prev => Math.max(0, prev - notificationIds.length));
      } else {
        console.error('[Notifications] Failed to mark as read:', response.status);
      }
    } catch (err) {
      console.error('[Notifications] Failed to mark as read:', err);
    }
  }, []);

  const markAllAsRead = useCallback(async () => {
    try {
      const response = await fetch('/api/notifications/mark-read/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${tokenRef.current}`,
          'X-Tenant-ID': String(tenantIdRef.current || ''),
        },
        body: JSON.stringify({ mark_all: true }),
      });

      if (response.ok) {
        setUnreadCount(0);
      }
    } catch (err) {
      console.error('[Notifications] Failed to mark all as read:', err);
    }
  }, []);

  const testWebSocket = useCallback(async (tenantId: number) => {
    try {
      const response = await fetch('/api/notifications/test-websocket/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${tokenRef.current}`,
          'X-Tenant-ID': String(tenantId),
        },
      });

      if (!response.ok) {
        throw new Error('Test notification failed');
      }
    } catch (err) {
      console.error('[Notifications] Test failed:', err);
      throw err;
    }
  }, []);

  const clearNotifications = useCallback(() => {
    setNotifications([]);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    notifications,
    unreadCount,
    isConnected,
    error,
    connect,
    disconnect,
    markAsRead,
    markAllAsRead,
    testWebSocket,
    clearNotifications,
  };
}

// Play a notification sound
function playNotificationSound() {
  try {
    // Create a simple beep sound using Web Audio API
    const audioContext = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();

    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);

    oscillator.frequency.value = 800;
    oscillator.type = 'sine';
    gainNode.gain.value = 0.1;

    oscillator.start();
    oscillator.stop(audioContext.currentTime + 0.1);
  } catch (err) {
    // Audio not supported or blocked
    console.log('[Notifications] Could not play sound');
  }
}

// Export singleton for global notification state
export const notificationStore = {
  listeners: new Set<(notifications: Notification[], unreadCount: number) => void>(),
  
  subscribe(callback: (notifications: Notification[], unreadCount: number) => void) {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  },
  
  notify(notifications: Notification[], unreadCount: number) {
    this.listeners.forEach(listener => listener(notifications, unreadCount));
  },
};
