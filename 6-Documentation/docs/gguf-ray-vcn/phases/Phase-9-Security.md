# Phase 9: Security Hardening

**Phase:** 9  
**Name:** Security Hardening  
**Duration:** 5 days  
**Dependencies:** Phase 8 (Monitoring & Observability)  
**Status:** TODO  
**Owner:** Security Team

---

## Overview

This phase implements comprehensive security measures for the GGUF-Ray-VCN-LUPINE deployment, including TLS certificates, authentication, authorization, network policies, and secrets management.

### Goals
1. Deploy cert-manager for automatic TLS certificate provisioning
2. Configure TLS for all external endpoints
3. Implement JWT-based authentication for Hermes API
4. Implement OAuth2 integration for user authentication
5. Configure Ray dashboard authentication
6. Deploy Kubernetes Network Policies
7. Configure RBAC for service accounts
8. Encrypt secrets at rest
9. Enable audit logging

### Key Components
- cert-manager (TLS certificates)
- JWT/OAuth2 authentication
- Network Policies (Calico)
- RBAC configuration
- Kubernetes Secrets
- Pod Security Policies

---

## Prerequisites

Before starting Phase 9, ensure:
- [ ] Phase 1-8 are complete
- [ ] All services are accessible via HTTPS (from Phase 6)
- [ ] Monitoring is in place (Phase 8)
- [ ] Helm is installed
- [ ] DNS records are configured for all domains

---

## Microsteps

### Day 1: TLS Certificate Management

#### Step 9.1.1: Install cert-manager
```bash
# Add Helm repo
helm repo add jetstack https://charts.jetstack.io
helm repo update

# Install cert-manager
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.13.0 \
  --set installCRDs=true
```

**Verification:**
```bash
kubectl get pods -n cert-manager
# Expected: cert-manager, cert-manager-cainjector, cert-manager-webhook pods

kubectl get crd | grep cert-manager
# Expected: certificaterequests.cert-manager.io, certificates.cert-manager.io, clusterissuers.cert-manager.io, issuers.cert-manager.io
```

#### Step 9.1.2: Configure Let's Encrypt ClusterIssuer
```yaml
# File: kubernetes/security/letsencrypt-clusterissuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@yourdomain.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: traefik
```

**Verification:**
```bash
kubectl get clusterissuer letsencrypt-prod
# Expected: Should show READY status

kubectl describe clusterissuer letsencrypt-prod
# Expected: Should show ACME account registered
```

#### Step 9.1.3: Update Existing Certificates to Use ClusterIssuer
```yaml
# File: kubernetes/ray/certificate.yaml (updated)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: ray-dashboard-tls
  namespace: ray-system
spec:
  secretName: ray-dashboard-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - ray.yourdomain.com
---
# File: kubernetes/hermes/certificate.yaml (updated)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: hermes-tls
  namespace: hermes
spec:
  secretName: hermes-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - api.yourdomain.com
  - hermes.yourdomain.com
---
# File: kubernetes/monitoring/certificate.yaml (updated)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: grafana-tls
  namespace: monitoring
spec:
  secretName: grafana-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - grafana.yourdomain.com
```

**Verification:**
```bash
kubectl get certificate -A
# Expected: All certificates should show READY status

kubectl describe certificate -n ray-system ray-dashboard-tls
# Expected: Should show certificate issued successfully
```

### Day 2: Authentication & Authorization

