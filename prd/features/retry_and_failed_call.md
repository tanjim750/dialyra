# 11. Retry & Failed Call Handling

# Purpose

Retry & Failed Call Handling is responsible for intelligently managing unsuccessful outbound call attempts.

This system ensures Dialyra can:

* retry unanswered calls
* recover temporary failures
* avoid unnecessary spam attempts
* optimize campaign success rates
* protect SIP trunks and providers
* improve customer reachability

without manual intervention.

---

# Core Goals

## 1. Automatic Retry Processing

Automatically retry failed or unanswered calls.

---

## 2. Smart Failure Classification

Differentiate between:

* busy
* no answer
* rejected
* network failure
* invalid number

---

## 3. Retry Strategy Control

Allow configurable:

* retry intervals
* retry limits
* retry conditions

---

## 4. SIP Resource Protection

Prevent:

* excessive retries
* provider bans
* CPS overload

---

# High-Level Architecture

```text id="f1"
Call Attempt
 ↓
Call Result Analysis
 ↓
Failure Classification
 ↓
Retry Decision Engine
 ↓
Retry Queue
 ↓
AMI Originate
```

---

# Main Concepts

# 1. Failure Classification

Every failed call should be categorized.

---

# 2. Retry Policy

Determines:

* when retry occurs
* how many retries allowed
* retry interval

---

# 3. Retry Queue

Stores pending retry attempts.

---

# Main Entities

# 1. Retry Policy

Stores retry configuration.

---

## Retry Policy Fields

| Field                  | Type      |
| ---------------------- | --------- |
| id                     | UUID      |
| business_id            | FK        |
| name                   | String    |
| max_retries            | Integer   |
| retry_interval_minutes | Integer   |
| retry_on_busy          | Boolean   |
| retry_on_no_answer     | Boolean   |
| retry_on_failure       | Boolean   |
| retry_on_rejected      | Boolean   |
| active                 | Boolean   |
| created_at             | Timestamp |

---

# Example Retry Policy

```text id="f2"
Max Retries: 3
Retry Interval: 15 mins
Retry Busy: Yes
Retry No Answer: Yes
Retry Rejected: No
```

---

# 2. Failed Call Record

Stores failed attempt details.

---

## Fields

| Field               | Type      |
| ------------------- | --------- |
| id                  | UUID      |
| call_session_id     | FK        |
| campaign_contact_id | FK        |
| failure_type        | Enum      |
| sip_code            | String    |
| hangup_cause        | String    |
| retry_eligible      | Boolean   |
| retry_count         | Integer   |
| next_retry_at       | Timestamp |
| created_at          | Timestamp |

---

# Failure Types

| Type              | Meaning             |
| ----------------- | ------------------- |
| busy              | line busy           |
| no_answer         | unanswered          |
| rejected          | manually rejected   |
| congestion        | provider congestion |
| network_error     | network issue       |
| invalid_number    | invalid destination |
| trunk_unavailable | SIP trunk offline   |
| timeout           | no SIP response     |
| failed            | generic failure     |

---

# Call Failure Detection Sources

Failures may come from:

* AMI events
* SIP response codes
* hangup causes
* originate responses

---

# Important SIP Codes

| SIP Code | Meaning                 |
| -------- | ----------------------- |
| 486      | Busy Here               |
| 480      | Temporarily Unavailable |
| 404      | Not Found               |
| 503      | Service Unavailable     |
| 408      | Request Timeout         |
| 603      | Declined                |

---

# Retry Decision Engine

# Purpose

Determine whether a failed call should retry.

---

# Decision Flow

```text id="f3"
Call Failed
 ↓
Classify Failure
 ↓
Check Retry Policy
 ↓
Eligible?
 ├─ Yes → Queue Retry
 └─ No → Mark Final Failure
```

---

# Example Retry Decisions

| Failure        | Retry? |
| -------------- | ------ |
| busy           | yes    |
| no_answer      | yes    |
| rejected       | no     |
| invalid_number | no     |
| congestion     | yes    |
| timeout        | yes    |

---

# Retry Queue Architecture

Retries should not happen immediately.

---

# Recommended Flow

```text id="f4"
Failure
 ↓
Retry Queue
 ↓
Scheduled Worker
 ↓
Originate Again
```

---

# Why Delayed Retry Important?

Immediate retry may:

* annoy customers
* trigger provider protections
* fail repeatedly

---

# Retry Scheduling

# Example

```text id="f5"
Attempt 1 → fail
 ↓
Retry after 15 mins
 ↓
Retry after 30 mins
 ↓
Retry after 1 hour
```

