/**
 * Unit tests for NotificationBell component
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NotificationBell } from '../NotificationBell';
import type { Notification } from '../../hooks/useNotifications';

// Mock Notification type
const createMockNotification = (overrides: Partial<Notification> = {}): Notification => ({
  id: '1',
  type: 'notification',
  notification_type: 'incident',
  title: 'Test Incident',
  message: 'Test message',
  created_at: new Date().toISOString(),
  severity: 4,
  camera_name: 'Test Camera',
  ...overrides,
});

describe('NotificationBell', () => {
  const mockProps = {
    notifications: [] as Notification[],
    unreadCount: 0,
    isConnected: true,
    onMarkAsRead: vi.fn().mockResolvedValue(undefined),
    onMarkAllAsRead: vi.fn().mockResolvedValue(undefined),
    onTestConnection: vi.fn().mockResolvedValue(undefined),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render bell icon', () => {
      render(<NotificationBell {...mockProps} />);
      expect(screen.getByLabelText('Notifications')).toBeInTheDocument();
    });

    it('should not show badge when unreadCount is 0', () => {
      render(<NotificationBell {...mockProps} unreadCount={0} />);
      const badges = screen.queryAllByText(/^\d+$/);
      expect(badges.length).toBe(0);
    });

    it('should show badge when unreadCount > 0', () => {
      render(<NotificationBell {...mockProps} unreadCount={5} />);
      expect(screen.getByText('5')).toBeInTheDocument();
    });

    it('should show 9+ when unreadCount > 9', () => {
      render(<NotificationBell {...mockProps} unreadCount={15} />);
      expect(screen.getByText('9+')).toBeInTheDocument();
    });

    it('should show connected status indicator (green dot) when connected', () => {
      render(<NotificationBell {...mockProps} isConnected={true} />);
      const indicators = screen.getAllByTitle(/Connected/);
      expect(indicators.length).toBeGreaterThan(0);
    });

    it('should show disconnected status indicator (red dot) when not connected', () => {
      render(<NotificationBell {...mockProps} isConnected={false} />);
      const indicators = screen.getAllByTitle(/Disconnected/);
      expect(indicators.length).toBeGreaterThan(0);
    });
  });

  describe('Dropdown', () => {
    it('should open dropdown when bell is clicked', () => {
      render(<NotificationBell {...mockProps} />);
      
      fireEvent.click(screen.getByLabelText('Notifications'));
      
      expect(screen.getByText('Notifications')).toBeInTheDocument();
    });

    it('should show empty state when no notifications', () => {
      render(<NotificationBell {...mockProps} notifications={[]} />);
      
      fireEvent.click(screen.getByLabelText('Notifications'));
      
      expect(screen.getByText('No notifications yet')).toBeInTheDocument();
    });

    it('should show notifications when present', () => {
      const notifications = [
        createMockNotification({ id: '1', title: 'Alert 1' }),
        createMockNotification({ id: '2', title: 'Alert 2' }),
      ];
      
      render(<NotificationBell {...mockProps} notifications={notifications} />);
      
      fireEvent.click(screen.getByLabelText('Notifications'));
      
      expect(screen.getByText('Alert 1')).toBeInTheDocument();
      expect(screen.getByText('Alert 2')).toBeInTheDocument();
    });

    it('should call onMarkAllAsRead when Mark all read is clicked', () => {
      const notifications = [
        createMockNotification({ id: '1' }),
        createMockNotification({ id: '2' }),
      ];
      
      render(<NotificationBell {...mockProps} notifications={notifications} unreadCount={2} />);
      
      fireEvent.click(screen.getByLabelText('Notifications'));
      fireEvent.click(screen.getByText('Mark all read'));
      
      expect(mockProps.onMarkAllAsRead).toHaveBeenCalledTimes(1);
    });

    it('should call onTestConnection when Test is clicked', () => {
      render(<NotificationBell {...mockProps} />);
      
      fireEvent.click(screen.getByLabelText('Notifications'));
      fireEvent.click(screen.getByText('Test'));
      
      expect(mockProps.onTestConnection).toHaveBeenCalledTimes(1);
    });

    it('should not show Test button when onTestConnection is not provided', () => {
      const propsWithoutTest = { ...mockProps, onTestConnection: undefined };
      render(<NotificationBell {...propsWithoutTest} />);
      
      fireEvent.click(screen.getByLabelText('Notifications'));
      
      expect(screen.queryByText('Test')).not.toBeInTheDocument();
    });
  });

  describe('Notification Display', () => {
    it('should display severity badge for high severity', () => {
      const notification = createMockNotification({ severity: 5 });
      render(<NotificationBell {...mockProps} notifications={[notification]} />);
      
      fireEvent.click(screen.getByLabelText('Notifications'));
      
      expect(screen.getByText('Critical')).toBeInTheDocument();
    });

    it('should display camera name when present', () => {
      const notification = createMockNotification({ camera_name: 'Front Door' });
      render(<NotificationBell {...mockProps} notifications={[notification]} />);
      
      fireEvent.click(screen.getByLabelText('Notifications'));
      
      expect(screen.getByText(/Front Door/)).toBeInTheDocument();
    });

    it('should format time correctly', () => {
      const now = new Date();
      const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
      const notification = createMockNotification({ created_at: oneHourAgo.toISOString() });
      
      render(<NotificationBell {...mockProps} notifications={[notification]} />);
      
      fireEvent.click(screen.getByLabelText('Notifications'));
      
      expect(screen.getByText('1h ago')).toBeInTheDocument();
    });

    it('should show just now for recent notifications', () => {
      const notification = createMockNotification({ created_at: new Date().toISOString() });
      render(<NotificationBell {...mockProps} notifications={[notification]} />);
      
      fireEvent.click(screen.getByLabelText('Notifications'));
      
      expect(screen.getByText('Just now')).toBeInTheDocument();
    });
  });

  describe('Click Outside', () => {
    it('should close dropdown when clicking outside', () => {
      render(<NotificationBell {...mockProps} />);
      
      fireEvent.click(screen.getByLabelText('Notifications'));
      expect(screen.getByText('Notifications')).toBeInTheDocument();
      
      fireEvent.mouseDown(document);
      expect(screen.queryByText('No notifications yet')).not.toBeInTheDocument();
    });
  });
});