#### Step 9.2.1: Implement JWT Authentication Middleware
```python
# File: code/hermes/auth.py
"""
Authentication and Authorization Middleware

Implements JWT-based authentication for Hermes API.
"""

import jwt
import time
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from hermes.config import settings

# Security scheme
security = HTTPBearer()


class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str  # User ID
    username: str
    roles: List[str] = []
    iat: float
    exp: float
    
    @property
    def is_expired(self) -> bool:
        """Check if token is expired."""
        return datetime.utcnow().timestamp() > self.exp


def create_token(username: str, user_id: str, roles: List[str] = None) -> str:
    """
    Create a JWT token for the given user.
    
    Args:
        username: User's username
        user_id: Unique user identifier
        roles: List of roles for the user
    
    Returns:
        JWT token as string
    """
    payload = {
        "sub": user_id,
        "username": username,
        "roles": roles or [],
        "iat": datetime.utcnow().timestamp(),
        "exp": (datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)).timestamp(),
    }
    
    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str) -> TokenPayload:
    """
    Decode and validate a JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        TokenPayload with decoded claims
    
    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        
        return TokenPayload(**payload)
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenPayload:
    """
    FastAPI dependency to get the current authenticated user.
    
    Args:
        credentials: HTTP Bearer token credentials
    
    Returns:
        TokenPayload with user information
    
    Raises:
        HTTPException: If authentication fails
    """
    if not settings.AUTH_ENABLED:
        # Bypass auth if disabled
        return TokenPayload(
            sub="anonymous",
            username="anonymous",
            roles=[],
            iat=time.time(),
            exp=time.time() + 3600,
        )
    
    token = credentials.credentials
    
    try:
        return decode_token(token)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}",
        )


async def get_current_user_optional(
    request: Request,
) -> Optional[TokenPayload]:
    """
    FastAPI dependency to get the current user if authenticated.
    
    Useful for endpoints that allow both authenticated and anonymous access.
    """
    auth_header = request.headers.get("Authorization")
    
    if not auth_header:
        return None
    
    try:
        # Extract token from "Bearer <token>"
        token = auth_header.split(" ")[1]
        return decode_token(token)
    except Exception:
        return None


def check_permission(required_roles: List[str]):
    """
    Create a dependency to check if user has required roles.
    
    Args:
        required_roles: List of roles that are required
    
    Returns:
        FastAPI dependency function
    """
    async def dependency(user: TokenPayload = Depends(get_current_user)):
        if not settings.AUTH_ENABLED:
            return user
        
        # Check if user has any of the required roles
        if not any(role in user.roles for role in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        
        return user
    
    return dependency


# Pre-defined role checks
is_admin = check_permission(["admin"])
is_user = check_permission(["user", "admin"])
is_service = check_permission(["service", "admin"])
```

**Verification:**
```bash
# Test token creation and validation
cd code/hermes && python -c "
from hermes.auth import create_token, decode_token
token = create_token('testuser', '123', ['user'])
print('Token:', token[:50] + '...')
payload = decode_token(token)
print('Username:', payload.username)
print('Roles:', payload.roles)
"
# Expected: Should create and decode token successfully
```

#### Step 9.2.2: Add Authentication to API Endpoints
```python
# File: code/hermes/orchestrator.py (updates)

from hermes.auth import (
    get_current_user,
    get_current_user_optional,
    is_admin,
    is_user,
)

# Update generate endpoint
@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Generate text from a prompt",
    description="Send a prompt to a model and get generated text back",
)
async def generate(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
    user: TokenPayload = Depends(is_user),  # Require authentication
    dispatcher: FrameDispatcher = Depends(get_dispatcher),
) -> GenerateResponse:
    # ... existing implementation ...

# Update batch generate endpoint
@router.post(
    "/generate/batch",
    response_model=BatchGenerateResponse,
    summary="Generate text from multiple prompts",
    description="Send multiple prompts for batch processing",
)
async def generate_batch(
    request: BatchGenerateRequest,
    user: TokenPayload = Depends(is_user),  # Require authentication
    dispatcher: FrameDispatcher = Depends(get_dispatcher),
) -> BatchGenerateResponse:
    # ... existing implementation ...

# Add auth endpoints
@router.post(
    "/auth/token",
    summary="Get authentication token",
    description="Exchange credentials for JWT token",
)
async def get_token(
    username: str,
    password: str,
) -> Dict[str, str]:
    """
    Authenticate user and return JWT token.
    
    In production, this should integrate with a proper user database
    and password hashing.
    """
    # TODO: Implement proper user authentication
    # For now, use a simple check
    if username != "admin" or password != settings.JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    
    # In production, fetch user info from database
    user_id = "user-123"
    roles = ["admin"] if username == "admin" else ["user"]
    
    token = create_token(username, user_id, roles)
    
    return {"access_token": token, "token_type": "bearer"}


@router.get(
    "/auth/me",
    summary="Get current user info",
    description="Get information about the authenticated user",
)
async def get_current_user_info(
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get information about the current authenticated user."""
    return {
        "username": user.username,
        "user_id": user.sub,
        "roles": user.roles,
        "expires_at": datetime.fromtimestamp(user.exp).isoformat(),
    }
```

