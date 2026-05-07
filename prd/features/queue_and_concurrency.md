# 17. Queue & Concurrent Call Handling

# Purpose

Queue & Concurrent Call Handling enables Dialyra to manage high call volume efficiently by distributing calls across available resources (agents, SIP trunks, system capacity) without dropping or blocking users.

It ensures:

* no call overload on agents
* controlled concurrency per business/trunk
* fair call distribution
* smooth IVR → agent transitions
* scalable outbound campaigns

---

# Core Goals

## 1. Call Queue Management

Hold calls when no resources are available.

---

## 2. Concurrency Control

Limit:

* simultaneous calls per agent
* simultaneous calls per trunk
* system-wide call capacity

---

## 3. Fair Distribution

Ensure calls are distributed evenly or by rules.

---

## 4. Load Protection

Prevent:

* SIP trunk overload
* Asterisk saturation
* agent overbooking

---

# High-Level Architecture

```text id="f1"
Inbound/Outbound Call
 ↓
Queue Manager
 ↓
Concurrency Controller
 ↓
Routing Engine
 ↓
Agent / SIP Trunk
```

---

# Main Concepts

# 1. Call Queue

Temporary holding system for calls waiting to be processed.

---

# 2. Concurrency Slot

Represents a “live call capacity unit”.

---

# 3. Dispatcher

Component that assigns calls to available resources.

---

# Main Entities

# 1. Queue

Represents a call holding structure.

---

## Fields

| Field          | Type      |
| -------------- | --------- |
| id             | UUID      |
| business_id    | FK        |
| name           | String    |
| strategy       | Enum      |
| max_wait_time  | Integer   |
| timeout_action | Enum      |
| created_at     | Timestamp |

---

# Queue Strategies

| Strategy    | Meaning                |
| ----------- | ---------------------- |
| FIFO        | first come first serve |
| round_robin | equal distribution     |
| least_busy  | least loaded agent     |
| priority    | VIP first              |
| skill_based | matching skills        |

---

# 2. Queue Entry

Represents a waiting call.

---

## Fields

| Field           | Type      |
| --------------- | --------- |
| id              | UUID      |
| queue_id        | FK        |
| call_session_id | FK        |
| priority        | Integer   |
| status          | Enum      |
| entered_at      | Timestamp |
| assigned_at     | Timestamp |

---

# Queue Status Types

| Status    | Meaning       |
| --------- | ------------- |
| waiting   | in queue      |
| assigned  | sent to agent |
| expired   | timeout       |
| abandoned | caller left   |

---

# 3. Concurrency Slot

Represents active capacity unit.

---

## Fields

| Field         | Type                      |
| ------------- | ------------------------- |
| id            | UUID                      |
| business_id   | FK                        |
| type          | Enum (agent/trunk/system) |
| reference_id  | String                    |
| max_limit     | Integer                   |
| current_usage | Integer                   |

---

# Concurrency Types

| Type   | Description        |
| ------ | ------------------ |
| agent  | per agent calls    |
| trunk  | SIP trunk capacity |
| system | global limit       |

---

# Queue Flow Architecture

```text id="f2"
Call Arrives
 ↓
Check Capacity
 ↓
If Available → Direct Call
Else → Queue Call
 ↓
Wait for Slot
 ↓
Assign When Free
```

---

# Concurrency Control Flow

```text id="f3"
New Call Request
 ↓
Check System Limit
 ↓
Check Trunk Limit
 ↓
Check Agent Limit
 ↓
Allow or Queue
```

---

# Agent Allocation Logic

## Step 1 — Find Available Agents

```text id="f4"
agent.status == available
AND concurrency < limit
```

---

## Step 2 — Apply Strategy

* least busy
* round robin
* priority

---

## Step 3 — Assign Call

Update:

* agent usage count
* call session state

---

# SIP Trunk Concurrency Handling

Each trunk has:

* max simultaneous calls
* rate limit per second

---

## Example

```text id="f5"
Trunk A:
Max Calls = 50
Current = 48
→ Allow 2 more calls only
```

---

# Queue Waiting Flow

```text id="f6"
No Agent Available
 ↓
Place in Queue
 ↓
Play Hold Audio
 ↓
Check Every Few Seconds
 ↓
Assign When Free
```

---

# Hold Experience

While waiting:

* hold music
* position announcement
* estimated wait time

---

# Example Message

```text id="f7"
"You are number 3 in queue"
```

---

# Timeout Handling

If wait exceeds limit:

```text id="f8"
Timeout → fallback action
```

---

## Timeout Actions

| Action      | Meaning           |
| ----------- | ----------------- |
| retry_queue | requeue call      |
| voicemail   | leave message     |
| callback    | schedule callback |
| hangup      | end call          |

---

# Load Balancing Strategy

## 1. Round Robin

Even distribution across agents.

---

## 2. Least Busy

Select agent with lowest active calls.

---

## 3. Weighted Routing

Priority-based allocation.

---

# Concurrent Outbound Calls

Used in campaigns.

---

## Control Rules

* per campaign limit
* per trunk limit
* per business limit

---

# Example

```text id="f9"
Campaign:
Max 100 concurrent calls
Trunk limit reached → pause dialing
```

---

# Queue Rebalancing

System periodically:

* redistributes waiting calls
* assigns freed agents
* updates queue positions

---

# Real-Time Queue State

```text id="f10"
Queue Snapshot:
- waiting: 12
- active agents: 5
- avg wait: 32s
```

---

# Event Flow Integration

Queue system emits events:

| Event           | Description       |
| --------------- | ----------------- |
| queue.entered   | call joined queue |
| queue.assigned  | assigned to agent |
| queue.abandoned | caller left       |
| queue.timeout   | expired           |

---

# Concurrency Lock System

Prevents race conditions:

* atomic slot allocation
* distributed locking (Redis)

---

# Failure Handling

Handle:

* agent disconnect
* trunk failure
* queue overflow
* system overload

---

# Overflow Strategy

When queue is full:

| Action         | Result         |
| -------------- | -------------- |
| reject         | drop call      |
| overflow_queue | move to backup |
| callback       | schedule later |

---

# Scalability Considerations

For large scale systems:

* distributed queue workers
* Redis-based counters
* horizontal scaling of dispatcher
* stateless routing engine

---

# Recommended Architecture

```text id="f11"
Call Intake
 ↓
Queue Service
 ↓
Concurrency Manager (Redis)
 ↓
Routing Engine
 ↓
Asterisk / Agents
```

---

# Suggested Implementation Order

## Phase 1

1. basic queue system
2. FIFO logic
3. agent assignment
4. concurrency counter

---

## Phase 2

1. retry logic
2. hold music system
3. trunk limits
4. event tracking

---

## Phase 3

1. distributed queue system
2. weighted routing
3. real-time dashboard
4. AI-based load prediction

---

# Final Architecture Summary

```text id="f12"
Incoming Call
 ↓
Queue Manager
 ↓
Concurrency Controller
 ↓
Routing Engine
 ↓
Agent / SIP Trunk
```

---

# Final Runtime Flow

```text id="f13"
Call Arrives
 ↓
Check Capacity
 ↓
If Busy → Queue
 ↓
Wait
 ↓
Assign Agent/Trunk
 ↓
Call Connected
```
