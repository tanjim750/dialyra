# 2. Authentication & Role Management

# Purpose

Authentication & Role Management is responsible for securing the Dialyra platform and controlling access to business resources.

Since Dialyra is a multi-tenant telephony platform, every request, flow, campaign, SIP trunk, and runtime action must operate inside a properly authenticated business workspace.

This layer ensures:

* Secure login system
* Business isolation
* Permission-based access control
* Role-specific operations
* Agent-level restrictions
* Workspace-scoped resource access

---

# Core Goals

## 1. Secure Platform Access

Prevent unauthorized access to:

* SIP credentials
* Call campaigns
* Customer phone numbers
* Audio assets
* Recordings
* Analytics

---

## 2. Multi-Tenant Security Isolation

A user from one business must never access another business’s data.

Example:

```text id="f1"
Business A User
 ❌ cannot access
Business B Flows
```

---

## 3. Role-Based Permission System

Different users should have different capabilities.

Example:

| Role    | Capability                |
| ------- | ------------------------- |
| Owner   | Full control              |
| Admin   | Manage operations         |
| Manager | Campaign management       |
| Agent   | Receive transferred calls |
| Viewer  | Read-only access          |

---

# Authentication Architecture

# Recommended Auth Strategy

## JWT-Based Authentication

Dialyra should use:

```text id="f2"
Access Token + Refresh Token
```

---

# Why JWT?

Because the platform contains:

* APIs
* FastAGI communication
* Real-time monitoring
* distributed workers
* scalable services

JWT works best for stateless scalable systems.

---

# Authentication Flow

```text id="f3"
User Login
 ↓
JWT Issued
 ↓
Client stores token
 ↓
Authenticated API requests
 ↓
Middleware validates token
 ↓
Workspace access granted
```

---

# Main Entities

# 1. User

Represents an authenticated platform user.

---

## User Fields

| Field         | Type      | Purpose             |
| ------------- | --------- | ------------------- |
| id            | UUID      | User ID             |
| business_id   | FK        | Workspace ownership |
| full_name     | String    | User name           |
| email         | String    | Login email         |
| password_hash | String    | Encrypted password  |
| role          | Enum      | Permission role     |
| status        | Enum      | active/inactive     |
| last_login    | Timestamp | Last access         |
| created_at    | Timestamp | Creation time       |

---

# 2. Refresh Token

Stores long-lived refresh sessions.

---

## Purpose

Allows secure token renewal without forcing re-login.

---

## Refresh Token Fields

| Field      | Type      |
| ---------- | --------- |
| id         | UUID      |
| user_id    | FK        |
| token      | String    |
| expires_at | Timestamp |
| revoked    | Boolean   |

---

# 3. Permission Model (Optional Advanced Layer)

Future extensible permission system.

---

## Example Permissions

| Permission       | Purpose              |
| ---------------- | -------------------- |
| manage_sip       | SIP management       |
| manage_flows     | Flow editing         |
| manage_campaigns | Campaign operations  |
| monitor_calls    | Real-time monitoring |
| manage_users     | User management      |

---

# User Roles

# 1. Owner

Highest business authority.

## Capabilities

* Full workspace access
* Billing
* SIP management
* User management
* Flow management
* Campaign control
* Analytics access

---

# 2. Admin

Operational administrator.

## Capabilities

* Manage SIP trunks
* Manage flows
* Launch campaigns
* Manage assets
* Monitor calls

Cannot:

* transfer business ownership

---

# 3. Manager

Campaign/operator role.

## Capabilities

* Create campaigns
* Monitor campaigns
* View analytics
* Access reports

Cannot:

* modify SIP trunks
* manage workspace users

---

# 4. Agent

Human call receiver.

## Capabilities

* Receive transferred calls
* View assigned sessions
* Access limited call data

Cannot:

* manage platform configuration

---

# 5. Viewer

Read-only role.

## Capabilities

* View analytics
* View reports
* View logs

Cannot:

* modify anything

---