**Verification:**
```bash
# Test authentication endpoint
curl -X POST https://api.yourdomain.com/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=your-secret"
# Expected: Should return JWT token

# Test authenticated endpoint
curl -X POST https://api.yourdomain.com/api/v1/generate \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "max_tokens": 10}'
# Expected: Should return generated text

# Test without authentication
curl -X POST https://api.yourdomain.com/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "max_tokens": 10}'
# Expected: Should return 401 Unauthorized
```

#### Step 9.2.3: Configure OAuth2 Integration
```python
# File: code/hermes/auth_oauth2.py
"""
OAuth2 Authentication Provider

Integrates with GitHub, Google, or other OAuth2 providers.
"""

from typing import Optional, Dict, Any
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer

from hermes.auth import TokenPayload, create_token
from hermes.config import settings

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


class OAuth2UserInfo(BaseModel):
    """User information from OAuth2 provider."""
    provider: str
    provider_id: str
    username: str
    email: Optional[str] = None
    name: Optional[str] = None
    avatar: Optional[str] = None


class OAuth2Config(BaseModel):
    """OAuth2 provider configuration."""
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scopes: List[str]


# Provider configurations (should be loaded from config)
OAUTH2_PROVIDERS: Dict[str, OAuth2Config] = {
    "github": OAuth2Config(
        client_id=settings.GITHUB_CLIENT_ID,
        client_secret=settings.GITHUB_CLIENT_SECRET,
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scopes=["user:email", "read:user"],
    ),
}


async def exchange_code_for_token(code: str, provider: str) -> str:
    """
    Exchange OAuth2 authorization code for access token.
    
    Args:
        code: Authorization code from OAuth2 provider
        provider: Provider name (e.g., "github")
    
    Returns:
        JWT token for the user
    """
    import httpx
    
    config = OAUTH2_PROVIDERS.get(provider)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported OAuth2 provider: {provider}",
        )
    
    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        response = await client.post(
            config.token_url,
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": "https://api.yourdomain.com/api/v1/auth/callback",
            },
            headers={"Accept": "application/json"},
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange code for token",
            )
        
        token_data = response.json()
        access_token = token_data.get("access_token")
        
        # Get user info
        user_response = await client.get(
            config.userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        
        if user_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to get user info",
            )
        
        user_info = user_response.json()
        
        # Create or get user
        user_id = f"{provider}:{user_info.get('id')}"
        username = user_info.get("login") or user_info.get("name") or user_id
        email = user_info.get("email")
        
        # In production, store user in database
        # For now, create JWT token
        roles = ["user"]
        jwt_token = create_token(username, user_id, roles)
        
        return jwt_token


@router.get(
    "/auth/{provider}/login",
    summary="Initiate OAuth2 login",
    description="Redirect to OAuth2 provider for authentication",
)
async def oauth2_login(provider: str):
    """
    Initiate OAuth2 login flow.
    
    Redirects user to the OAuth2 provider's authorization page.
    """
    config = OAUTH2_PROVIDERS.get(provider)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported OAuth2 provider: {provider}",
        )
    
    # Generate state token (for CSRF protection)
    import secrets
    state = secrets.token_urlsafe(32)
    
    # Store state in session (in production, use Redis or similar)
    # For now, we'll skip proper state management
    
    # Build authorization URL
    from urllib.parse import urlencode
    
    params = {
        "client_id": config.client_id,
        "redirect_uri": "https://api.yourdomain.com/api/v1/auth/callback",
        "scope": " ".join(config.scopes),
        "state": state,
    }
    
    auth_url = f"{config.authorize_url}?{urlencode(params)}"
    
    return {"auth_url": auth_url}


@router.get(
    "/auth/callback",
    summary="OAuth2 callback",
    description="Handle OAuth2 callback from provider",
)
async def oauth2_callback(
    code: str,
    provider: str,
    state: str,
):
    """
    Handle OAuth2 callback from provider.
    
    Exchanges authorization code for JWT token.
    """
    token = await exchange_code_for_token(code, provider)
    
    # In production, return HTML with token or redirect with token in URL
    return {"access_token": token, "token_type": "bearer"}
```

