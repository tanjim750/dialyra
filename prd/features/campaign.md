# 10. Campaign Management

# Purpose

Campaign Management is responsible for organizing, scheduling, executing, and monitoring bulk outbound calling operations for businesses.

This system enables Dialyra to automate large-scale communication workflows such as:

- order confirmation
- payment reminders
- marketing calls
- delivery verification
- customer surveys
- OTP verification
- customer engagement campaigns

using dynamic voice flows.

---

# Core Goals

## 1. Bulk Outbound Call Execution

Allow businesses to call thousands of customers automatically.

---

## 2. Flow-Based Campaign Logic

Each campaign should use dynamic runtime flows.

---

## 3. Queue & Retry Management

Handle:
- failed calls
- retries
- concurrency limits
- rate control

---

## 4. Campaign Analytics

Track:
- answer rates
- engagement
- conversions
- failures

---

# High-Level Architecture

```text id="f1"
Campaign
 ↓
Target Contacts
 ↓
Call Queue
 ↓
AMI Originate
 ↓
Flow Execution
 ↓
Event Tracking
 ↓
Analytics
```

---

# Main Concepts

# 1. Campaign

Represents a bulk outbound operation.

---

# 2. Campaign Contact

Represents an individual target customer.

---

# 3. Campaign Execution

Tracks runtime call processing.

---

# Main Entities

# 1. Campaign

Stores campaign metadata.

---

## Campaign Fields

| Field | Type |
|---|---|
| id | UUID |
| business_id | FK |
| name | String |
| description | Text |
| flow_id | FK |
| sip_trunk_id | FK |
| campaign_type | Enum |
| status | Enum |
| start_at | Timestamp |
| end_at | Timestamp |
| max_concurrent_calls | Integer |
| retry_limit | Integer |
| created_by | FK |
| created_at | Timestamp |

---

# Campaign Status Types

| Status | Meaning |
|---|---|
| draft | not started |
| scheduled | waiting |
| running | active |
| paused | temporarily stopped |
| completed | finished |
| failed | execution failed |
| cancelled | manually stopped |

---

# 2. Campaign Contact

Stores individual recipients.

---

## Campaign Contact Fields

| Field | Type |
|---|---|
| id | UUID |
| campaign_id | FK |
| customer_name | String |
| phone_number | String |
| metadata | JSON |
| call_status | Enum |
| retry_count | Integer |
| last_attempt_at | Timestamp |
| answered_at | Timestamp |
| completed_at | Timestamp |
| created_at | Timestamp |

---

# Example Metadata

```json id="j1"
{
  "order_id": "ORD-102",
  "amount": 500,
  "language": "bn"
}
```

---

# Why Metadata Important?

Because runtime flows can dynamically personalize calls.

---

# Example

```text id="f2"
"Hello Tanjim, your order amount is 500 taka"
```

---

# 3. Campaign Call Attempt

Tracks individual retry attempts.

---

## Fields

| Field | Type |
|---|---|
| id | UUID |
| campaign_contact_id | FK |
| call_session_id | FK |
| attempt_number | Integer |
| status | Enum |
| started_at | Timestamp |
| ended_at | Timestamp |

---

# Campaign Execution Flow

# Step 1 — Create Campaign

Business configures:
- flow
- SIP trunk
- concurrency
- retry policy

---

# Step 2 — Upload Contacts

CSV/API/manual upload.

---

# Step 3 — Queue Contacts

System prepares outbound jobs.

---

# Step 4 — Originate Calls

AMI originates calls progressively.

---

# Step 5 — Runtime Flow Executes

Each answered call enters Flow Engine.

---

# Step 6 — Track Results

Store:
- answered
- failed
- busy
- completed

---

# Contact Upload Sources

# 1. CSV Upload

Example:

```csv id="c1"
name,phone,amount
Tanjim,8801XXXX,500
```

---

# 2. API Import

Businesses push contacts via API.

---

# 3. Database Sync

Future external integrations.

---

# Concurrency Control

# Purpose

Prevent:
- SIP overload
- provider throttling
- server overload

---

# Example

```text id="f3"
max_concurrent_calls = 50
```

---

# Runtime Queue Example

```text id="f4"
5000 contacts
 ↓
50 calls simultaneously
 ↓
Next batch after completion
```

---

# Retry Logic

# Retry Conditions

| Condition | Retry? |
|---|---|
| no_answer | yes |
| busy | yes |
| failed | yes |
| answered | no |

---

# Example Retry Policy

```text id="f5"
Retry 3 times
with 15 minute interval
```

---

# Call Scheduling

