import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { NotificationBell } from '../NotificationBell';
import type { Notification } from '../../hooks/useNotifications';

const createNotification = (overrides: Partial<Notification> = {}): Notification => ({
  id: `alert-${Math.random().toString(36).slice(2, 8)}`,
  type: 'notification',
  notification_type: 'incident',
  title: 'Incident detected',
  message: 'Test message',
  created_at: new Date().toISOString(),
  severity: 4,
  severity_level: 'severe',
  camera_name: 'Front Door',
  incident_id: 10,
  alert_id: 42,
  is_read: false,
  ...overrides,
});

describe('NotificationBell', () => {
  const baseProps = {
    notifications: [] as Notification[],
    unreadCount: 0,
    isConnected: true,
    onMarkAsRead: vi.fn().mockResolvedValue(undefined),
    onMarkAllAsRead: vi.fn().mockResolvedValue(undefined),
    onTestConnection: vi.fn().mockResolvedValue(undefined),
    onNavigate: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the notification button and live transport indicator', () => {
    render(<NotificationBell {...baseProps} />);

    expect(screen.getByLabelText('Notifications')).toBeInTheDocument();
    expect(screen.getByTitle('Realtime live')).toBeInTheDocument();
  });

  it('shows unread badge and caps it at 9+', () => {
    const { rerender } = render(<NotificationBell {...baseProps} unreadCount={5} />);
    expect(screen.getByText('5')).toBeInTheDocument();

    rerender(<NotificationBell {...baseProps} unreadCount={15} />);
    expect(screen.getByText('9+')).toBeInTheDocument();
  });

  it('shows the empty state when there are no notifications', () => {
    render(<NotificationBell {...baseProps} notifications={[]} />);

    fireEvent.click(screen.getByLabelText('Notifications'));

    expect(screen.getByText('No incident notifications yet')).toBeInTheDocument();
  });

  it('renders every notification instead of truncating at 20', () => {
    const notifications = Array.from({ length: 25 }, (_, index) =>
      createNotification({
        id: `alert-${index}`,
        alert_id: index + 1,
        incident_id: index + 100,
        title: `Alert ${index + 1}`,
      })
    );

    render(
      <NotificationBell
        {...baseProps}
        notifications={notifications}
        unreadCount={notifications.length}
      />
    );

    fireEvent.click(screen.getByLabelText('Notifications'));

    expect(screen.getByText('Alert 1')).toBeInTheDocument();
    expect(screen.getByText('Alert 25')).toBeInTheDocument();
    expect(screen.getByText('View all incidents')).toBeInTheDocument();
  });

  it('calls mark-all and test actions from the dropdown header', async () => {
    render(
      <NotificationBell
        {...baseProps}
        notifications={[createNotification()]}
        unreadCount={1}
      />
    );

    fireEvent.click(screen.getByLabelText('Notifications'));
    fireEvent.click(screen.getByText('Mark all'));
    fireEvent.click(screen.getByText('Test'));

    await waitFor(() => {
      expect(baseProps.onMarkAllAsRead).toHaveBeenCalledTimes(1);
      expect(baseProps.onTestConnection).toHaveBeenCalledTimes(1);
    });
  });

  it('marks an unread notification as read and navigates to the incident', async () => {
    render(
      <NotificationBell
        {...baseProps}
        notifications={[createNotification({ alert_id: 99, incident_id: 321 })]}
        unreadCount={1}
      />
    );

    fireEvent.click(screen.getByLabelText('Notifications'));
    fireEvent.click(screen.getByText('Incident detected'));

    await waitFor(() => {
      expect(baseProps.onMarkAsRead).toHaveBeenCalledWith([99]);
      expect(baseProps.onNavigate).toHaveBeenCalledWith('/incidents/321');
    });
  });

  it('opens the incidents page from the footer action', () => {
    render(
      <NotificationBell
        {...baseProps}
        notifications={[createNotification()]}
        unreadCount={1}
      />
    );

    fireEvent.click(screen.getByLabelText('Notifications'));
    fireEvent.click(screen.getByText('View all incidents'));

    expect(baseProps.onNavigate).toHaveBeenCalledWith('/incidents');
  });
});
