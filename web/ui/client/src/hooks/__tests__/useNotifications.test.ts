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

// Mock fetch
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

import { useNotifications } from '../useNotifications';

describe('useNotifications', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lastCreatedWebSocket = null;
    mockSend.mockClear();
    mockClose.mockClear();
  });

  describe('connect', () => {
    it('should create WebSocket connection with correct URL', () => {
      const { result } = renderHook(() => useNotifications());
      
      act(() => {
        result.current.connect('test-token', 1);
      });

      expect(WebSocket).toHaveBeenCalledWith(
        'ws://localhost:8000/ws/notifications/?token=test-token&tenant_id=1'
      );
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

      // Simulate receiving notification
      act(() => {
        if (lastCreatedWebSocket?.onmessage) {
          lastCreatedWebSocket.onmessage(new MessageEvent('message', {
            data: JSON.stringify({
              type: 'notification',
              title: 'New Alert',
              message: 'Alert message',
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
        json: () => Promise.resolve({ success: true }),
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

      // Simulate connection and notification
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
});
