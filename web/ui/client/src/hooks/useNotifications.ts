/**
 * WebSocket notification hook for real-time alerts.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from './use-toast';
import { playChime } from '@/lib/audio';

export interface Notification {
  id: string;
  type: 'notification' | 'connection_established' | 'subscribed';
  notification_type?: 'incident' | 'broadcast' | 'test' | 'direct';
  title: string;
  message: string;
  data?: {
    incident_id?: number;
    severity?: number;
    severity_level?: string;
    camera_name?: string;
    [key: string]: unknown;
  };
  created_at: string;
  incident_id?: number;
  severity?: number;
  severity_level?: string;
  camera_name?: string;
  alert_id?: number;
  is_read?: boolean;
}

export interface UseNotificationsReturn {
  notifications: Notification[];
  unreadCount: number;
  isConnected: boolean;
  isSubscribed: boolean;
  redisReachable: boolean;
  error: string | null;
  connect: (token: string, tenantId: number) => void;
  disconnect: () => void;
  markAsRead: (notificationIds: number[]) => Promise<void>;
  markAllAsRead: () => Promise<void>;
  testWebSocket: (tenantId: number) => Promise<void>;
  clearNotifications: () => void;
}

function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('accessToken') || sessionStorage.getItem('accessToken');
}

function resolveWsUrl(): string {
  const configured = import.meta.env.VITE_WS_URL as string | undefined;
  if (configured && configured.trim().length > 0) {
    return configured;
  }
  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}/ws/notifications/`;
  }
  return 'ws://localhost:8000/ws/notifications/';
}

interface UpsertResult {
  items: Notification[];
  inserted: boolean;
}

/**
 * Idempotent upsert of a notification into the list.
 * Returns both updated items and a flag indicating if this was a true insert (not an update).
 * 
 * Matching logic (in order of precedence):
 * 1. alert_id (most specific — directly references the Alert record)
 * 2. incident_id + created_at (for websocket-only events without alert_id)
 * 3. id (fallback)
 * 
 * This prevents duplicate unread count increments when the same notification
 * arrives via both WebSocket and REST hydration.
 */
export function upsertNotification(prev: Notification[], incoming: Notification): UpsertResult {
  const matchIndex = prev.findIndex((item) => {
    // Priority 1: match by alert_id (most reliable)
    if (incoming.alert_id && item.alert_id) {
      return item.alert_id === incoming.alert_id;
    }
    // Priority 2: match by incident_id + created_at (for websocket-only events)
    if (incoming.incident_id && item.incident_id && incoming.created_at && item.created_at) {
      return item.incident_id === incoming.incident_id && item.created_at === incoming.created_at;
    }
    // Priority 3: match by id (fallback for truly unique identifiers)
    return item.id === incoming.id;
  });

  // True insert: new notification
  if (matchIndex === -1) {
    const updated = [incoming, ...prev].slice(0, 100);
    return { items: updated, inserted: true };
  }

  // Update: merge with existing notification
  const copy = [...prev];
  copy[matchIndex] = {
    ...copy[matchIndex],
    ...incoming,
    is_read: incoming.is_read ?? copy[matchIndex].is_read,
  };
  return { items: copy, inserted: false };
}

export function mergeHydratedNotifications(prev: Notification[], incoming: Notification[]): Notification[] {
  const reversedIncoming = [...incoming].reverse();
  return reversedIncoming.reduce(
    (current, item) => upsertNotification(current, item).items,
    prev,
  );
}

export function mergeHydratedUnreadCount(prevUnreadCount: number, hydratedUnreadCount: number): number {
  return Math.max(prevUnreadCount, hydratedUnreadCount);
}