**Verification:**
```bash
# Test OAuth2 login URL
curl https://api.yourdomain.com/api/v1/auth/github/login
# Expected: Should return auth_url
```

### Day 3: Ray Dashboard Authentication

#### Step 9.3.1: Configure Ray Dashboard with HTTPS and Auth
```yaml
# File: kubernetes/ray/raycluster.yaml (updated)
spec:
  rayStartParams:
    dashboard-user: admin
    dashboard-password: ${RAY_DASHBOARD_PASSWORD}
    dashboard-host: 0.0.0.0
    # Enable HTTPS for dashboard
    dashboard-tls-cert: /etc/ray/tls/ray-dashboard.crt
    dashboard-tls-key: /etc/ray/tls/ray-dashboard.key
  
  # Mount TLS certificates
  volumes:
  - name: ray-tls
    secret:
      secretName: ray-dashboard-tls
  
  volumeMounts:
  - name: ray-tls
    mountPath: /etc/ray/tls
    readOnly: true
```

**Verification:**
```bash
# Access dashboard via browser: https://ray.yourdomain.com/server/ray
# Expected: Should require username/password and use HTTPS
```

#### Step 9.3.2: Create Ray Dashboard Secret
```bash
# Create secret for Ray dashboard credentials
kubectl create secret generic ray-dashboard-creds \
  --namespace ray-system \
  --from-literal=RAY_DASHBOARD_PASSWORD=your-secure-password

# Mount in RayCluster
apiVersion: v1
kind: Secret
metadata:
  name: ray-dashboard-creds
  namespace: ray-system
type: Opaque
stringData:
  RAY_DASHBOARD_PASSWORD: "your-secure-password"
```

### Day 4: Network Policies

#### Step 9.4.1: Create Network Policies for Ray Cluster
```yaml
# File: kubernetes/security/ray-network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ray-allow-internal
  namespace: ray-system
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ray-system
    - namespaceSelector:
        matchLabels:
          name: hermes
    - namespaceSelector:
        matchLabels:
          name: monitoring
    ports:
    - protocol: TCP
      port: 8265  # Dashboard
    - protocol: TCP
      port: 6379  # Redis
    - protocol: TCP
      port: 10001  # Ray internal
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          name: ray-system
    ports:
    - protocol: TCP
      port: 6379
    - protocol: TCP
      port: 10001
    - protocol: UDP
      port: 41641  # Tailscale
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ray-allow-external
  namespace: ray-system
spec:
  podSelector:
    matchLabels:
      app: ray-head
  policyTypes:
  - Ingress
  ingress:
  - from:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 8265
```

**Verification:**
```bash
kubectl get networkpolicy -n ray-system
# Expected: ray-allow-internal and ray-allow-external should be listed
```

#### Step 9.4.2: Create Network Policies for Hermes
```yaml
# File: kubernetes/security/hermes-network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hermes-allow-internal
  namespace: hermes
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: hermes
    - namespaceSelector:
        matchLabels:
          name: monitoring
    - namespaceSelector:
        matchLabels:
          name: ray-system
    ports:
    - protocol: TCP
      port: 8000
    - protocol: TCP
      port: 9090  # Metrics
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          name: ray-system
    ports:
    - protocol: TCP
      port: 8265
    - protocol: TCP
      port: 10001
  - to:
    - namespaceSelector:
        matchLabels:
          name: monitoring
    ports:
    - protocol: TCP
      port: 9090  # Prometheus
    - protocol: TCP
      port: 3100  # Loki
    - protocol: TCP
      port: 4317  # Tempo
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hermes-allow-external
  namespace: hermes
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 8000
```

