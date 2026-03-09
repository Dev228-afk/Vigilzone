import { http, HttpResponse, delay } from 'msw';
import { setupServer } from 'msw/node';

export const mockUser = {
  id: 1,
  username: 'testuser',
  email: 'test@example.com',
  is_superuser: false,
  is_staff: false,
};

export const mockTenant = {
  id: 1,
  name: 'Test Community',
  role: 'owner',
};

export const mockTokens = {
  access: 'mock-access-token',
  refresh: 'mock-refresh-token',
};

export const mockTenants = [
  { id: 1, name: 'Test Community', role: 'owner' },
  { id: 2, name: 'Second Community', role: 'member' },
];

// Helper to normalize URL for both relative and absolute paths
const normalizeUrl = (url: string | URL): string => {
  const urlStr = url instanceof URL ? url.href : url;
  // Remove host and protocol for relative URLs
  return urlStr.replace(/^https?:\/\/[^/]+/, '');
};

export const handlers = [
  // POST /api/auth/token/ - Login
  http.post('*/api/auth/token/', async ({ request }) => {
    await delay(100);
    const body = await request.json() as { username?: string; password?: string };
    
    if (body.username === 'testuser' && body.password === 'password123') {
      return HttpResponse.json({
        ...mockTokens,
        user: { username: 'testuser' },
      });
    }
    
    return HttpResponse.json(
      { detail: 'Invalid credentials' },
      { status: 401 }
    );
  }),

  // POST /api/auth/register/ - Registration
  http.post('*/api/auth/register/', async ({ request }) => {
    await delay(100);
    const body = await request.json() as { username?: string; email?: string; password?: string };
    
    if (body.username && body.email && body.password) {
      return HttpResponse.json(
        { message: 'User registered successfully' },
        { status: 201 }
      );
    }
    
    return HttpResponse.json(
      { username: ['This field is required.'] },
      { status: 400 }
    );
  }),

  // POST /api/auth/refresh/ - Token refresh
  http.post('*/api/auth/refresh/', async ({ request }) => {
    await delay(100);
    const body = await request.json() as { refresh?: string };
    
    if (body.refresh === 'mock-refresh-token') {
      return HttpResponse.json({ access: 'new-mock-access-token' });
    }
    
    return HttpResponse.json(
      { detail: 'Invalid token' },
      { status: 401 }
    );
  }),

  // GET /api/auth/context/ - Auth context
  http.get('*/api/auth/context/', async ({ request }) => {
    await delay(100);
    const authHeader = request.headers.get('Authorization');
    
    if (authHeader?.startsWith('Bearer ')) {
      return HttpResponse.json({
        user: mockUser,
        tenant: mockTenant,
        role: 'owner',
      });
    }
    
    return HttpResponse.json(
      { detail: 'Authentication credentials were not provided.' },
      { status: 401 }
    );
  }),

  // GET /api/tenants/mine/ - Get user's tenants
  http.get('*/api/tenants/mine/', async ({ request }) => {
    await delay(100);
    const authHeader = request.headers.get('Authorization');
    
    if (authHeader?.startsWith('Bearer ')) {
      return HttpResponse.json(mockTenants);
    }
    
    return HttpResponse.json(
      { detail: 'Authentication credentials were not provided.' },
      { status: 401 }
    );
  }),

  // GET /api/tenants/ - Get all tenants (for user with membership)
  http.get('*/api/tenants/', async ({ request }) => {
    await delay(100);
    const authHeader = request.headers.get('Authorization');
    
    if (authHeader?.startsWith('Bearer ')) {
      return HttpResponse.json(mockTenants);
    }
    
    return HttpResponse.json(
      { detail: 'Authentication credentials were not provided.' },
      { status: 401 }
    );
  }),

  // POST /api/tenants/ - Create new tenant
  http.post('*/api/tenants/', async ({ request }) => {
    await delay(100);
    const authHeader = request.headers.get('Authorization');
    const body = await request.json() as { name?: string };
    
    if (authHeader?.startsWith('Bearer ') && body.name) {
      return HttpResponse.json(
        { id: 3, name: body.name, plan: 'free', role: 'owner' },
        { status: 201 }
      );
    }
    
    return HttpResponse.json(
      { detail: 'Authentication credentials were not provided.' },
      { status: 401 }
    );
  }),

  // GET /api/profile/ - Get user profile
  http.get('*/api/profile/', async ({ request }) => {
    await delay(100);
    const authHeader = request.headers.get('Authorization');
    
    if (authHeader?.startsWith('Bearer ')) {
      return HttpResponse.json({
        id: 1,
        user: 'testuser',
        bio: '',
      });
    }
    
    return HttpResponse.json(
      { detail: 'Authentication credentials were not provided.' },
      { status: 401 }
    );
  }),

  // GET /api/cameras/ - Get cameras
  http.get('*/api/cameras/', async ({ request }) => {
    await delay(100);
    const tenantHeader = request.headers.get('X-Tenant-ID');
    const authHeader = request.headers.get('Authorization');
    
    if (authHeader?.startsWith('Bearer ') && tenantHeader) {
      return HttpResponse.json([
        { id: 1, name: 'Front Door', status: 'active', site: 'Home' },
        { id: 2, name: 'Backyard', status: 'active', site: 'Home' },
      ]);
    }
    
    return HttpResponse.json(
      { detail: 'Missing X-Tenant-ID header.' },
      { status: 403 }
    );
  }),

  // GET /api/incidents/ - Get incidents
  http.get('*/api/incidents/', async ({ request }) => {
    await delay(100);
    const tenantHeader = request.headers.get('X-Tenant-ID');
    const authHeader = request.headers.get('Authorization');
    
    if (authHeader?.startsWith('Bearer ') && tenantHeader) {
      return HttpResponse.json([
        { 
          id: 1, 
          type: 'intrusion', 
          status: 'open', 
          severity: 3,
          camera: 1,
          started_at: '2024-01-15T10:00:00Z',
        },
      ]);
    }
    
    return HttpResponse.json(
      { detail: 'Missing X-Tenant-ID header.' },
      { status: 403 }
    );
  }),

  // GET /api/alerts/ - Get alerts
  http.get('*/api/alerts/', async ({ request }) => {
    await delay(100);
    const tenantHeader = request.headers.get('X-Tenant-ID');
    const authHeader = request.headers.get('Authorization');
    
    if (authHeader?.startsWith('Bearer ') && tenantHeader) {
      return HttpResponse.json([
        { id: 1, channel: 'email', delivered_at: null },
      ]);
    }
    
    return HttpResponse.json(
      { detail: 'Missing X-Tenant-ID header.' },
      { status: 403 }
    );
  }),

  // GET /api/invitations/pending/ - Get pending invitations
  http.get('*/api/invitations/pending/', async ({ request }) => {
    await delay(100);
    const authHeader = request.headers.get('Authorization');
    
    if (authHeader?.startsWith('Bearer ')) {
      return HttpResponse.json([
        { 
          id: 1, 
          tenant: { id: 1, name: 'Test Community' },
          email: 'test@example.com',
          role: 'member',
          invited_by: 'admin',
          expires_at: '2024-12-31T23:59:59Z',
        },
      ]);
    }
    
    return HttpResponse.json(
      { detail: 'Authentication credentials were not provided.' },
      { status: 401 }
    );
  }),
];
