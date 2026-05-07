# 12. Agent Call Transfer

# Purpose

Agent Call Transfer enables Dialyra to transfer live calls from automated IVR flows to human agents when necessary.

This feature bridges automation and human support.

It allows businesses to:

* escalate customer calls
* provide live support
* handle complex situations
* improve customer satisfaction
* combine IVR automation with call center operations

---

# Core Goals

## 1. Seamless Human Escalation

Transfer callers from automated flows to live agents.

---

## 2. Dynamic Agent Routing

Route calls based on:

* department
* language
* priority
* availability
* skill group

---

## 3. Queue & Availability Management

Handle:

* busy agents
* offline agents
* waiting queues

---

## 4. Runtime Transfer Control

Allow transfers dynamically during flow execution.

---

# High-Level Architecture

```text id="f1"
Caller
 ↓
Flow Engine
 ↓
Transfer Node
 ↓
Agent Router
 ↓
Queue / Agent
 ↓
Bridge Call
```

---

# Main Concepts

# 1. Agent

Represents a human support operator.

---

# 2. Queue

Represents a waiting group for agents.

---

# 3. Transfer Session

Represents the live transfer operation.

---

# Main Entities

# 1. Agent

Stores agent information.

---

## Agent Fields

| Field                | Type      |
| -------------------- | --------- |
| id                   | UUID      |
| business_id          | FK        |
| name                 | String    |
| extension            | String    |
| sip_username         | String    |
| status               | Enum      |
| max_concurrent_calls | Integer   |
| department_id        | FK        |
| created_at           | Timestamp |

---

# Agent Status Types

| Status    | Meaning                 |
| --------- | ----------------------- |
| available | ready                   |
| busy      | active call             |
| offline   | disconnected            |
| paused    | temporarily unavailable |

---

# 2. Agent Queue

Represents support queues.

---

## Queue Fields

| Field            | Type      |
| ---------------- | --------- |
| id               | UUID      |
| business_id      | FK        |
| name             | String    |
| routing_strategy | Enum      |
| max_wait_time    | Integer   |
| overflow_action  | Enum      |
| created_at       | Timestamp |

---

# Queue Routing Strategies

| Strategy       | Purpose           |
| -------------- | ----------------- |
| round_robin    | fair distribution |
| least_calls    | load balancing    |
| random         | random assignment |
| skill_based    | expertise routing |
| priority_based | VIP handling      |

---

# 3. Queue Agent Mapping

Links agents to queues.

---

## Fields

| Field    | Type    |
| -------- | ------- |
| id       | UUID    |
| queue_id | FK      |
| agent_id | FK      |
| priority | Integer |
| active   | Boolean |

---

# 4. Transfer Session

Tracks transfer operations.

---

## Fields

| Field           | Type      |
| --------------- | --------- |
| id              | UUID      |
| call_session_id | FK        |
| queue_id        | FK        |
| agent_id        | FK        |
| transfer_status | Enum      |
| started_at      | Timestamp |
| connected_at    | Timestamp |
| ended_at        | Timestamp |

---

# Transfer Status Types

| Status    | Meaning          |
| --------- | ---------------- |
| initiated | transfer started |
| queued    | waiting          |
| ringing   | agent ringing    |
| connected | bridged          |
| failed    | failed           |
| abandoned | caller hung up   |

---

# Runtime Transfer Flow

# Step 1 — Caller Enters Flow

Customer interacts with IVR.

---

# Step 2 — Transfer Node Triggered

Flow decides:

* transfer required
  or
* user requested agent

---

# Step 3 — Agent Routing

System selects available agent.

---

# Step 4 — Queue Handling

If no agent available:

* queue caller
* play hold music
* estimate wait time

---

# Step 5 — Agent Answers

Asterisk bridges both channels.

---

# Step 6 — Call Monitoring

Track:

* duration
* wait time
* transfer outcome

---

# Transfer Trigger Methods

# 1. DTMF Request

Example:

```text id="f2"
Press 0 to talk to an agent
```

---

# 2. Conditional Logic

Example:

```text id="f3"
High-value customer → transfer
```

---

# 3. Failure Escalation

Example:

```text id="f4"
3 invalid attempts → transfer
```

---

# 4. AI Intent Detection (Future)

Example:

```text id="f5"
Customer sounds frustrated
```

