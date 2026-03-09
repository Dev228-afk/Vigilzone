from typing import Optional
from django.http import HttpRequest
from .models import Tenant

TENANT_HEADER = "HTTP_X_TENANT_ID"  # Django transforms X-Tenant-ID -> HTTP_X_TENANT_ID

def get_tenant_from_request(request: HttpRequest) -> Optional[Tenant]:
    tenant_id = request.META.get(TENANT_HEADER)
    if not tenant_id:
        return None
    try:
        return Tenant.objects.get(pk=tenant_id)
    except Tenant.DoesNotExist:
        return None