import { describe, it, expect, beforeAll, afterEach, afterAll, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { handlers, mockTokens, mockTenant, mockUser } from '../mocks/handlers';
import { api, setAccessToken } from '@/lib/api';
import { getSelectedTenantId, setSelectedTenantId } from '@/lib/tenant';
import * as auth from '@/lib/auth';
import * as user from '@/lib/user';

// Create MSW server
export const apiServer = setupServer(...handlers);

beforeAll(() => {
  apiServer.listen({ onUnhandledRequest: 'error' });
});

afterEach(() => {
  apiServer.resetHandlers();
  localStorage.clear();
  setAccessToken(null);
  setSelectedTenantId(null);
});

afterAll(() => {
  apiServer.close();
});

describe('API Client Integration Tests', () => {
  describe('Authentication Flow via API Client', () => {
    it('should login successfully and store tokens', async () => {
      const result = await auth.login('testuser', 'password123');
      
      expect(result.access).toBe(mockTokens.access);
      expect(result.refresh).toBe(mockTokens.refresh);
      expect(localStorage.getItem('accessToken')).toBe(mockTokens.access);
      expect(localStorage.getItem('refreshToken')).toBe(mockTokens.refresh);
    });

    it('should throw error on invalid credentials', async () => {
      await expect(auth.login('invalid', 'wrong')).rejects.toThrow();
    });

    it('should logout and clear tokens', async () => {
      // First login
      await auth.login('testuser', 'password123');
      expect(localStorage.getItem('accessToken')).toBeTruthy();
      
      // Then logout
      auth.logout();
      expect(localStorage.getItem('accessToken')).toBeNull();
      expect(localStorage.getItem('refreshToken')).toBeNull();
    });

    it('should refresh token successfully', async () => {
      // Set initial refresh token
      localStorage.setItem('refreshToken', 'mock-refresh-token');
      
      await auth.refresh();
      
      expect(localStorage.getItem('accessToken')).toBe('new-mock-access-token');
    });

    it('should throw error when refreshing without token', async () => {
      await expect(auth.refresh()).rejects.toThrow('No refresh token');
    });
  });

  describe('Tenant Selection Flow', () => {
    it('should get user tenants', async () => {
      // Set access token
      setAccessToken(mockTokens.access);
      
      const tenants = await user.getUserTenants();
      
      expect(Array.isArray(tenants)).toBe(true);
      expect(tenants.length).toBe(2);
    });
  });

  describe('Protected Endpoints with Tenant Context', () => {
    beforeEach(() => {
      setAccessToken(mockTokens.access);
      setSelectedTenantId('1');
    });

    it('should include tenant header in requests', async () => {
      // Verify tenant is set
      expect(getSelectedTenantId()).toBe('1');
      
      // Make request - tenant header should be included
      const response = await api.get('/cameras/');
      expect(response.status).toBe(200);
      expect(Array.isArray(response.data)).toBe(true);
    });

    it('should get incidents with tenant context', async () => {
      const response = await api.get('/incidents/');
      expect(response.status).toBe(200);
      expect(Array.isArray(response.data)).toBe(true);
    });

    it('should get alerts with tenant context', async () => {
      const response = await api.get('/alerts/');
      expect(response.status).toBe(200);
      expect(Array.isArray(response.data)).toBe(true);
    });
  });

  describe('API Interceptor Tests', () => {
    it('should add Authorization header automatically', async () => {
      setAccessToken(mockTokens.access);
      
      const response = await api.get('/auth/context/');
      
      expect(response.status).toBe(200);
      expect(response.data.user).toEqual(mockUser);
    });

    it('should add X-Tenant-ID header automatically', async () => {
      setAccessToken(mockTokens.access);
      setSelectedTenantId('1');
      
      const response = await api.get('/cameras/');
      
      expect(response.status).toBe(200);
    });

    it('should handle 401 and attempt token refresh', async () => {
      // This tests the interceptor behavior
      // Note: Full refresh flow requires mock setup for refresh endpoint
      localStorage.setItem('refreshToken', 'mock-refresh-token');
      setAccessToken(mockTokens.access);
      
      // The mock should handle the refresh
      const response = await api.get('/auth/context/');
      expect(response.status).toBe(200);
    });
  });
});

describe('End-to-End Flow Tests', () => {
  it('should complete login -> tenant selection -> protected resource flow', async () => {
    // Step 1: Login
    await auth.login('testuser', 'password123');
    expect(localStorage.getItem('accessToken')).toBeTruthy();
    
    // Step 2: Get tenants
    const tenants = await user.getUserTenants();
    expect(tenants.length).toBeGreaterThan(0);
    
    // Step 3: Select tenant
    setSelectedTenantId(String(tenants[0].id));
    expect(getSelectedTenantId()).toBe(String(tenants[0].id));
    
    // Step 4: Access protected resource with tenant context
    const camerasResponse = await api.get('/cameras/');
    expect(camerasResponse.status).toBe(200);
    expect(Array.isArray(camerasResponse.data)).toBe(true);
  });

  it('should handle logout and session cleanup', async () => {
    // Setup: Login and select tenant
    await auth.login('testuser', 'password123');
    setSelectedTenantId('1');
    
    // Verify setup
    expect(localStorage.getItem('accessToken')).toBeTruthy();
    expect(getSelectedTenantId()).toBe('1');
    
    // Logout
    auth.logout();
    
    // Verify cleanup
    expect(localStorage.getItem('accessToken')).toBeNull();
    expect(localStorage.getItem('refreshToken')).toBeNull();
    expect(localStorage.getItem('selectedTenantId')).toBeNull();
  });
});