**Verification:**
```bash
kubectl get networkpolicy -n hermes
# Expected: hermes-allow-internal and hermes-allow-external should be listed
```

#### Step 9.4.3: Create Network Policies for Monitoring
```yaml
# File: kubernetes/security/monitoring-network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: monitoring-allow-internal
  namespace: monitoring
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: monitoring
    - namespaceSelector:
        matchLabels:
          name: ray-system
    - namespaceSelector:
        matchLabels:
          name: hermes
    ports:
    - protocol: TCP
      port: 9090  # Prometheus
    - protocol: TCP
      port: 3000  # Grafana
    - protocol: TCP
      port: 9093  # Alertmanager
    - protocol: TCP
      port: 3100  # Loki
    - protocol: TCP
      port: 3200  # Tempo
```

### Day 5: RBAC and Secrets Management

#### Step 9.5.1: Configure RBAC for Service Accounts
```yaml
# File: kubernetes/security/ray-rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ray-service
  namespace: ray-system
rules:
- apiGroups: [""]
  resources: ["pods", "services", "configmaps", "secrets"]
  verbs: ["get", "list", "watch", "create", "update", "delete"]
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets", "daemonsets"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["ray.io"]
  resources: ["rayclusters"]
  verbs: ["get", "list", "watch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ray-service-binding
  namespace: ray-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: ray-service
subjects:
- kind: ServiceAccount
  name: ray-head
  namespace: ray-system
```

**Verification:**
```bash
kubectl get role -n ray-system
kubectl get rolebinding -n ray-system
# Expected: ray-service and ray-service-binding should be listed
```

#### Step 9.5.2: Encrypt Secrets at Rest
```yaml
# File: kubernetes/security/encryption-config.yaml
apiVersion: v1
kind: EncryptionConfig
preferences: {}
providers:
- aescbc:
    keys:
    - name: key1
      secret: BASE64_ENCRYPTION_KEY_HERE
- identity: {}
```

**Apply encryption:**
```bash
# Generate encryption key
head -c 32 /dev/urandom | base64

# Update kube-apiserver with encryption config
# This requires restarting the API server
```

**Verification:**
```bash
kubectl get secrets -A -o json | kubectl replace -f -
# Secrets should be encrypted at rest
```

#### Step 9.5.3: Enable Audit Logging
```yaml
# File: kubernetes/security/audit-policy.yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
- level: Metadata
  resources:
  - group: ""
    resources: ["secrets", "configmaps"]
- level: RequestResponse
  resources:
  - group: ""
    resources: ["pods", "services"]
- level: Request
  resources:
  - group: "apps"
    resources: ["deployments", "statefulsets"]
- level: None
  resources:
  - group: ""
    resources: ["events"]

# Configure in kube-apiserver
# --audit-policy-file=/etc/kubernetes/audit-policy.yaml
# --audit-log-path=/var/log/kubernetes/audit.log
# --audit-log-maxage=30
# --audit-log-maxbackup=10
# --audit-log-maxsize=100
```

---

## Deliverables

### Files Created/Modified
- [ ] `kubernetes/security/letsencrypt-clusterissuer.yaml`
- [ ] `kubernetes/ray/certificate.yaml` (updated)
- [ ] `kubernetes/hermes/certificate.yaml` (updated)
- [ ] `kubernetes/monitoring/certificate.yaml` (updated)
- [ ] `code/hermes/auth.py`
- [ ] `code/hermes/auth_oauth2.py`
- [ ] `code/hermes/orchestrator.py` (updated with auth)
- [ ] `kubernetes/ray/raycluster.yaml` (updated with auth)
- [ ] `kubernetes/security/ray-network-policy.yaml`
- [ ] `kubernetes/security/hermes-network-policy.yaml`
- [ ] `kubernetes/security/monitoring-network-policy.yaml`
- [ ] `kubernetes/security/ray-rbac.yaml`
- [ ] `kubernetes/security/encryption-config.yaml`
- [ ] `kubernetes/security/audit-policy.yaml`

