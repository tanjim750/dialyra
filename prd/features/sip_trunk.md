# 3. SIP Trunk Management

# Purpose

SIP Trunk Management is responsible for connecting Dialyra with telecom providers and enabling outbound/inbound call communication through Asterisk.

This layer allows businesses to:

* Configure SIP providers
* Register SIP trunks
* Route outbound calls
* Receive inbound calls
* Share global trunks
* Use dedicated trunks
* Control call routing behavior

It acts as the telephony connectivity layer between:

```text id="f1"
Dialyra
↓
Asterisk
↓
SIP Provider
↓
Public Telephone Network
```

---

# Core Goals

## 1. Business Telephony Integration

Allow each business to connect its own telecom provider.

Example:

```text id="f2"
Business A → BDWebs
Business B → Twilio
Business C → Custom IP Trunk
```

---

## 2. Shared Global Trunk Support

Allow platform-level SIP trunks reusable across businesses.

Example:

```text id="f3"
Global SIP Pool
 ├── Trunk 1
 ├── Trunk 2
 └── Trunk 3
```

---

## 3. Dynamic Call Routing

Determine which SIP trunk should be used during runtime.

Routing may depend on:

* business settings
* campaign
* destination country
* load balancing
* failover
* concurrency limits

---

# Telephony Architecture

# High-Level Flow

```text id="f4"
Flask API
 ↓
AMI Originate
 ↓
Asterisk
 ↓
PJSIP Endpoint
 ↓
SIP Provider
 ↓
Destination Number
```

---

# SIP Trunk Types

# 1. Business SIP Trunk

Owned by a specific business.

---

## Purpose

Allows businesses to use their own telecom accounts.

---

## Example

```text id="f5"
Business A
 └── own SIP credentials
```

---

# 2. Global SIP Trunk

Managed by platform administrators.

---

## Purpose

Shared SIP access for businesses without their own provider.

---

## Example

```text id="f6"
Dialyra Global Trunk
 ↓
multiple businesses use it
```

---

# 3. IP Authentication Trunk

Authentication based on VPS public IP.

---

## Purpose

No username/password registration required.

Provider whitelists server IP.

---

# 4. Registration-Based Trunk

Traditional SIP username/password registration.

---

## Purpose

Most common SIP provider integration.

---

# Main Entities

# 1. SIP Trunk

Primary SIP configuration entity.

---

## SIP Trunk Fields

| Field                | Type        | Purpose                |
| -------------------- | ----------- | ---------------------- |
| id                   | UUID        | Trunk ID               |
| business_id          | FK nullable | Null for global trunks |
| name                 | String      | Friendly name          |
| provider_name        | String      | Telecom provider       |
| trunk_type           | Enum        | registration/ip        |
| is_global            | Boolean     | Shared or dedicated    |
| host                 | String      | SIP server             |
| port                 | Integer     | SIP port               |
| username             | String      | SIP username           |
| password             | Encrypted   | SIP password           |
| transport            | Enum        | udp/tcp/tls            |
| from_user            | String      | Caller identity        |
| from_domain          | String      | SIP domain             |
| outbound_proxy       | String      | Optional proxy         |
| codecs               | JSON        | Allowed codecs         |
| max_concurrent_calls | Integer     | CPS/concurrency        |
| is_active            | Boolean     | Status                 |
| created_at           | Timestamp   | Creation               |

---

# 2. SIP Routing Policy

Controls runtime routing behavior.

---

## Purpose

Determines which trunk should be used.

---

## Routing Fields

| Field            | Type    |
| ---------------- | ------- |
| id               | UUID    |
| business_id      | FK      |
| strategy         | Enum    |
| fallback_enabled | Boolean |
| primary_trunk_id | FK      |
| backup_trunk_id  | FK      |

---

# 3. SIP Usage Log

Tracks SIP usage statistics.

---

## Purpose

Analytics and monitoring.

---

## Usage Fields

| Field            | Type      |
| ---------------- | --------- |
| id               | UUID      |
| sip_trunk_id     | FK        |
| active_calls     | Integer   |
| failed_calls     | Integer   |
| successful_calls | Integer   |
| last_used_at     | Timestamp |

---

# Trunk Types Explained

# Registration-Based SIP

Provider requires:

* username
* password
* REGISTER requests

---

## Example

```text id="f7"
Asterisk
 ↓ REGISTER
Provider
 ↓ 200 OK
Registered
```

---

## Used For

* BDWebs
* retail VoIP providers
* hosted SIP accounts

---

# IP Authentication SIP

Provider trusts VPS IP.

No registration required.

---

## Example

