import { describe, it, expect, beforeAll, afterEach, afterAll, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { handlers, mockTokens, mockUser, mockTenants, mockTenant } from '../mocks/handlers';

// Create MSW server for Node.js environment
export const server = setupServer(...handlers);

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
});

afterEach(() => {
  server.resetHandlers();
  // Clear localStorage between tests
  localStorage.clear();
});

afterAll(() => {
  server.close();
});

describe('Authentication Integration Tests', () => {
  describe('POST /api/auth/token/', () => {
    it('should return tokens on successful login', async () => {
      const response = await fetch('/api/auth/token/', {
        method: 'POST',
        body: JSON.stringify({
          username: 'testuser',
          password: 'password123',
        }),
        headers: {
          'Content-Type': 'application/json',
        },
      });

      expect(response.ok).toBe(true);
      const data = await response.json();
      expect(data.access).toBeDefined();
      expect(data.refresh).toBeDefined();
      expect(data.user).toBeDefined();
    });

    it('should return 401 on invalid credentials', async () => {
      const response = await fetch('/api/auth/token/', {
        method: 'POST',
        body: JSON.stringify({
          username: 'invaliduser',
          password: 'wrongpassword',
        }),
        headers: {
          'Content-Type': 'application/json',
        },
      });

      expect(response.status).toBe(401);
      const data = await response.json();
      expect(data.detail).toBe('Invalid credentials');
    });
  });

  describe('POST /api/auth/register/', () => {
    it('should register a new user successfully', async () => {
      const response = await fetch('/api/auth/register/', {
        method: 'POST',
        body: JSON.stringify({
          username: 'newuser',
          email: 'newuser@example.com',
          password: 'securepassword123',
        }),
        headers: {
          'Content-Type': 'application/json',
        },
      });

      expect(response.status).toBe(201);
      const data = await response.json();
      expect(data.message).toBe('User registered successfully');
    });

    it('should return 400 on invalid registration data', async () => {
      const response = await fetch('/api/auth/register/', {
        method: 'POST',
        body: JSON.stringify({
          username: '',  // Invalid: empty username
        }),
        headers: {
          'Content-Type': 'application/json',
        },
      });

      expect(response.status).toBe(400);
    });
  });

  describe('POST /api/auth/refresh/', () => {
    it('should refresh access token with valid refresh token', async () => {
      const response = await fetch('/api/auth/refresh/', {
        method: 'POST',
        body: JSON.stringify({
          refresh: 'mock-refresh-token',
        }),
        headers: {
          'Content-Type': 'application/json',
        },
      });

      expect(response.ok).toBe(true);
      const data = await response.json();
      expect(data.access).toBeDefined();
    });

    it('should return 401 with invalid refresh token', async () => {
      const response = await fetch('/api/auth/refresh/', {
        method: 'POST',
        body: JSON.stringify({
          refresh: 'invalid-token',
        }),
        headers: {
          'Content-Type': 'application/json',
        },
      });

      expect(response.status).toBe(401);
    });
  });

  describe('GET /api/auth/context/', () => {
    it('should return user context with valid token', async () => {
      const response = await fetch('/api/auth/context/', {
        headers: {
          'Authorization': `Bearer ${mockTokens.access}`,
        },
      });

      expect(response.ok).toBe(true);
      const data = await response.json();
      expect(data.user).toEqual(mockUser);
      expect(data.tenant).toEqual(mockTenant);
    });

    it('should return 401 without token', async () => {
      const response = await fetch('/api/auth/context/');

      expect(response.status).toBe(401);
    });
  });
});

describe('Tenant Integration Tests', () => {
  describe('GET /api/tenants/mine/', () => {
    it('should return user tenants with valid token', async () => {
      const response = await fetch('/api/tenants/mine/', {
        headers: {
          'Authorization': `Bearer ${mockTokens.access}`,
        },
      });

      expect(response.ok).toBe(true);
      const data = await response.json();
      expect(Array.isArray(data)).toBe(true);
      expect(data.length).toBe(2);
    });

    it('should return 401 without token', async () => {
      const response = await fetch('/api/tenants/mine/');

      expect(response.status).toBe(401);
    });
  });

  describe('POST /api/tenants/', () => {
    it('should create new tenant with valid token', async () => {
      const response = await fetch('/api/tenants/', {
        method: 'POST',
        body: JSON.stringify({
          name: 'New Test Tenant',
        }),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${mockTokens.access}`,
        },
      });

      expect(response.status).toBe(201);
      const data = await response.json();
      expect(data.name).toBe('New Test Tenant');
      expect(data.role).toBe('owner');
    });
  });
});

describe('Protected Resources Integration Tests', () => {
  const authHeaders = {
    'Authorization': `Bearer ${mockTokens.access}`,
    'X-Tenant-ID': '1',
  };

  describe('GET /api/cameras/', () => {
    it('should return cameras with valid tenant and token', async () => {
      const response = await fetch('/api/cameras/', {
        headers: authHeaders,
      });

      expect(response.ok).toBe(true);
      const data = await response.json();
      expect(Array.isArray(data)).toBe(true);
      expect(data.length).toBe(2);
      expect(data[0].name).toBe('Front Door');
    });

    it('should return 403 without tenant header', async () => {
      const response = await fetch('/api/cameras/', {
        headers: {
          'Authorization': `Bearer ${mockTokens.access}`,
        },
      });

      expect(response.status).toBe(403);
    });
  });

  describe('GET /api/incidents/', () => {
    it('should return incidents with valid tenant and token', async () => {
      const response = await fetch('/api/incidents/', {
        headers: authHeaders,
      });

      expect(response.ok).toBe(true);
      const data = await response.json();
      expect(Array.isArray(data)).toBe(true);
      expect(data[0].type).toBe('intrusion');
    });
  });

  describe('GET /api/alerts/', () => {
    it('should return alerts with valid tenant and token', async () => {
      const response = await fetch('/api/alerts/', {
        headers: authHeaders,
      });

      expect(response.ok).toBe(true);
      const data = await response.json();
      expect(Array.isArray(data)).toBe(true);
    });
  });

  describe('GET /api/invitations/pending/', () => {
    it('should return pending invitations with valid token', async () => {
      const response = await fetch('/api/invitations/pending/', {
        headers: {
          'Authorization': `Bearer ${mockTokens.access}`,
        },
      });

      expect(response.ok).toBe(true);
      const data = await response.json();
      expect(Array.isArray(data)).toBe(true);
      expect(data[0].tenant.name).toBe('Test Community');
    });
  });
});