# Workspace Isolation Strategy

Every authenticated request must contain:

```text id="f4"
business_id
```

derived from:

```text id="f5"
JWT token
```

---

# Example

```text id="f6"
JWT
 ↓
user_id
 ↓
business_id
 ↓
query filtering
```

---

# Security Middleware

Every API request should pass through:

## 1. JWT Validation

Checks:

* token validity
* expiration
* signature

---

## 2. User Validation

Checks:

* active user
* business status
* role permissions

---

## 3. Workspace Injection

Automatically inject:

```text id="f7"
request.business_id
request.user
```

into runtime context.

---

# Recommended Auth Endpoints

# 1. Register Business Owner

```http id="h1"
POST /api/auth/register
```

Creates:

* business
* owner account
* workspace

---

# 2. Login

```http id="h2"
POST /api/auth/login
```

Returns:

```json id="j1"
{
  "access_token": "...",
  "refresh_token": "...",
  "user": {},
  "business": {}
}
```

---

# 3. Refresh Token

```http id="h3"
POST /api/auth/refresh
```

---

# 4. Logout

```http id="h4"
POST /api/auth/logout
```

Revokes refresh token.

---

# 5. Current User

```http id="h5"
GET /api/auth/me
```

Returns authenticated user context.

---

# Password Security

Passwords must NEVER be stored directly.

Use:

```text id="f8"
bcrypt
```

or

```text id="f9"
argon2
```

---

# Recommended Password Rules

| Rule           | Requirement |
| -------------- | ----------- |
| Minimum length | 8+          |
| Hashing        | Required    |
| Plain storage  | Never       |
| Reset tokens   | Expirable   |

---

# API Authorization Strategy

# Example Route Protection

## Public Route

```http id="h6"
POST /api/auth/login
```

No authentication needed.

---

## Protected Route

```http id="h7"
POST /api/flows
```

Requires:

* valid JWT
* active business
* proper role

---

# Role Middleware Example

```text id="f10"
Owner/Admin only
```

for:

* SIP management
* user management
* workspace settings

---

# Agent Authentication Flow

Special case for transferred calls.

Example:

```text id="f11"
Customer
 ↓
IVR
 ↓
Transfer to Agent
 ↓
Agent Extension
```

Agents may authenticate using:

* dashboard login
* SIP extension association
* session mapping

---

# Future Authentication Extensions

# 1. Two-Factor Authentication (2FA)

Optional future enhancement.

---

# 2. API Keys

For:

* webhook integrations
* external systems
* CRM integrations

---

# 3. SSO / OAuth

Possible future integrations:

* Google login
* Microsoft login
* enterprise SSO

---

# Security Recommendations

## 1. Rate Limiting

Protect login endpoints.

Example:

```text id="f12"
5 failed attempts
 ↓
temporary lock
```

---

## 2. Token Expiration

| Token         | Lifetime |
| ------------- | -------- |
| Access Token  | Short    |
| Refresh Token | Long     |

---

## 3. Audit Logging

Track:

* login attempts
* password resets
* role changes
* SIP modifications

---

# Recommended Initial Implementation Order

## Phase 1

Implement:

1. User model
2. Business association
3. JWT login
4. Password hashing
5. Auth middleware

---

## Phase 2

Implement:

1. Role middleware
2. Permission checks
3. Refresh tokens
4. Logout handling

---

## Phase 3

Implement:

1. Audit logs
2. API keys
3. 2FA
4. advanced permission engine

---

# Final Architecture Summary

```text id="f13"
Business
 └── Users
      ├── Owner
      ├── Admin
      ├── Manager
      ├── Agent
      └── Viewer
```

---

# Final System Responsibility

| Layer      | Responsibility                 |
| ---------- | ------------------------------ |
| Flask      | Authentication & authorization |
| PostgreSQL | User/session storage           |
| Redis      | Temporary auth/cache           |
| FastAGI    | Runtime user context access    |
| Asterisk   | SIP/media only                 |
