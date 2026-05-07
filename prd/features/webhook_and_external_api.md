# 14. Webhook & External API Integration

# Purpose

Webhook & External API Integration enables Dialyra to connect with external systems in real-time.

This allows businesses to:

* trigger calls from external apps
* receive call events in real-time
* sync CRM/ERP data
* integrate with ecommerce systems
* automate workflows beyond Dialyra

---

# Core Goals

## 1. Real-Time Event Delivery

Push call events instantly to external systems.

---

## 2. External Trigger Support

Allow external systems to:

* start calls
* trigger campaigns
* update flows

---

## 3. Reliable Delivery System

Ensure:

* retry on failure
* delivery guarantees
* event ordering control

---

## 4. Secure Integration Layer

Protect APIs with authentication and validation.

---

# High-Level Architecture

```text id="f1"
Asterisk / Flow Engine
 ↓
Event Bus
 ↓
Webhook Dispatcher
 ↓
External APIs
```

---

# Main Concepts

# 1. Webhook

HTTP callback triggered by Dialyra events.

---

# 2. External API Trigger

External system calling Dialyra APIs.

---

# 3. Event Subscription

Business-defined event listeners.

---

# Main Entities

# 1. Webhook Endpoint

Stores external webhook configuration.

---

## Fields

| Field           | Type       |
| --------------- | ---------- |
| id              | UUID       |
| business_id     | FK         |
| url             | String     |
| secret          | String     |
| events          | JSON Array |
| is_active       | Boolean    |
| retry_policy_id | FK         |
| created_at      | Timestamp  |

---

# Supported Events

| Event              | Meaning        |
| ------------------ | -------------- |
| call.initiated     | call started   |
| call.answered      | call connected |
| call.failed        | call failed    |
| call.completed     | call ended     |
| dtmf.received      | input received |
| flow.node_entered  | flow execution |
| campaign.started   | campaign start |
| campaign.completed | campaign end   |

---

# 2. Webhook Delivery Log

Tracks each delivery attempt.

---

## Fields

| Field         | Type      |
| ------------- | --------- |
| id            | UUID      |
| webhook_id    | FK        |
| event_type    | String    |
| payload       | JSON      |
| status        | Enum      |
| response_code | Integer   |
| response_body | Text      |
| attempt_count | Integer   |
| delivered_at  | Timestamp |
| next_retry_at | Timestamp |

---

# Delivery Status Types

| Status   | Meaning           |
| -------- | ----------------- |
| pending  | not sent          |
| success  | delivered         |
| failed   | permanent failure |
| retrying | retry scheduled   |

---

# Webhook Event Flow

```text id="f2"
Internal Event
 ↓
Event Queue
 ↓
Webhook Dispatcher
 ↓
HTTP Request
 ↓
External System
```

---

# Webhook Payload Structure

```json id="j1"
{
  "event": "call.answered",
  "timestamp": "2026-05-05T12:00:00Z",
  "business_id": "123",
  "call_session_id": "abc",
  "data": {
    "caller": "8801xxxx",
    "duration": 45
  }
}
```

---

# Security Mechanisms

## 1. Signature Verification

Each webhook includes:

```text id="f3"
X-Dialyra-Signature
```

---

## 2. Secret Key HMAC

Payload signed using HMAC SHA256.

---

## 3. IP Allowlist (Optional)

Restrict delivery to trusted endpoints.

---

# Retry Strategy

# Why Retry Needed?

External APIs may fail due to:

* downtime
* network errors
* timeout

---

# Retry Flow

```text id="f4"
Webhook Failure
 ↓
Retry Queue
 ↓
Exponential Backoff
 ↓
Re-delivery
```

---

# Retry Policy Example

| Attempt | Delay     |
| ------- | --------- |
| 1       | immediate |
| 2       | 1 min     |
| 3       | 5 min     |
| 4       | 15 min    |

---

# External API Integration (Inbound)

External systems can trigger Dialyra.

---

# Example Use Cases

* CRM triggers outbound call
* ecommerce order triggers IVR
* support ticket escalation

---

# API Trigger Flow

```text id="f5"
External System
 ↓
API Request
 ↓
Validation
 ↓
Flow/Campaign Execution
 ↓
AMI Originate
```

---

# Example Endpoint

```http id="h1"
POST /api/external/call
```

---

# Request Example

```json id="j2"
{
  "phone": "8801631596698",
  "flow_id": "flow_123",
  "metadata": {
    "order_id": "ORD-10"
  }
}
```

---

# Authentication Methods

## 1. API Key

Simple header-based auth.

---

## 2. JWT Token

Advanced secure authentication.

---

## 3. HMAC Signed Requests

Highest security option.

---

# Rate Limiting

Prevent abuse:

| Limit        | Value |
| ------------ | ----- |
| requests/sec | 10    |
| burst        | 50    |

---

# Event Routing System

Events should be filtered per webhook.

---

# Example

```text id="f6"
call.answered → webhook A
call.failed → webhook B
```

---

# Filtering Rules

Each webhook can subscribe to:

* specific event types
* specific campaigns
* specific flows

---

# Dead Letter Queue (DLQ)

Failed webhook deliveries stored for manual retry.

---

# Example

```text id="f7"
Webhook permanently failed
 ↓
Move to DLQ
```

---

# Webhook Analytics

Track:

* delivery success rate
* failure rate
* latency
* retry counts

---

# Example Metrics

| Metric       | Meaning     |
| ------------ | ----------- |
| success_rate | reliability |
| avg_latency  | speed       |
| retry_rate   | instability |

---

# Flow Integration

Webhooks can be triggered from:

* flow nodes
* campaign events
* call events
* agent transfer events

---

# Example Flow Node

```text id="f8"
After DTMF input → call webhook
```

---

# Real-Time Streaming vs Webhook

| Type               | Use Case             |
| ------------------ | -------------------- |
| webhook            | external integration |
| internal event bus | system processing    |

---

# External System Examples

Dialyra can integrate with:

* CRM systems
* Shopify
* ERP systems
* support platforms
* analytics tools

---

# Example Workflow

```text id="f9"
Order Placed (Shopify)
 ↓
Webhook Trigger
 ↓
Dialyra Call
 ↓
IVR Flow
 ↓
Result Sent Back
```

---

# Failure Handling

Handle:

* timeout
* DNS failure
* invalid response
* HTTP 500 errors

---

# Example Failure Event

```json id="j3"
{
  "status": "failed",
  "reason": "timeout"
}
```

---

# Security Best Practices

* rotate webhook secrets
* validate payload signature
* encrypt sensitive metadata
* restrict endpoints

---

# Suggested Initial Implementation Order

## Phase 1

1. webhook model
2. event dispatcher
3. HTTP delivery
4. logging system

---

## Phase 2

1. retry system
2. signature security
3. filtering rules
4. API triggers

---

## Phase 3

1. DLQ system
2. analytics dashboard
3. streaming integration
4. multi-region delivery

---

# Scalability Considerations

Large-scale systems require:

* async queue workers
* batching events
* distributed webhook dispatchers
* retry optimization

---

# Recommended Architecture

```text id="f10"
Event Engine
 ↓
Queue System
 ↓
Webhook Dispatcher Workers
 ↓
External APIs
```

---

# Final Architecture Summary

```text id="f11"
Internal Events
 ↓
Event Bus
 ↓
Webhook Layer
 ↓
External Systems
```

---

# Final Runtime Flow

```text id="f12"
Call/Event Occurs
 ↓
Event Generated
 ↓
Webhook Matched
 ↓
Delivery Attempt
 ↓
Success / Retry / Fail
```