---

# Retry Backoff Strategies

# 1. Fixed Retry

```text id="f6"
Every 15 minutes
```

---

# 2. Incremental Retry

```text id="f7"
15m → 30m → 1h
```

---

# 3. Exponential Backoff

```text id="f8"
5m → 10m → 20m → 40m
```

---

# Recommended Initial Strategy

Use:

* fixed retry
  or
* incremental retry

before implementing exponential logic.

---

# Retry Execution Worker

Worker responsibilities:

* fetch pending retries
* validate retry eligibility
* originate new call
* update retry count
* reschedule if needed

---

# Retry State Tracking

# Example Runtime State

| Field         | Value    |
| ------------- | -------- |
| retry_count   | 2        |
| next_retry_at | 10:30 PM |
| last_failure  | busy     |

---

# Campaign Integration

Retry system integrates directly with campaigns.

---

# Example

```text id="f9"
Campaign Contact
 ↓
Call Failed
 ↓
Retry Engine
 ↓
Retry Scheduled
```

---

# Call Attempt Lifecycle

```text id="f10"
Attempt 1
 ↓
Busy
 ↓
Retry Scheduled
 ↓
Attempt 2
 ↓
No Answer
 ↓
Retry Scheduled
 ↓
Attempt 3
 ↓
Answered
```

---

# Retry Termination Conditions

Stop retries when:

* max retries reached
* customer answered
* invalid number detected
* campaign ended
* business manually stopped retry

---

# Example

```text id="f11"
retry_count >= max_retries
```

---

# Final Failure Handling

When retries exhausted:

```text id="f12"
Mark Contact:
FAILED_FINAL
```

---

# Failure Analytics

Track:

* retry success rate
* failure patterns
* SIP issues
* provider reliability

---

# Example Metrics

| Metric                 | Purpose             |
| ---------------------- | ------------------- |
| retry recovery rate    | retry effectiveness |
| most common failure    | provider monitoring |
| avg retries per answer | optimization        |

---

# Smart Retry Possibilities (Future)

Future AI logic may:

* predict best retry times
* analyze answer behavior
* optimize retry windows

---

# Example

```text id="f13"
Customer usually answers after 7PM
```

---

# Time Window Restrictions

Retries should respect:

* business hours
* local timezone
* campaign schedule

---

# Example

```text id="f14"
No retries after 9PM
```

---

# SIP Trunk Protection

Retry engine must respect:

* concurrent channel limits
* CPS limits
* provider policies

---

# Duplicate Protection

Prevent accidental infinite loops.

---

# Example Rule

```text id="f15"
Do not retry same contact more than 3 times in 24h
```

---

# Manual Retry Controls

Businesses may:

* manually retry failed calls
* retry selected contacts
* disable retries

---

# Failure Dashboard

Future dashboard may display:

* failed calls
* retry queue
* retry success rate
* SIP health
* provider errors

---

# Recommended API Endpoints

# Get Failed Calls

```http id="h1"
GET /api/failed-calls
```

---

# Retry Single Contact

```http id="h2"
POST /api/failed-calls/{id}/retry
```

---

# Retry Bulk Contacts

```http id="h3"
POST /api/failed-calls/retry
```

---

# Update Retry Policy

```http id="h4"
PUT /api/retry-policies/{id}
```

---

# Get Retry Queue

```http id="h5"
GET /api/retry-queue
```

---

# Suggested Initial Implementation Order

# Phase 1

Implement:

1. failure tracking
2. retry queue
3. retry worker
4. retry policy

---

# Phase 2

Implement:

1. retry analytics
2. delayed scheduling
3. retry dashboards
4. SIP failure categorization

---

# Phase 3

Implement:

1. predictive retries
2. AI retry optimization
3. adaptive pacing
4. customer behavior analysis

---

# Scalability Considerations

Large retry systems may require:

* distributed workers
* retry partitioning
* delayed job queues
* Redis scheduling

---

# Recommended Stack

```text id="f16"
Flask
 ↓
Redis Queue
 ↓
Retry Scheduler
 ↓
Worker Pool
 ↓
AMI Originate
```

---

# Final Architecture Summary

```text id="f17"
Call Failure
 ↓
Failure Analysis
 ↓
Retry Decision
 ↓
Retry Queue
 ↓
Worker Execution
 ↓
Call Retry
```

---

# Final Runtime Flow

```text id="f18"
Call Attempt
 ↓
Failure Detected
 ↓
Retry Eligibility Check
 ↓
Retry Scheduled
 ↓
Worker Executes Retry
 ↓
Success or Final Failure
```
