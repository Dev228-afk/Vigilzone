/**
 * WebSocket notification hook for real-time alerts.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from './use-toast';
import { playChime, unlockAudio } from '@/lib/audio';

export interface Notification {
  id: string;
  type: 'notification' | 'connection_established' | 'subscribed';
  notification_type?: 'incident' | 'broadcast' | 'test' | 'direct';
  title: string;
  message: string;
  data?: {
    incident_id?: string | number;
    severity?: number;
    severity_level?: string;
    camera_name?: string;
    [key: string]: unknown;
  };
  created_at: string;
  incident_id?: string | number;
  severity?: number;
  severity_level?: string;
  camera_name?: string;
  alert_id?: string;
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
  markAsRead: (notificationIds: string[]) => Promise<void>;
  markAllAsRead: () => Promise<void>;
  testWebSocket: (tenantId: number) => Promise<void>;
  clearNotifications: () => void;
}

function normalizeId(value: unknown): string | undefined {
  if (value === null || value === undefined) return undefined;
  const normalized = String(value).trim();
  return normalized.length > 0 ? normalized : undefined;
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
    // In development, Vite's middleware-mode proxy does not reliably forward
    // WebSocket upgrade requests.  Connect directly to the Django/Daphne
    // backend on port 8000.  In production the reverse-proxy (nginx) handles
    // the upgrade so we can use the same host.
    const backendPort = import.meta.env.VITE_BACKEND_PORT || '8000';
    const isDev = import.meta.env.DEV;
    if (isDev) {
      return `${protocol}//${window.location.hostname}:${backendPort}/ws/notifications/`;
    }
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
    const incomingAlertId = normalizeId(incoming.alert_id);
    const itemAlertId = normalizeId(item.alert_id);

    // Priority 1: match by alert_id (most reliable)
    if (incomingAlertId && itemAlertId) {
      return itemAlertId === incomingAlertId;
    }

    // Priority 2: match by incident_id + created_at (for websocket-only events)
    const incomingIncidentId = normalizeId(incoming.incident_id);
    const itemIncidentId = normalizeId(item.incident_id);
    if (incomingIncidentId && itemIncidentId && incoming.created_at && item.created_at) {
      return itemIncidentId === incomingIncidentId && item.created_at === incoming.created_at;
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
  // Track processed alert IDs to avoid duplicate unread increments.
  const processedAlertIds = useRef<Set<string>>(new Set());
  const audioUnlockedRef = useRef(false);

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
        
        // Add this quick loop to register hydrated IDs
        items.forEach((item: any) => {
          const alertId = normalizeId(item.alert_id ?? item.id);
          if (alertId) processedAlertIds.current.add(alertId);
        });

        const mapped: Notification[] = items.map((item: Record<string, unknown>) => {
          const data = (item.data as Record<string, unknown>) || {};
          const severity = (item.severity as number | undefined) ?? (data.severity as number | undefined);
          const severityLevel = (item.severity_level as string | undefined) ?? (data.severity_level as string | undefined);
          const cameraName = (item.camera_name as string | undefined) ?? (data.camera_name as string | undefined);
          const incidentId = (item.incident_id as string | number | undefined) ?? (data.incident_id as string | number | undefined);
          const alertId = normalizeId(item.alert_id ?? item.id);
          
          return {
            id: alertId ? `alert-${alertId}` : `alert-${String(item.id ?? Date.now())}`,
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
            alert_id: alertId,
            is_read: Boolean(item.is_read),
          };
        });
        setNotifications((prev) => mergeHydratedNotifications(prev, mapped));
      }

      if (unreadResp.status === 401) {
        console.warn('[Notifications] 401 Unauthorized during hydration. Token may be invalid.');
      }

      if (unreadResp.ok) {
        const unreadJson = await unreadResp.json();
        const nextUnreadCount = Number(unreadJson?.unread_count ?? 0);
        console.log('[Notifications] Hydrated unread count:', nextUnreadCount);
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
        console.log('[WS] WebSocket Connected to:', wsUrl);
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

          if (data.type === 'NEW_NOTIFICATION' || data.type === 'notification') {
            const payloadData = (data.data || {}) as Record<string, unknown>;
            
            // Normalize ID: use alert_id with prefix if available, else random
            const notification: Notification = {
              id: data.alert_id ? `alert-${String(data.alert_id)}` : `ws-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
              ...data,
              incident_id: (data.incident_id ?? payloadData.incident_id) as string | number | undefined,
              severity: (data.severity ?? payloadData.severity) as number | undefined,
              severity_level: (data.severity_level ?? payloadData.severity_level) as string | undefined,
              camera_name: (data.camera_name ?? payloadData.camera_name) as string | undefined,
              is_read: false,
            };

            // 1. Process side-effects using the Ref (Sync check)
            const alertId = normalizeId(data.alert_id ?? data.id);
            if (alertId && !processedAlertIds.current.has(alertId)) {
              processedAlertIds.current.add(alertId);
              
              // Use absolute count if provided, otherwise increment
              if (typeof data.unread_count === 'number') {
                console.log(`[WS] Setting absolute unread count: ${data.unread_count}`);
                setUnreadCount(data.unread_count);
              } else {
                setUnreadCount((current) => current + 1);
              }
              
              playChime();

              // Force React Query components (Incident Cards) to pull fresh data
              if (queryClient && notification.incident_id) {
                queryClient.invalidateQueries({ queryKey: ["incident", String(notification.incident_id)] });
              }
            }

            // 2. Safely push the notification object into the dropdown list array
            setNotifications((prev) => upsertNotification(prev, notification).items);
          }
        } catch (err) {
          console.error('[WS] Failed to parse message:', err);
        }
      };

      ws.onerror = (error) => {
        console.error('[WS] WebSocket Error:', error);
        setError('WebSocket connection error');
      };

      ws.onclose = (event) => {
        console.log(`[WS] WebSocket Closed: code=${event.code}, reason=${event.reason}`);
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

  const markAsRead = useCallback(async (notificationIds: string[]) => {
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
        const readIds = new Set(notificationIds.map((id) => normalizeId(id)).filter(Boolean) as string[]);
        setNotifications((prev) => prev.map((n) => (
          n.alert_id && readIds.has(n.alert_id) ? { ...n, is_read: true } : n
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

  useEffect(() => {
    const unlockFromInteraction = () => {
      if (audioUnlockedRef.current) return;
      audioUnlockedRef.current = true;
      void unlockAudio();
      window.removeEventListener('pointerdown', unlockFromInteraction);
      window.removeEventListener('keydown', unlockFromInteraction);
      window.removeEventListener('touchstart', unlockFromInteraction);
    };

    window.addEventListener('pointerdown', unlockFromInteraction, { passive: true });
    window.addEventListener('keydown', unlockFromInteraction, { passive: true });
    window.addEventListener('touchstart', unlockFromInteraction, { passive: true });

    return () => {
      window.removeEventListener('pointerdown', unlockFromInteraction);
      window.removeEventListener('keydown', unlockFromInteraction);
      window.removeEventListener('touchstart', unlockFromInteraction);
    };
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

