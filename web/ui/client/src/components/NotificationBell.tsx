import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bell, BellRing, CheckCheck, CircleAlert, Dot, Info, Radar, ShieldAlert, Siren } from 'lucide-react';
import { Notification } from '../hooks/useNotifications';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';

interface NotificationBellProps {
  notifications: Notification[];
  unreadCount: number;
  onMarkAsRead: (ids: number[]) => Promise<void>;
  onMarkAllAsRead: () => Promise<void>;
  isConnected: boolean;
  isSubscribed?: boolean;
  transportHealthy?: boolean;
  tenantId?: number | null;
  onTestConnection?: () => Promise<void>;
  onNavigate?: (path: string) => void;
}

const severityLabelByLevel: Record<string, string> = {
  critical: 'Critical',
  severe: 'Severe',
  moderate: 'Moderate',
  low: 'Low',
  info: 'Info',
};

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Just now';
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getSeverityLevel(notification: Notification) {
  return String(
    notification.data?.severity_level ||
      notification.severity_level ||
      (notification.severity && notification.severity >= 5
        ? 'critical'
        : notification.severity && notification.severity >= 4
          ? 'severe'
          : notification.severity && notification.severity >= 3
            ? 'moderate'
            : notification.severity && notification.severity >= 2
              ? 'low'
              : 'info')
  );
}

function getIncidentId(notification: Notification): number | undefined {
  if (typeof notification.incident_id === 'number') return notification.incident_id;
  const nested = notification.data?.incident_id;
  return typeof nested === 'number' ? nested : undefined;
}

function getSeverityIcon(level: string) {
  if (level === 'critical') return <Siren className="h-4 w-4" />;
  if (level === 'severe') return <ShieldAlert className="h-4 w-4" />;
  if (level === 'moderate') return <CircleAlert className="h-4 w-4" />;
  if (level === 'low') return <Radar className="h-4 w-4" />;
  return <Info className="h-4 w-4" />;
}

function severityBadgeClass(level: string) {
  switch (level) {
    case 'critical':
      return 'border-red-500/30 bg-red-500/15 text-red-600 dark:text-red-300';
    case 'severe':
      return 'border-orange-500/30 bg-orange-500/15 text-orange-600 dark:text-orange-300';
    case 'moderate':
      return 'border-amber-500/30 bg-amber-500/15 text-amber-600 dark:text-amber-300';
    case 'low':
      return 'border-sky-500/30 bg-sky-500/15 text-sky-600 dark:text-sky-300';
    default:
      return 'border-border bg-secondary text-secondary-foreground';
  }
}

export const NotificationBell: React.FC<NotificationBellProps> = ({
  notifications,
  unreadCount,
  onMarkAsRead,
  onMarkAllAsRead,
  isConnected,
  isSubscribed = false,
  transportHealthy = isConnected,
  tenantId,
  onTestConnection,
  onNavigate,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  const visibleNotifications = useMemo(() => notifications, [notifications]);
  const connectionLabel = transportHealthy
    ? isSubscribed
      ? 'Realtime live'
      : isConnected
        ? 'Connected (no sub)'
        : 'Redis Reachable'
    : isConnected
      ? 'Socket connected'
      : 'Offline';

  const handleNotificationClick = async (notification: Notification) => {
    setIsOpen(false);

    if (notification.alert_id && !notification.is_read) {
      await onMarkAsRead([notification.alert_id]);
    }

    const incidentId = getIncidentId(notification);
    if (incidentId) {
      const path = `/incidents/${incidentId}`;
      if (onNavigate) {
        onNavigate(path);
      } else {
        window.history.pushState({}, '', path);
        window.dispatchEvent(new PopStateEvent('popstate'));
      }
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="relative rounded-full border border-transparent hover:border-border hover:bg-accent"
        aria-label="Notifications"
        onClick={() => setIsOpen((prev) => !prev)}
      >
        {unreadCount > 0 ? <BellRing className="h-5 w-5" /> : <Bell className="h-5 w-5" />}
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground shadow-sm">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
        <span
          className={cn(
            'absolute bottom-1 right-1 h-2.5 w-2.5 rounded-full border border-background',
            isSubscribed ? 'bg-emerald-500' 
              : isConnected ? 'bg-amber-500' 
              : transportHealthy ? 'bg-sky-500' 
              : 'bg-muted-foreground/60'
          )}
          title={connectionLabel}
        />
      </Button>

      {isOpen && (
        <div className="absolute right-0 z-50 mt-3 w-[24rem] max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl border border-border bg-popover text-popover-foreground shadow-2xl">
          <div className="border-b border-border/80 bg-gradient-to-b from-background to-popover px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold">Incident notifications</h3>
                  <Badge variant="outline" className="gap-1 border-border bg-background/60 text-[11px] text-muted-foreground">
                    <Dot className="h-3 w-3" />
                    {connectionLabel}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Community {tenantId ? `#${tenantId}` : '(none selected)'}
                </p>
              </div>
              <div className="flex items-center gap-1">
                {unreadCount > 0 && (
                  <Button variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={onMarkAllAsRead}>
                    <CheckCheck className="mr-1 h-3.5 w-3.5" />
                    Mark all
                  </Button>
                )}
                {onTestConnection && (
                  <Button variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={onTestConnection}>
                    Test
                  </Button>
                )}
              </div>
            </div>
          </div>

          {visibleNotifications.length === 0 ? (
            <div className="px-5 py-10 text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full border border-dashed border-border bg-background/70">
                <Bell className="h-5 w-5 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium">No incident notifications yet</p>
              <p className="mt-1 text-xs text-muted-foreground">
                When the AI service reports an incident for this community, it will appear here instantly.
              </p>
            </div>
          ) : (
            <>
              <ScrollArea type="always" className="h-[28rem] max-h-[70vh]">
              <ul className="divide-y divide-border/70">
                {visibleNotifications.map((notification) => {
                  const level = getSeverityLevel(notification);
                  return (
                    <li
                      key={notification.id}
                      className={cn(
                        'cursor-pointer px-4 py-3 transition-colors hover:bg-accent/70',
                        !notification.is_read && 'bg-primary/5'
                      )}
                      onClick={() => void handleNotificationClick(notification)}
                    >
                      <div className="flex items-start gap-3">
                        <div className={cn('mt-0.5 rounded-full border p-2', severityBadgeClass(level))}>
                          {getSeverityIcon(level)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center justify-between gap-2">
                            <p className="truncate text-sm font-medium">{notification.title}</p>
                            <Badge variant="outline" className={cn('shrink-0 text-[10px] uppercase tracking-wide', severityBadgeClass(level))}>
                              {severityLabelByLevel[level] ?? level}
                            </Badge>
                          </div>
                          <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{notification.message}</p>
                          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                            {notification.camera_name && <span>Camera: {notification.camera_name}</span>}
                            <span>{formatTime(notification.created_at)}</span>
                            {!notification.is_read && <span className="font-medium text-primary">Unread</span>}
                          </div>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
              </ScrollArea>
              <div className="border-t border-border/70 bg-background/50 px-4 py-3">
                <Button
                  type="button"
                  variant="ghost"
                  className="w-full justify-center text-sm"
                  onClick={() => {
                    setIsOpen(false);
                    if (onNavigate) {
                      onNavigate('/incidents');
                    } else {
                      window.history.pushState({}, '', '/incidents');
                      window.dispatchEvent(new PopStateEvent('popstate'));
                    }
                  }}
                >
                  View all incidents
                </Button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default NotificationBell;