---

# Queue Handling Flow

```text id="f6"
Transfer Request
 ↓
Find Available Agent
 ├─ Available → Ring Agent
 └─ Not Available → Queue Caller
```

---

# Hold Queue Features

# Queue Playback

While waiting:

* hold music
* queue announcements
* estimated wait time

---

# Example

```text id="f7"
"All agents are busy. Please wait."
```

---

# Queue Timeout

If waiting too long:

```text id="f8"
Queue Timeout
 ↓
Fallback Action
```

---

# Fallback Actions

| Action           | Purpose         |
| ---------------- | --------------- |
| voicemail        | leave message   |
| callback_request | future callback |
| disconnect       | end call        |
| retry_queue      | retry later     |

---

# Agent Selection Logic

# Example Round Robin

```text id="f9"
Agent A
 ↓
Agent B
 ↓
Agent C
```

---

# Example Least Calls

```text id="f10"
Choose agent with lowest active calls
```

---

# Skill-Based Routing

Future enhancement.

---

# Example

```text id="f11"
Bangla callers → Bangla agents
```

---

# SIP Extension Architecture

Agents may connect using:

* softphones
* WebRTC
* SIP desk phones

---

# Example SIP Extension

```text id="f12"
PJSIP/1001
```

---

# Asterisk Bridging

When agent answers:

```text id="f13"
Caller Channel
 ↔
Bridge
 ↔
Agent Channel
```

---

# Transfer Monitoring

Track:

* wait duration
* answer duration
* transfer failures
* abandoned queues

---

# Agent Presence Tracking

Track real-time:

* online
* offline
* active call state

using:

* AMI events
* SIP registration state

---

# Queue Metrics

| Metric            | Purpose           |
| ----------------- | ----------------- |
| avg wait time     | support quality   |
| abandoned calls   | queue performance |
| agent utilization | staffing analysis |

---

# Call Recording Support

Optional future feature.

---

# Recording Possibilities

* caller + agent conversation
* QA monitoring
* dispute handling

---

# Whisper & Coaching (Future)

Advanced call center features.

---

# Example

```text id="f14"
Supervisor whispers to agent only
```

---

# Security Considerations

# 1. Business Isolation

Agents belong only to their business.

---

# 2. Queue Permissions

Restrict access to departments.

---

# 3. SIP Authentication

Secure agent extensions.

---

# 4. Transfer Authorization

Only valid flows can initiate transfers.

---

# Failure Handling

Handle:

* agent unavailable
* queue timeout
* SIP disconnect
* bridge failure

---

# Example Failure Flow

```text id="f15"
Agent Did Not Answer
 ↓
Retry Another Agent
```

---

# Recommended API Endpoints

# Create Agent

```http id="h1"
POST /api/agents
```

---

# Create Queue

```http id="h2"
POST /api/queues
```

---

# Assign Agent To Queue

```http id="h3"
POST /api/queues/{id}/agents
```

---

# Get Live Queue State

```http id="h4"
GET /api/queues/live
```

---

# Get Agent Status

```http id="h5"
GET /api/agents/status
```

---

# Suggested Initial Implementation Order

# Phase 1

Implement:

1. agent model
2. queue model
3. basic transfer node
4. SIP extension dialing

---

# Phase 2

Implement:

1. queue waiting
2. hold playback
3. routing strategies
4. agent presence tracking

---

# Phase 3

Implement:

1. skill routing
2. WebRTC agents
3. supervisor monitoring
4. AI-assisted routing

---

# Scalability Considerations

Large deployments may require:

* distributed queue workers
* dedicated media servers
* SIP load balancing
* multi-region routing

---

# Recommended Runtime Architecture

```text id="f16"
Flow Engine
 ↓
Transfer Service
 ↓
Queue Engine
 ↓
Agent Router
 ↓
Asterisk Bridge
```

---

# Final Architecture Summary

```text id="f17"
Caller
 ↓
Flow Engine
 ↓
Transfer Node
 ↓
Queue
 ↓
Agent
 ↓
Bridged Conversation
```

---

# Final Runtime Flow

```text id="f18"
Customer Requests Agent
 ↓
Queue Assignment
 ↓
Agent Rings
 ↓
Agent Answers
 ↓
Call Bridged
 ↓
Conversation Ends
```