Campaigns may run:
- immediately
- scheduled time
- business hours only

---

# Example

```text id="f6"
Run between 10AM - 8PM
```

---

# Runtime Call Personalization

Flows may use contact metadata dynamically.

---

# Example

```text id="f7"
Hello {{customer_name}}
```

---

# Runtime Injection Flow

```text id="f8"
Campaign Contact
 ↓
Metadata Injection
 ↓
Flow Runtime
 ↓
Dynamic TTS
```

---

# Campaign Types

| Type | Purpose |
|---|---|
| order_confirmation | ecommerce |
| payment_reminder | finance |
| survey | feedback |
| marketing | promotions |
| otp | verification |
| support_followup | customer service |

---

# Campaign Analytics

# Core Metrics

| Metric | Meaning |
|---|---|
| total_contacts | uploaded contacts |
| calls_attempted | originated |
| answered_calls | answered |
| failed_calls | failed |
| conversion_rate | successful actions |
| average_duration | engagement |

---

# Example Dashboard Metrics

```text id="f9"
Total Calls: 5000
Answered: 3200
Busy: 400
Failed: 600
No Answer: 800
```

---

# Live Campaign Monitoring

Future dashboard may show:

- active calls
- current queue
- call rate
- SIP usage
- success rates

---

# Queue System Architecture

# Recommended Stack

```text id="f10"
Flask
 ↓
Redis Queue
 ↓
Worker Pool
 ↓
AMI Originate
```

---

# Why Queue-Based?

Campaign execution requires:
- scalability
- retries
- concurrency management
- scheduling

---

# Recommended Worker Design

Workers should:
- fetch pending contacts
- originate calls
- monitor results
- update statuses

---

# Call Rate Limiting

Prevent provider bans.

---

# Example

```text id="f11"
10 calls/sec
```

---

# SIP Trunk Protection

Campaigns must respect:
- provider CPS limits
- concurrent channel limits

---

# Flow Integration

Campaign calls enter the same:

```text id="f12"
Dynamic Flow Engine
```

used by normal calls.

---

# Example Runtime Flow

```text id="f13"
Campaign Call
 ↓
Customer Answers
 ↓
Flow Starts
 ↓
DTMF Interaction
 ↓
Completion
```

---

# Failure Handling

Track:
- SIP failure
- congestion
- timeout
- trunk unavailable

---

# Example Failure Event

```json id="j2"
{
  "status": "failed",
  "reason": "sip_congestion"
}
```

---

# Pause & Resume Support

Businesses may:
- pause campaigns
- resume later

without losing progress.

---

# Duplicate Prevention

Avoid calling same number repeatedly.

---

# Example Rules

```text id="f14"
Do not call same number within 24 hours
```

---

# Security Considerations

# 1. Business Isolation

Businesses access only their campaigns.

---

# 2. Rate Limits

Prevent abuse/spam.

---

# 3. Contact Validation

Validate:
- phone format
- duplicates
- invalid numbers

---

# 4. Audit Logs

Track:
- campaign changes
- uploads
- deletions
- executions

---

# Recommended API Endpoints

# Create Campaign

```http id="h1"
POST /api/campaigns
```

---

# Upload Contacts

```http id="h2"
POST /api/campaigns/{id}/contacts
```

---

# Start Campaign

```http id="h3"
POST /api/campaigns/{id}/start
```

---

# Pause Campaign

```http id="h4"
POST /api/campaigns/{id}/pause
```

---

# Resume Campaign

```http id="h5"
POST /api/campaigns/{id}/resume
```

---

# Get Campaign Analytics

```http id="h6"
GET /api/campaigns/{id}/analytics
```

---

# Suggested Initial Implementation Order

# Phase 1

Implement:

1. campaign model
2. contact upload
3. queue system
4. AMI originate workers

---

# Phase 2

Implement:

1. retry engine
2. scheduling
3. analytics
4. concurrency control

---

# Phase 3

Implement:

1. predictive dialing
2. AI optimization
3. smart retries
4. adaptive pacing

---

# Scalability Considerations

Large deployments may require:

- distributed workers
- SIP load balancing
- horizontal scaling
- queue partitioning

---

# Final Architecture Summary

```text id="f15"
Campaign
 ↓
Contact Queue
 ↓
Workers
 ↓
AMI Originate
 ↓
Flow Engine
 ↓
Analytics
```

---

# Final Runtime Flow

```text id="f16"
Upload Contacts
 ↓
Queue Calls
 ↓
Originate
 ↓
Customer Answers
 ↓
Flow Execution
 ↓
Track Results
```