export function useNotifications(): UseNotificationsReturn {
  const queryClient = useQueryClient();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  const [isSubscribed, setIsSubscribed] = useState(false);
  const [redisReachable, setRedisReachable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const tokenRef = useRef<string | null>(null);
  const tenantIdRef = useRef<number | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 5;
  const healthIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const healthFailureCountRef = useRef(0);

  const stopHealthPolling = useCallback(() => {
    if (healthIntervalRef.current) {
      clearInterval(healthIntervalRef.current);
      healthIntervalRef.current = null;
    }
  }, []);

  const fetchTransportStatus = useCallback(async (token: string, tenantId: number) => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      return;
    }

    try {
      const response = await fetch('/api/notifications/transport-status/', {
        headers: {
          Authorization: `Bearer ${token}`,
          'X-Tenant-ID': String(tenantId),
        },
      });
      if (!response.ok) {
        setRedisReachable(false);
        healthFailureCountRef.current += 1;
        if (healthFailureCountRef.current >= 3) {
          stopHealthPolling();
        }
        return;
      }
      const payload = await response.json();
      setRedisReachable(Boolean(payload?.redis_reachable));
      healthFailureCountRef.current = 0;
    } catch {
      setRedisReachable(false);
      healthFailureCountRef.current += 1;
      if (healthFailureCountRef.current >= 3) {
        stopHealthPolling();
      }
    }
  }, [stopHealthPolling]);

  const startHealthPolling = useCallback((token: string, tenantId: number) => {
    stopHealthPolling();
    healthFailureCountRef.current = 0;

    fetchTransportStatus(token, tenantId);
    healthIntervalRef.current = setInterval(() => {
      if (tokenRef.current && tenantIdRef.current) {
        fetchTransportStatus(tokenRef.current, tenantIdRef.current);
      }
    }, 15000);
  }, [fetchTransportStatus, stopHealthPolling]);

  const hydrateNotifications = useCallback(async (token: string, tenantId: number) => {
    try {
      const headers = {
        Authorization: `Bearer ${token}`,
        'X-Tenant-ID': String(tenantId),
      };

      const [listResp, unreadResp] = await Promise.all([
        fetch('/api/notifications/?limit=50', { headers }),
        fetch('/api/notifications/unread-count/', { headers }),
      ]);

      if (listResp.ok) {
        const listJson = await listResp.json();
        const items = Array.isArray(listJson?.notifications) ? listJson.notifications : [];
        const mapped: Notification[] = items.map((item: Record<string, unknown>) => {
          const data = (item.data as Record<string, unknown>) || {};
          const severity = (item.severity as number | undefined) ?? (data.severity as number | undefined);
          const severityLevel = (item.severity_level as string | undefined) ?? (data.severity_level as string | undefined);
          const cameraName = (item.camera_name as string | undefined) ?? (data.camera_name as string | undefined);
          const incidentId = (item.incident_id as number | undefined) ?? (data.incident_id as number | undefined);
          const alertId = Number(item.alert_id ?? item.id);
          return {
            id: `alert-${String(alertId)}`,
            type: 'notification',
            notification_type: 'incident',
            title: String(item.title ?? 'Notification'),
            message: String(item.message ?? ''),
            data,
            created_at: String(item.created_at ?? new Date().toISOString()),
            incident_id: incidentId,
            severity,
            severity_level: severityLevel,
            camera_name: cameraName,
            alert_id: Number.isFinite(alertId) ? alertId : undefined,
            is_read: Boolean(item.is_read),
          };
        });
        setNotifications((prev) => mergeHydratedNotifications(prev, mapped));
      }

      if (unreadResp.ok) {
        const unreadJson = await unreadResp.json();
        const nextUnreadCount = Number(unreadJson?.unread_count ?? 0);
        setUnreadCount((prev) => mergeHydratedUnreadCount(prev, nextUnreadCount));
      }
    } catch (err) {
      console.error('[Notifications] Failed to hydrate:', err);
    }
  }, []);

  const connect = useCallback((token: string, tenantId: number) => {
    if (
      wsRef.current &&
      wsRef.current.readyState === WebSocket.OPEN &&
      tokenRef.current === token &&
      tenantIdRef.current === tenantId
    ) {
      return;
    }

    if (wsRef.current) {
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
      wsRef.current.close();
    }

    tokenRef.current = token;
    tenantIdRef.current = tenantId;
    setError(null);
    setIsSubscribed(false);

    hydrateNotifications(token, tenantId);
    startHealthPolling(token, tenantId);

    const wsUrl = `${resolveWsUrl()}?token=${encodeURIComponent(token)}&tenant_id=${tenantId}`;

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);
        reconnectAttempts.current = 0;
        if (tokenRef.current && tenantIdRef.current) {
          startHealthPolling(tokenRef.current, tenantIdRef.current);
        }

        // Clear any previous ping interval before creating a new one (B3 fix)
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
        }
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          } else {
            clearInterval(pingIntervalRef.current!);
            pingIntervalRef.current = null;
          }
        }, 30000);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === 'connection_established' || data.type === 'subscribed') {
            setIsSubscribed(true);
            return;
          }
          if (data.type === 'pong') {
            return;
          }

          if (data.type === 'notification') {
            const payloadData = (data.data || {}) as Record<string, unknown>;
            const notification: Notification = {
              id: data.alert_id ? `alert-${String(data.alert_id)}` : `ws-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
              ...data,
              incident_id: (data.incident_id ?? payloadData.incident_id) as number | undefined,
              severity: (data.severity ?? payloadData.severity) as number | undefined,
              severity_level: (data.severity_level ?? payloadData.severity_level) as string | undefined,
              camera_name: (data.camera_name ?? payloadData.camera_name) as string | undefined,
              is_read: false,
            };

            // FIX: Track insertion status locally. Do NOT call side effects inside setNotifications.
            let wasInserted = false;
            let hasAlertId = false;

            setNotifications((prev) => {
              const result = upsertNotification(prev, notification);
              if (result.inserted) {
                wasInserted = true;
                hasAlertId = !!notification.alert_id;
              }
              return result.items;
            });

            // FIX: Defer side-effects to run immediately after the render phase tick
            setTimeout(() => {
              if (wasInserted && hasAlertId) {
                if (notification.incident_id) {
                  setUnreadCount((current) => current + 1);
                  playChime();
                  
                  if (queryClient) {
                  // Opt out of immediate global invalidation to prevent backend DDoS.
                  // Only refresh specific Incident query to keep cards live.
                  if (notification.incident_id) {
                    queryClient.invalidateQueries({ queryKey: ["incident", String(notification.incident_id)] });
                  }
                }
              }
            }
          }, 0);
          }
        } catch (err) {
          console.error('[WS] Failed to parse message:', err);
        }
      };

      ws.onerror = () => {
        setError('WebSocket connection error');
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        setIsSubscribed(false);

        // Debug-only toast for connection loss (as requested)
        if (typeof window !== 'undefined' && window.location.pathname === "/debug") {
          toast({
            title: "WebSocket Disconnected",
            description: "Live subscription lost. Check backend logs.",
            variant: "destructive",
          });
        }

        // Clean up ping interval on close (B3 fix)
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }
        wsRef.current = null;

        if (event.code !== 1000 && reconnectAttempts.current < maxReconnectAttempts) {
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
          reconnectTimeoutRef.current = setTimeout(() => {
            reconnectAttempts.current += 1;
            if (tokenRef.current && tenantIdRef.current) {
              connect(tokenRef.current, tenantIdRef.current);
            }
          }, delay);
        } else {
          stopHealthPolling();
        }
      };

      wsRef.current = ws;
    } catch (err) {
      console.error('[WS] Failed to create WebSocket:', err);
      setError('Failed to connect to notification server');
    }
  }, [hydrateNotifications, startHealthPolling, stopHealthPolling]);

  const disconnect = useCallback(() => {
    reconnectAttempts.current = maxReconnectAttempts;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    stopHealthPolling();
    if (wsRef.current) {
      wsRef.current.close(1000, 'User disconnected');
      wsRef.current = null;
    }
    setIsConnected(false);
    setIsSubscribed(false);
    setRedisReachable(false);
  }, [stopHealthPolling]);

  const markAsRead = useCallback(async (notificationIds: number[]) => {
    const token = getStoredToken();
    if (!token) return;

    try {
      const response = await fetch('/api/notifications/mark-read/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
          'X-Tenant-ID': String(tenantIdRef.current || ''),
        },
        body: JSON.stringify({ notification_ids: notificationIds }),
      });

      if (response.ok) {
        setNotifications((prev) => prev.map((n) => (
          n.alert_id && notificationIds.includes(n.alert_id) ? { ...n, is_read: true } : n
        )));
        setUnreadCount((prev) => Math.max(0, prev - notificationIds.length));
      }
    } catch (err) {
      console.error('[Notifications] Failed to mark as read:', err);
    }
  }, []);

  const markAllAsRead = useCallback(async () => {
    const token = tokenRef.current || getStoredToken();
    if (!token) return;

    try {
      const response = await fetch('/api/notifications/mark-read/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
          'X-Tenant-ID': String(tenantIdRef.current || ''),
        },
        body: JSON.stringify({ mark_all: true }),
      });

      if (response.ok) {
        setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
        setUnreadCount(0);
      }
    } catch (err) {
      console.error('[Notifications] Failed to mark all as read:', err);
    }
  }, []);

  const testWebSocket = useCallback(async (tenantId: number) => {
    const token = tokenRef.current || getStoredToken();
    if (!token) throw new Error('Missing auth token');

    const response = await fetch('/api/notifications/test-websocket/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        'X-Tenant-ID': String(tenantId),
      },
    });

    if (!response.ok) {
      throw new Error('Test notification failed');
    }
  }, []);

  const clearNotifications = useCallback(() => {
    setNotifications([]);
    setUnreadCount(0);
  }, []);

  useEffect(() => () => disconnect(), [disconnect]);

  return {
    notifications,
    unreadCount,
    isConnected,
    isSubscribed,
    redisReachable,
    error,
    connect,
    disconnect,
    markAsRead,
    markAllAsRead,
    testWebSocket,
    clearNotifications,
  };
}

