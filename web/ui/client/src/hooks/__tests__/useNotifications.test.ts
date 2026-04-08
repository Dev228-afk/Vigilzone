/**
 * Unit tests for useNotifications hook
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the WebSocket - we need to track instances created by the hook
const mockSend = vi.fn();
const mockClose = vi.fn();

// Store handlers for the most recently created WebSocket instance
let lastCreatedWebSocket: {
  onopen: (() => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  send: typeof mockSend;
  close: typeof mockClose;
  readyState: number;
} | null = null;

// Factory function to create mock WebSocket instances
function createMockWebSocket(_url: string) {
  const ws = {
    onopen: null as (() => void) | null,
    onclose: null as ((event: CloseEvent) => void) | null,
    onerror: null as ((event: Event) => void) | null,
    onmessage: null as ((event: MessageEvent) => void) | null,
    send: mockSend,
    close: mockClose,
    readyState: 1 as const,
  };
  lastCreatedWebSocket = ws;
  return ws;
}

// Use vi.fn().mockImplementation to make it a spy that returns our mock
vi.stubGlobal('WebSocket', vi.fn(createMockWebSocket));

// Mock AudioContext for notification sounds
vi.stubGlobal('AudioContext', vi.fn(() => ({
  createOscillator: vi.fn(() => ({
    connect: vi.fn(),
    frequency: { value: 800 },
    type: 'sine',
    start: vi.fn(),
    stop: vi.fn(),
  })),
  destination: {},
  currentTime: 0,
})));

// Mock fetch with proper Response-like object
const mockFetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => ({ notifications: [], unread_count: 0 }),
});
vi.stubGlobal('fetch', mockFetch);

import { useNotifications } from '../useNotifications';

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('useNotifications', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lastCreatedWebSocket = null;
    mockSend.mockClear();
    mockClose.mockClear();
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ notifications: [], unread_count: 0 }),
    });
  });

  describe('connect', () => {
    it('should create WebSocket connection with correct URL', () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      // WebSocket should be called with a URL containing the token and tenant_id
      expect(WebSocket).toHaveBeenCalled();
      const callUrl = (WebSocket as any).mock.calls[0][0];
      expect(callUrl).toMatch(/ws:\/\/.+\/ws\/notifications\/\?token=test-token&tenant_id=1/);
    });

    it('should set isConnected to true on successful connection', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      // Simulate connection on the actual created WebSocket instance
      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });
    });

    it('should set isConnected to false on disconnect', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      act(() => {
        if (lastCreatedWebSocket?.onclose) {
          lastCreatedWebSocket.onclose(new CloseEvent('close', { code: 1000, reason: 'Normal close', wasClean: true }));
        }
      });

      await waitFor(() => {
        expect(result.current.isConnected).toBe(false);
      });
    });
  });

  describe('disconnect', () => {
    it('should close WebSocket connection', () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        result.current.disconnect();
      });

      expect(mockClose).toHaveBeenCalledWith(1000, 'User disconnected');
    });
  });

  describe('notifications', () => {
    it('should add notification when received', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      // Simulate receiving notification
      const notificationData = {
        type: 'notification',
        notification_type: 'incident',
        title: 'Test Incident',
        message: 'Test message',
        created_at: new Date().toISOString(),
      };

      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', { data: JSON.stringify(notificationData) }));
        }
      });

      await waitFor(() => {
        expect(result.current.notifications.length).toBe(1);
        expect(result.current.notifications[0].title).toBe('Test Incident');
      });
    });

    it('should increment unread count when notification received', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      expect(result.current.unreadCount).toBe(0);

      // Simulate receiving notification with alert_id (so unread count increments)
      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', {
            data: JSON.stringify({
              type: 'notification',
              title: 'New Alert',
              message: 'Alert message',
              alert_id: 42,
              created_at: new Date().toISOString(),
            }),
          }));
        }
      });

      await waitFor(() => {
        expect(result.current.unreadCount).toBe(1);
      });
    });

    it('should ignore connection_established messages', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      // Simulate receiving connection_established
      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', {
            data: JSON.stringify({
              type: 'connection_established',
              message: 'Connected',
            }),
          }));
        }
      });

      await waitFor(() => {
        expect(result.current.notifications.length).toBe(0);
      });
    });

    it('should ignore pong messages', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      // Simulate receiving pong
      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', {
            data: JSON.stringify({ type: 'pong' }),
          }));
        }
      });

      await waitFor(() => {
        expect(result.current.notifications.length).toBe(0);
      });
    });
  });

  describe('markAsRead', () => {
    it('should call API to mark notifications as read', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      });

      // Mock localStorage
      const localStorageMock = {
        getItem: vi.fn().mockReturnValue('test-token'),
        setItem: vi.fn(),
        removeItem: vi.fn(),
        clear: vi.fn(),
      };
      Object.defineProperty(window, 'localStorage', { value: localStorageMock, writable: true });

      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      // Simulate connection and notification with alert_id
      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', {
            data: JSON.stringify({
              type: 'notification',
              title: 'Test',
              message: 'Test',
              alert_id: 1,
              incident_id: 10,
              created_at: new Date().toISOString(),
            }),
          }));
        }
      });

      await waitFor(() => {
        expect(result.current.unreadCount).toBe(1);
      });

      // Mark as read
      await act(async () => {
        await result.current.markAsRead([1]);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/notifications/mark-read/',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
            'Authorization': 'Bearer test-token',
            'X-Tenant-ID': '1',
          }),
        })
      );
    });
  });

  describe('markAllAsRead', () => {
    it('should call API to mark all notifications as read', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ success: true }),
      });

      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      await act(async () => {
        await result.current.markAllAsRead();
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/notifications/mark-read/',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ mark_all: true }),
        })
      );
    });
  });

  describe('testWebSocket', () => {
    it('should call test-websocket API endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ success: true }),
      });

      const { result } = renderHook(() => useNotifications());
      
      await act(async () => {
        await result.current.testWebSocket(1);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/notifications/test-websocket/',
        expect.objectContaining({
          method: 'POST',
        })
      );
    });

    it('should throw error when API fails', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: () => Promise.resolve({ error: 'Server error' }),
      });

      // Mock localStorage with a token so the function proceeds
      Object.defineProperty(window, 'localStorage', { 
        value: { getItem: vi.fn().mockReturnValue('test-token'), setItem: vi.fn(), removeItem: vi.fn(), clear: vi.fn() }, 
        writable: true 
      });

      const { result } = renderHook(() => useNotifications());
      
      await expect(result.current.testWebSocket(1)).rejects.toThrow();
    });
  });

  describe('clearNotifications', () => {
    it('should clear all notifications', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      // Add some notifications
      for (let i = 0; i < 3; i++) {
        act(() => {
          if (lastCreatedWebSocket?.onmessage) {
            lastCreatedWebSocket.onmessage(new MessageEvent('message', {
              data: JSON.stringify({
                type: 'notification',
                title: `Notification ${i}`,
                message: 'Test',
                created_at: new Date().toISOString(),
              }),
            }));
          }
        });
      }

      await waitFor(() => {
        expect(result.current.notifications.length).toBe(3);
      });

      // Clear notifications
      act(() => {
        result.current.clearNotifications();
      });

      expect(result.current.notifications.length).toBe(0);
    });
  });

  describe('duplicate prevention and unread count accuracy (REGRESSION)', () => {
    it('should not insert duplicate notifications with same alert_id', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      const notificationWithAlertId = {
        type: 'notification',
        notification_type: 'incident',
        title: 'Incident Detected',
        message: 'Motion detected',
        alert_id: 42,
        incident_id: 10,
        created_at: '2026-03-28T10:00:00Z',
      };

      // Receive notification via WebSocket
      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', { 
            data: JSON.stringify(notificationWithAlertId) 
          }));
        }
      });

      await waitFor(() => {
        expect(result.current.notifications.length).toBe(1);
        expect(result.current.unreadCount).toBe(1);
      });

      // Receive same notification again (e.g., from REST hydration or duplicate WebSocket delivery)
      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', { 
            data: JSON.stringify(notificationWithAlertId) 
          }));
        }
      });

      // Should not create duplicate entry or increment unread count again
      await waitFor(() => {
        expect(result.current.notifications.length).toBe(1);
        expect(result.current.unreadCount).toBe(1);
      });
    });

    it('should not increment unread count when updating existing notification', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      const timestamp = '2026-03-28T10:00:00Z';
      const notification = {
        type: 'notification',
        notification_type: 'incident',
        title: 'Incident',
        message: 'Test',
        alert_id: 55,
        incident_id: 20,
        created_at: timestamp,
      };

      // First delivery
      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', { 
            data: JSON.stringify(notification) 
          }));
        }
      });

      await waitFor(() => {
        expect(result.current.unreadCount).toBe(1);
        expect(result.current.notifications.length).toBe(1);
      });

      // Second delivery with updated properties (e.g., more details)
      const updatedNotification = {
        ...notification,
        message: 'Updated message with more detail',
      };

      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', { 
            data: JSON.stringify(updatedNotification) 
          }));
        }
      });

      // Wait for the message to be updated, then verify unread count and list length haven't changed
      await waitFor(() => {
        expect(result.current.notifications[0].message).toBe('Updated message with more detail');
        // Still only 1 notification and unread count should not have changed
        expect(result.current.notifications.length).toBe(1);
        expect(result.current.unreadCount).toBe(1);
      });
    });

    it('should preserve websocket notifications when hydration resolves after connect', async () => {
      const listDeferred = createDeferred<{ ok: boolean; json: () => Promise<{ notifications: never[] }> }>();
      const unreadDeferred = createDeferred<{ ok: boolean; json: () => Promise<{ unread_count: number }> }>();

      mockFetch
        .mockReset()
        .mockImplementationOnce(() => listDeferred.promise)
        .mockImplementationOnce(() => unreadDeferred.promise);

      const { result } = renderHook(() => useNotifications());

      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      const notification = {
        type: 'notification',
        notification_type: 'incident',
        title: 'Race Condition Alert',
        message: 'Arrived before hydration',
        alert_id: 77,
        incident_id: 33,
        created_at: '2026-03-28T10:00:00Z',
      };

      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', {
            data: JSON.stringify(notification),
          }));
        }
      });

      await waitFor(() => {
        expect(result.current.notifications.length).toBe(1);
        expect(result.current.unreadCount).toBe(1);
      });

      await act(async () => {
        listDeferred.resolve({
          ok: true,
          json: async () => ({ notifications: [] }),
        });
        unreadDeferred.resolve({
          ok: true,
          json: async () => ({ unread_count: 0 }),
        });
        await Promise.all([listDeferred.promise, unreadDeferred.promise]);
      });

      await waitFor(() => {
        expect(result.current.notifications.length).toBe(1);
        expect(result.current.notifications[0].alert_id).toBe(77);
        expect(result.current.unreadCount).toBe(1);
      });
    });

    it('should match notifications by incident_id + created_at for websocket-only events without alert_id', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      const timestamp = '2026-03-28T10:30:00Z';
      const incidentNotification = {
        type: 'notification',
        notification_type: 'incident',
        title: 'Fire Detected',
        message: 'Fire alert',
        incident_id: 99,
        created_at: timestamp,
        // Note: no alert_id (might be a websocket-only event or AI service notification)
      };

      // First delivery
      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', { 
            data: JSON.stringify(incidentNotification) 
          }));
        }
      });

      await waitFor(() => {
        expect(result.current.notifications.length).toBe(1);
      });

      // Second delivery of same incident (should merge, not duplicate)
      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', { 
            data: JSON.stringify(incidentNotification) 
          }));
        }
      });

      expect(result.current.notifications.length).toBe(1);
      expect(result.current.notifications[0].incident_id).toBe(99);
    });

    it('should allow websocket-only notifications without alert_id to appear immediately', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      const wsOnlyNotification = {
        type: 'notification',
        notification_type: 'broadcast',
        title: 'System Maintenance',
        message: 'Server will restart in 5 minutes',
        created_at: new Date().toISOString(),
        // No alert_id — this is a broadcast/system notification
      };

      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', { 
            data: JSON.stringify(wsOnlyNotification) 
          }));
        }
      });

      await waitFor(() => {
        expect(result.current.notifications.length).toBe(1);
        expect(result.current.notifications[0].title).toBe('System Maintenance');
      });

      // Unread count should NOT increment for notifications without alert_id
      expect(result.current.unreadCount).toBe(0);
    });

    it('should prevent unread count inflation with rapid duplicate deliveries', async () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      act(() => {
        if (lastCreatedWebSocket?.onopen) {
          lastCreatedWebSocket.onopen();
        }
      });

      const notification = {
        type: 'notification',
        notification_type: 'incident',
        title: 'High Severity Alert',
        message: 'Critical event',
        alert_id: 300,
        incident_id: 100,
        created_at: '2026-03-28T11:00:00Z',
      };

      // Simulate rapid delivery of the same notification (e.g., network retry, duplicate broker delivery)
      for (let i = 0; i < 5; i++) {
        act(() => {
          if (lastCreatedWebSocket?.onmessage) {
            lastCreatedWebSocket.onmessage(new MessageEvent('message', { 
              data: JSON.stringify(notification) 
            }));
          }
        });
      }

      // Should still be 1 notification and unread count should be 1, not 5
      expect(result.current.notifications.length).toBe(1);
      expect(result.current.unreadCount).toBe(1);
    });
  });
});
