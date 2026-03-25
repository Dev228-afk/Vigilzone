# VigilZone Backend - Real-Time Notification Service

## Architecture Overview

The notification service uses **Django Channels** to provide real-time WebSocket-based notifications. When an incident is detected by the AI service, all members of the affected community (tenant) receive instant notifications.

```
┌─────────────┐     Webhook      ┌─────────────┐    Broadcast     ┌─────────────────┐
│  AI Service │ ────────────────► │   Django    │ ────────────────► │   Redis         │
│  (Alerts)   │                 │   Backend    │                  │   Channel Layer  │
└─────────────┘                 └─────────────┘                  └────────┬────────┘
                                                                              │
                        ┌─────────────┐    WebSocket     ┌──────────────────┴───────┐
                        │   Browser   │ ◄───────────────► │   Daphne ASGI Server     │
                        │   (React)   │                   │   (ws://host/ws/notif/)  │
                        └─────────────┘                   └──────────────────────────┘
```

## Components

### 1. Django Backend (`server/`)
- **ASGI Application** (`server/asgi.py`) - Handles both HTTP and WebSocket connections
- **WebSocket Consumer** (`api/consumers.py`) - Manages real-time connections per tenant
- **Notification Service** (`api/notification_service.py`) - Broadcasts incidents to all tenant members
- **API Views** (`api/views.py`) - REST endpoints for notifications

### 2. Redis Channel Layer
- **Purpose**: Pub/sub messaging between Django instances and WebSocket connections
- **Container**: `redis:7-alpine` in docker-compose
- **Why needed**: Allows multiple backend instances to share WebSocket message routing

### 3. Daphne ASGI Server
- **Purpose**: Production-grade ASGI server with WebSocket support
- **Why not Gunicorn**: Gunicorn doesn't support WebSocket natively

### 4. React Frontend (`web/ui/`)
- **WebSocket Hook** (`hooks/useNotifications.ts`) - Manages WebSocket connection lifecycle
- **NotificationBell** (`components/NotificationBell.tsx`) - UI component with badge and dropdown

## How It Works (End-to-End)

### 1. Incident Detection Flow

```
AI Service detects incident
        │
        ▼
POST /api/ai/webhook/receive/ (ai_integration/views.py)
        │
        ▼
Creates Incident in database
        │
        ▼
Calls dispatch_notifications(incident)
        │
        ▼
NotificationService.broadcast_incident()
        │
        ├─► Creates Alert records for audit trail
        │
        └─► Broadcasts to Redis channel group "tenant_notifications_{id}"
                │
                ▼
        Redis pub/sub propagates to all connected clients
                │
                ▼
        WebSocket consumer sends JSON to each connected browser
                │
                ▼
        React hook receives message, updates state
                │
                ▼
        NotificationBell displays notification + badge
```

### 2. WebSocket Connection Flow

```
Browser loads app
        │
        ▼
useNotifications hook connects:
ws://host/ws/notifications/?token={jwt}&tenant_id={id}
        │
        ▼
NotificationConsumer.authenticate_user() - Validates JWT
        │
        ▼
NotificationConsumer.verify_tenant_membership() - Checks user is member
        │
        ▼
Joins channel group: tenant_notifications_{tenant_id}
        │
        ▼
Connection established - green dot in UI
        │
        ▼
Receives real-time notifications via group_send
```

## API Endpoints

### REST Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/notifications/` | GET | List user's notifications |
| `/api/notifications/mark-read/` | POST | Mark notifications as read |
| `/api/notifications/unread-count/` | GET | Get unread notification count |
| `/api/notifications/broadcast/` | POST | Send broadcast to all tenant members |
| `/api/notifications/test-websocket/` | POST | Send test notification via WebSocket |

### WebSocket Endpoint

| URL | Query Params | Description |
|-----|--------------|-------------|
| `ws://host/ws/notifications/` | `token`, `tenant_id` | Real-time notification channel |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `redis` | Redis server hostname |
| `REDIS_PORT` | `6379` | Redis server port |
| `DJANGO_DEBUG` | `1` | Debug mode |
| `SECRET_KEY` | `django-insecure-...` | Django secret key |

### Docker Compose Services

```yaml
services:
  redis:           # Channel layer for WebSocket pub/sub
  backend:         # Django + Daphne ASGI server
  nginx:           # Reverse proxy + static files
  ai:              # AI detection service
  mediamtx:        # RTSP server for camera streams
  webcam_publisher: # Webcam capture
```

## Commands

### Development

```bash
# Start all services
docker compose up -d

# Start only backend with hot reload
docker compose up backend

# View backend logs
docker compose logs -f backend

# View Redis logs
docker compose logs -f redis

# Restart backend after code changes
docker compose restart backend
```

### Testing Notifications

```bash
# 1. Get JWT token (from browser devtools or login endpoint)
# 2. Open browser console, find tenant_id
# 3. Click "Test" button in notification bell dropdown
# 4. Check logs:
docker compose logs backend | grep "broadcast"
```

Run this command after running redis
```
export REDIS_HOST=localhost
export REDIS_PORT=6379
python -m daphne -b 0.0.0.0 -p 8000 server.asgi:application 
```

### Rebuilding

```bash
# Full rebuild (after requirements.txt changes)
docker compose down
docker compose up -d --build

# Rebuild only backend
docker compose build backend
docker compose up -d backend
```

### Troubleshooting

```bash
# Check WebSocket connectivity
docker compose logs backend | grep -i websocket

# Check Redis connectivity
docker compose logs backend | grep -i redis

# Check if Redis is running
docker compose ps redis

# Test Redis connection from backend
docker compose exec backend python -c "from channels.layers import get_channel_layer; print(get_channel_layer())"
```

## File Structure

```
services/backend/
├── Dockerfile                 # Container image definition
├── requirements.txt           # Python dependencies
├── manage.py                  # Django management script
├── api/
│   ├── consumers.py          # WebSocket consumer (NotificationConsumer)
│   ├── notification_service.py # Broadcast service
│   ├── routing.py            # WebSocket URL routing
│   ├── views.py              # REST API views
│   └── models.py             # Alert, Incident models
└── server/
    ├── asgi.py               # ASGI application config
    ├── settings.py            # Django settings (includes CHANNEL_LAYERS)
    └── urls.py                # HTTP URL routing
```

## Dependencies

### Python Packages (requirements.txt)

```
Django==5.2.7
djangorestframework==3.16.1
djangorestframework_simplejwt==5.5.1
django-cors-headers==4.9.0

# Real-time notifications
channels==4.2.0
channels-redis==4.2.1
daphne==4.1.2
```

### Infrastructure

- **Redis 7+** - Required for channels-redis channel layer
- **Daphne** - ASGI server with WebSocket support

## Known Issues

1. **Redis must be running** - WebSocket won't work without Redis
2. **JWT token required** - WebSocket connections require valid JWT authentication
3. **Tenant membership verified** - Users can only subscribe to their own tenant's notifications

## Security Considerations

1. JWT tokens expire - WebSocket will disconnect when token expires
2. Tenant isolation - Users can only receive notifications for their community
3. CORS configured - WebSocket origins are validated in production
