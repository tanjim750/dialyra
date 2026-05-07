# 20. Scheduler & Automated Calling System

# Purpose

Scheduler & Automated Calling System enables Dialyra to run time-based and event-based outbound call automation at scale.

It allows businesses to:

* schedule calls in future
* run recurring campaigns
* trigger bulk calling jobs
* automate reminders (payment, appointment, alerts)
* integrate scheduling with flow engine + AMI

---

# Core Goals

## 1. Time-Based Call Execution

Execute calls at a specific time or schedule.

---

## 2. Recurring Automation

Support repeated calling patterns.

---

## 3. Scalable Bulk Dialing

Handle large outbound campaigns safely.

---

## 4. Reliable Execution Guarantees

Ensure no scheduled call is lost or duplicated.

---

# High-Level Architecture

```text id="f1"
Scheduler Engine
 ↓
Job Queue (Redis / Celery)
 ↓
Call Dispatcher
 ↓
AMI Originate System
 ↓
Flow Engine Execution
```

---

# Main Concepts

# 1. Schedule Job

Represents a future or recurring call task.

---

# 2. Job Worker

Background processor that executes scheduled tasks.

---

# 3. Call Task

Individual call instance created from a schedule.

---

# Main Entities

# 1. Schedule

Stores scheduling rules.

---

## Fields

| Field           | Type      |
| --------------- | --------- |
| id              | UUID      |
| business_id     | FK        |
| name            | String    |
| type            | Enum      |
| start_time      | Timestamp |
| timezone        | String    |
| recurrence_rule | String    |
| flow_id         | FK        |
| campaign_id     | FK        |
| status          | Enum      |
| created_at      | Timestamp |

---

# Schedule Types

| Type      | Meaning            |
| --------- | ------------------ |
| one_time  | single execution   |
| recurring | repeated schedule  |
| campaign  | bulk calling batch |

---

# 2. Schedule Task

Represents individual execution unit.

---

## Fields

| Field           | Type      |
| --------------- | --------- |
| id              | UUID      |
| schedule_id     | FK        |
| phone_number    | String    |
| status          | Enum      |
| retry_count     | Integer   |
| next_attempt_at | Timestamp |
| call_session_id | FK        |

---

# Task Status Types

| Status   | Meaning            |
| -------- | ------------------ |
| pending  | waiting execution  |
| queued   | in execution queue |
| running  | call started       |
| success  | completed          |
| failed   | failed             |
| retrying | retry scheduled    |

---

# Scheduler Architecture

## Core Components

* Scheduler Engine
* Job Queue
* Worker Pool
* Call Dispatcher
* AMI Integration Layer

---

# Execution Flow

```text id="f2"
Schedule Trigger Time
 ↓
Scheduler Engine
 ↓
Create Call Tasks
 ↓
Push to Queue
 ↓
Worker Picks Task
 ↓
AMI Originate Call
 ↓
Flow Execution Starts
```

---

# Recurring Scheduling

Uses cron-like rules.

---

## Example Rules

| Rule            | Meaning        |
| --------------- | -------------- |
| daily 10:00     | every day      |
| weekly mon 9:00 | weekly         |
| every 5 min     | interval-based |

---

# Cron Expression Example

```text id="f3"
0 10 * * *
```

---

# Bulk Calling System

Used for:

* marketing campaigns
* reminders
* notifications

---

## Execution Flow

```text id="f4"
Campaign Created
 ↓
Generate Call List
 ↓
Queue Tasks
 ↓
Rate-Limited Execution
 ↓
Dial via AMI
```

---

# Rate Limiting System

Prevents overload:

---

## Limits

| Scope        | Limit        |
| ------------ | ------------ |
| per second   | 5–20 calls   |
| per trunk    | max capacity |
| per business | quota-based  |

---

# Retry Mechanism

Handles failed calls automatically.

---

## Retry Flow

```text id="f5"
Call Failed
 ↓
Retry Policy Check
 ↓
Wait Backoff Time
 ↓
Requeue Call
```

---

## Retry Policy Example

| Attempt | Delay  |
| ------- | ------ |
| 1       | 1 min  |
| 2       | 5 min  |
| 3       | 15 min |
| 4       | stop   |

---

# AMI Integration

Scheduler triggers AMI originate actions.

---

## Example Flow

```text id="f6"
Scheduler → AMI Service → Asterisk → Dial → Flow Engine
```

---

# Call Origination Context

Each scheduled call includes:

* phone number
* flow ID
* campaign ID
* metadata

---

# Flow Integration

Scheduled calls automatically enter Flow Engine.

---

## Example

```text id="f7"
Schedule → Call → IVR Flow → Agent Transfer
```

---

# Failure Handling

Handle:

* AMI failure
* trunk busy
* no agent available
* system overload

---

# Failure Flow

```text id="f8"
Task Failed
 ↓
Retry or mark failed
 ↓
Log error
```

---

# Dead Letter Queue (DLQ)

Stores permanently failed tasks.

---

# Example

```text id="f9"
Task failed after max retries → DLQ
```

---

# Concurrency Control

Scheduler respects:

* agent availability
* trunk capacity
* system load

---

# Example Control

```text id="f10"
Do not exceed 50 concurrent calls
```

---

# Job Worker Architecture

Workers execute scheduled tasks:

* stateless
* horizontally scalable
* queue-based processing

---

# Recommended Stack

* Redis Queue / Celery
* Flask FastAPI workers
* Asterisk AMI bridge

---

# Event Tracking

Each scheduled call emits events:

| Event            | Meaning        |
| ---------------- | -------------- |
| schedule.created | schedule added |
| task.queued      | call queued    |
| call.started     | dial initiated |
| call.completed   | finished       |
| call.failed      | failed         |

---

# Analytics Integration

Scheduler feeds data into:

* campaign analytics
* call success rate
* retry effectiveness

---

# Example Metrics

* scheduled calls executed
* success rate
* retry rate
* average delay

---

# Security Considerations

* business-level isolation
* schedule validation
* API authentication
* rate-limited scheduling API

---

# Example Abuse Prevention

```text id="f11"
Block > 1000 calls/min per business
```

---

# Scalability Design

For large systems:

* distributed scheduler
* queue sharding
* worker autoscaling
* regional Asterisk clusters

---

# Recommended Architecture

```text id="f12"
Scheduler Engine
 ↓
Queue System (Redis/Kafka)
 ↓
Worker Cluster
 ↓
AMI Dispatcher
 ↓
Asterisk Nodes
```

---

# Suggested Implementation Order

## Phase 1

1. basic scheduler model
2. one-time job execution
3. AMI integration
4. task queue system

---

## Phase 2

1. recurring schedules
2. retry system
3. campaign bulk calling
4. rate limiting

---

## Phase 3

1. distributed scheduling
2. multi-region execution
3. predictive scheduling
4. AI-driven optimization

---

# Final Architecture Summary

```text id="f13"
Schedules
 ↓
Scheduler Engine
 ↓
Task Queue
 ↓
Workers
 ↓
AMI Originate
 ↓
Call Flow Execution
```

---

# Final Runtime Flow

```text id="f14"
Schedule Triggered
 ↓
Tasks Generated
 ↓
Queued for Execution
 ↓
Worker Picks Task
 ↓
Call Initiated
 ↓
Flow Engine Runs
 ↓
Call Completed
```