```text id="f8"
Provider Whitelists:
138.x.x.x
```

Then Asterisk directly sends INVITE requests.

---

## Benefits

* simpler
* more stable
* better for large-scale outbound systems

---

# Asterisk Configuration Strategy

Dialyra should NOT manually edit:

```text id="f9"
pjsip.conf
```

directly during runtime.

---

# Recommended Strategy

Generate configs dynamically:

```text id="f10"
/etc/asterisk/pjsip_custom/
```

Example:

```text id="f11"
/etc/asterisk/pjsip_custom/
 ├── business_1.conf
 ├── business_2.conf
 └── global_trunks.conf
```

---

# Runtime Flow

# Step 1 — Business Adds SIP Trunk

```http id="h1"
POST /api/sip-trunks
```

---

# Step 2 — Flask Stores Trunk

Stored in PostgreSQL.

---

# Step 3 — Config Generator Runs

Generates:

```text id="f12"
PJSIP endpoint
PJSIP auth
PJSIP registration
```

---

# Step 4 — Reload Asterisk

Using:

```text id="f13"
pjsip reload
```

or AMI command.

---

# Step 5 — Trunk Becomes Available

Asterisk can now place calls.

---

# Dynamic Outbound Call Routing

# Example Flow

```text id="f14"
Campaign
 ↓
Business
 ↓
Routing Policy
 ↓
Selected SIP Trunk
 ↓
AMI Originate
 ↓
Asterisk
```

---

# SIP Failover Logic

Example:

```text id="f15"
Primary Trunk Fails
 ↓
Automatically use backup trunk
```

---

# Recommended Routing Strategies

| Strategy    | Purpose            |
| ----------- | ------------------ |
| priority    | Always use primary |
| round_robin | Load balancing     |
| least_used  | Lower load         |
| failover    | Backup routing     |

---

# Codec Management

Recommended codecs initially:

```text id="f16"
ulaw
alaw
```

Later:

```text id="f17"
g729
opus
gsm
```

---

# Concurrency Management

Each trunk should define:

```text id="f18"
max_concurrent_calls
```

---

## Purpose

Prevents:

* provider rejection
* overload
* rate limiting

---

# Caller ID Management

Businesses may configure:

* default caller ID
* campaign caller ID
* masked caller IDs

---

# Example

```text id="f19"
Dialyra Support <096xxxxxxx>
```

---

# Security Requirements

# 1. Encrypt SIP Passwords

Never store plaintext credentials.

---

# 2. Restrict SIP Management

Only:

```text id="f20"
Owner/Admin
```

can modify trunks.

---

# 3. Audit Logging

Track:

* trunk changes
* password updates
* trunk failures

---

# Health Monitoring

Dialyra should monitor:

* registration status
* response latency
* active channels
* rejection rates

---

# Monitoring Sources

Use:

* AMI events
* PJSIP status
* Asterisk CLI
* RTP statistics

---

# Important Runtime Separation

| Layer      | Responsibility          |
| ---------- | ----------------------- |
| Flask      | SIP management          |
| PostgreSQL | trunk storage           |
| Redis      | temporary runtime state |
| FastAGI    | runtime flow logic      |
| Asterisk   | actual SIP signaling    |

---

# API Endpoints

# Create SIP Trunk

```http id="h2"
POST /api/sip-trunks
```

---

# Update SIP Trunk

```http id="h3"
PUT /api/sip-trunks/{id}
```

---

# Delete SIP Trunk

```http id="h4"
DELETE /api/sip-trunks/{id}
```

---

# List SIP Trunks

```http id="h5"
GET /api/sip-trunks
```

---

# Reload Trunk

```http id="h6"
POST /api/sip-trunks/{id}/reload
```

---

# Test Trunk

```http id="h7"
POST /api/sip-trunks/{id}/test
```

---

# Recommended Initial Development Order

# Phase 1

Implement:

1. SIP trunk DB model
2. CRUD APIs
3. Asterisk config generator
4. pjsip reload integration

---

# Phase 2

Implement:

1. registration monitoring
2. health checks
3. routing policies
4. failover logic

---

# Phase 3

Implement:

1. CPS control
2. advanced routing
3. intelligent load balancing
4. provider analytics

---

# Final Architecture Summary

```text id="f21"
Business
 └── SIP Trunks
      ├── Registration SIP
      ├── IP Trunk
      └── Global Shared SIP
```

---

# Final System Flow

```text id="f22"
Business
 ↓
SIP Trunk
 ↓
AMI Originate
 ↓
Asterisk
 ↓
PJSIP
 ↓
Provider
 ↓
Customer Phone
```