### Security Measures Implemented
- [ ] TLS certificates for all external endpoints
- [ ] JWT authentication for Hermes API
- [ ] OAuth2 integration (optional)
- [ ] Ray dashboard authentication
- [ ] Network policies for all namespaces
- [ ] RBAC for service accounts
- [ ] Secrets encryption at rest
- [ ] Audit logging configuration

---

## Verification Checklist

### TLS Certificates
- [ ] cert-manager is installed and running
- [ ] ClusterIssuer is configured
- [ ] All certificates show READY status
- [ ] All external endpoints use HTTPS
- [ ] Certificates are valid (not self-signed)

### Authentication
- [ ] JWT authentication is implemented
- [ ] /auth/token endpoint works
- [ ] Protected endpoints require authentication
- [ ] OAuth2 login flow is configured
- [ ] Ray dashboard requires authentication

### Authorization
- [ ] Role-based access control is configured
- [ ] Users have appropriate permissions
- [ ] Service accounts have minimal required permissions

### Network Security
- [ ] Network policies are configured for all namespaces
- [ ] Default-deny policies are in place
- [ ] Only necessary traffic is allowed
- [ ] External access is properly restricted

### Data Protection
- [ ] Secrets are encrypted at rest
- [ ] Sensitive data is not logged
- [ ] Audit logging is enabled

---

## Troubleshooting

### Certificate Issues

**Symptom:** Certificates show "Pending" or "Error" status

```bash
# Check certificate status
kubectl describe certificate -n ray-system ray-dashboard-tls

# Check cert-manager logs
kubectl logs -n cert-manager -l app=cert-manager

# Check DNS records
nslookup ray.yourdomain.com
```

**Fix:** Ensure DNS records point to your cluster and HTTP-01 challenges can succeed

### Authentication Failures

**Symptom:** Authentication always fails

```bash
# Check Hermes logs
kubectl logs -n hermes -l app=hermes

# Test token creation manually
kubectl exec -n hermes -it hermes-xxxx -- python -c "
from hermes.auth import create_token
token = create_token('testuser', '123', ['user'])
print(token)
"
```

**Fix:** Verify JWT_SECRET is consistent between token creation and validation

### Network Policy Issues

**Symptom:** Services cannot communicate after applying network policies

```bash
# Check network policy
kubectl get networkpolicy -A

# Test connectivity
kubectl exec -n hermes -it hermes-xxxx -- curl -v http://raycluster-head-svc.ray-system.svc.cluster.local:8265
```

**Fix:** Verify network policies allow necessary traffic

### RBAC Issues

**Symptom:** Permission denied errors

```bash
# Check RBAC configuration
kubectl get roles -A
kubectl get rolebindings -A

# Check service account permissions
kubectl auth can-i --as=system:serviceaccount:ray-system:ray-head get pods -n ray-system
```

**Fix:** Adjust role bindings to grant necessary permissions

---

## Rollback Plan

If Phase 9 fails:

1. **cert-manager**: Uninstall and use manual certificates
   ```bash
   helm uninstall cert-manager -n cert-manager
   kubectl delete ns cert-manager
   ```

2. **Network Policies**: Delete all network policies
   ```bash
   kubectl delete networkpolicy -A --all
   ```

3. **RBAC**: Reset to default
   ```bash
   kubectl delete role -A --all
   kubectl delete rolebinding -A --all
   ```

---

## Next Phase

After completing Phase 9, proceed to **Phase 10: Performance Optimization** to implement auto-scaling, GPU sharing, and other performance improvements.
