# 9. Call Session & Event Tracking

# Purpose

Call Session & Event Tracking is responsible for monitoring, storing, and analyzing everything that happens during a phone call lifecycle.

This system acts as the observability and runtime intelligence layer of Dialyra.

It tracks:

* call states
* flow execution
* DTMF interactions
* playback events
* transfers
* failures
* call duration
* business analytics

---

# Core Goals

## 1. Full Call Lifecycle Tracking

Track the entire call journey from originate to hangup.

---

## 2. Runtime Flow Visibility

Understand:

* which nodes executed
* customer interactions
* branch decisions

---

## 3. Business Analytics

Provide:

* reports
* call insights
* performance monitoring

---

## 4. Debugging & Reliability

Help diagnose:

* failed flows
* playback errors
* SIP issues
* timeout loops

---

# High-Level Architecture

```text id="f1"
Asterisk Events
 ↓
AMI / FastAGI
 ↓
Event Collector
 ↓
PostgreSQL + Redis
 ↓
Analytics & Monitoring
```

---

# Core Concepts

# 1. Call Session

Represents a single phone call lifecycle.

---

# 2. Event

Represents an action or state change during the call.

---

# Main Entities

# 1. Call Session

Tracks high-level call information.

---

## Call Session Fields

| Field              | Type      |
| ------------------ | --------- |
| id                 | UUID      |
| business_id        | FK        |
| flow_id            | FK        |
| sip_trunk_id       | FK        |
| caller_number      | String    |
| destination_number | String    |
| call_direction     | Enum      |
| call_status        | Enum      |
| asterisk_channel   | String    |
| uniqueid           | String    |
| linkedid           | String    |
| started_at         | Timestamp |
| answered_at        | Timestamp |
| ended_at           | Timestamp |
| duration_seconds   | Integer   |
| bill_seconds       | Integer   |
| hangup_cause       | String    |
| created_at         | Timestamp |

---

# Call Status Types

| Status      | Meaning             |
| ----------- | ------------------- |
| initiated   | originate requested |
| ringing     | destination ringing |
| answered    | call answered       |
| in_progress | active flow running |
| completed   | normal completion   |
| failed      | failure             |
| busy        | destination busy    |
| no_answer   | unanswered          |
| cancelled   | manually cancelled  |

---

# 2. Call Event

Tracks detailed runtime actions.

---

## Call Event Fields

| Field           | Type      |
| --------------- | --------- |
| id              | UUID      |
| call_session_id | FK        |
| event_type      | Enum      |
| node_id         | FK        |
| event_data      | JSON      |
| created_at      | Timestamp |

---

# Why Event-Based Architecture?

Because calls are sequential runtime processes.

Events allow:

* replaying call history
* debugging
* analytics
* runtime monitoring

---

# Core Event Types

# Telephony Events

| Event          | Purpose           |
| -------------- | ----------------- |
| call_initiated | originate started |
| call_ringing   | ringing detected  |
| call_answered  | answered          |
| call_hangup    | call ended        |
| call_failed    | failure           |

---

# Flow Events

| Event          | Purpose        |
| -------------- | -------------- |
| flow_started   | flow execution |
| node_entered   | node traversal |
| node_completed | node finished  |
| flow_completed | flow finished  |

---

# Audio Events

| Event                | Purpose             |
| -------------------- | ------------------- |
| playback_started     | audio start         |
| playback_completed   | audio finished      |
| playback_interrupted | interrupted by DTMF |
| playback_failed      | playback issue      |

---

# DTMF Events

| Event         | Purpose         |
| ------------- | --------------- |
| dtmf_received | input captured  |
| dtmf_invalid  | invalid digit   |
| dtmf_timeout  | no input        |
| dtmf_retry    | retry triggered |

---

# Transfer Events

| Event              | Purpose            |
| ------------------ | ------------------ |
| transfer_started   | transfer initiated |
| transfer_completed | transfer success   |
| transfer_failed    | transfer failure   |

---

# Runtime Call Lifecycle

# Step 1 — Originate Request

```text id="f2"
API Request
 ↓
AMI Originate
```

---

# Step 2 — Call Session Created

Initial DB session created.

---

# Step 3 — Asterisk Events Start

AMI events begin streaming.

---

# Step 4 — Runtime Flow Executes

Flow engine processes nodes.

---

# Step 5 — Events Logged Continuously

Playback, DTMF, conditions, transfers.

---

# Step 6 — Call Ends

Session finalized.

---

# Example Runtime Event Flow

```text id="f3"
call_initiated
 ↓
call_ringing
 ↓
call_answered
 ↓
playback_started
 ↓
dtmf_received
 ↓
node_completed
 ↓
call_hangup
```

---

# AMI Integration

# Why AMI Important?

AMI provides:

* real-time telephony events
* channel monitoring
* hangup tracking
* bridge events
* state changes

---

# Important AMI Events

| AMI Event   | Purpose          |
| ----------- | ---------------- |
| Newchannel  | channel created  |
| DialBegin   | outbound started |
| DialEnd     | dial result      |
| BridgeEnter | call connected   |
| Hangup      | call ended       |
| DTMFBegin   | input started    |
| DTMFEnd     | input completed  |

---

# Recommended Event Processing Architecture

```text id="f4"
AMI Listener
 ↓
Event Parser
 ↓
Redis Queue
 ↓
Worker
 ↓
Database Storage
```

---

# Why Queue-Based Processing?

Because high call concurrency can generate huge event volumes.

---

# Redis Usage

Redis should store:

* active sessions
* runtime state
* temporary events
* retry counters

---

# PostgreSQL Usage

PostgreSQL should store:

* permanent history
* analytics data
* reporting data

---

# Runtime Session State

Each active call should maintain runtime memory.

---

# Example Runtime State

| Key           | Value        |
| ------------- | ------------ |
| current_node  | gather_input |
| retry_count   | 2            |
| current_audio | menu.wav     |
| dtmf_buffer   | 12           |

---

# Flow Tracking

Every node execution should be tracked.

---

# Example

```text id="f5"
Node Entered:
gather_input

Node Completed:
valid_input_received
```

---

# Why Important?

Enables:

* debugging
* replay
* analytics
* optimization

---

# Call Recording Tracking

Optional future feature.

---

## Track

| Field              | Purpose   |
| ------------------ | --------- |
| recording_path     | file path |
| recording_duration | duration  |
| recording_status   | state     |

---

# Analytics Possibilities

# Business Metrics

| Metric           | Example |
| ---------------- | ------- |
| total calls      | 500/day |
| answer rate      | 72%     |
| timeout rate     | 15%     |
| average duration | 45 sec  |

---

# Flow Metrics

| Metric             | Purpose      |
| ------------------ | ------------ |
| most selected menu | optimization |
| abandonment node   | UX analysis  |
| retry-heavy nodes  | redesign     |

---

# Error Monitoring

Track:

* failed playback
* SIP errors
* transfer failures
* flow crashes

---

# Example Failure Event

```json id="j1"
{
  "event": "playback_failed",
  "reason": "missing_audio_file"
}
```

---

# Recommended Logging Strategy

# Structured Logging

Use JSON-based logs.

---

# Example

```json id="j2"
{
  "call_id": "abc123",
  "event": "dtmf_received",
  "digit": "1",
  "timestamp": "2026-05-05T12:00:00Z"
}
```

---

# Event Replay Capability

Future enhancement:

```text id="f6"
Replay entire call timeline
```

for debugging.

---

# Monitoring Dashboard Possibilities

Future dashboard may show:

* active calls
* live node execution
* flow traversal
* DTMF activity
* call heatmaps

---

# Recommended API Endpoints

# Get Call Sessions

```http id="h1"
GET /api/call-sessions
```

---

# Get Single Call Session

```http id="h2"
GET /api/call-sessions/{id}
```

---

# Get Call Events

```http id="h3"
GET /api/call-sessions/{id}/events
```

---

# Get Live Call State

```http id="h4"
GET /api/live-calls
```

---

# Suggested Initial Implementation Order

# Phase 1

Implement:

1. call session model
2. AMI event listener
3. basic event storage
4. call lifecycle tracking

---

# Phase 2

Implement:

1. flow node tracking
2. DTMF logging
3. playback tracking
4. Redis runtime state

---

# Phase 3

Implement:

1. live dashboards
2. event replay
3. advanced analytics
4. anomaly detection

---

# Scalability Considerations

# Event Volume

Large deployments may generate:

```text id="f7"
millions of events/day
```

---

# Recommended Optimizations

* batch inserts
* async workers
* event partitioning
* Redis buffering

---

# Final Architecture Summary

```text id="f8"
Asterisk
 ↓
AMI Events
 ↓
Event Collector
 ↓
Redis Queue
 ↓
PostgreSQL
 ↓
Analytics
```

---

# Final Runtime Flow

```text id="f9"
Call Starts
 ↓
Events Generated
 ↓
Runtime Tracking
 ↓
Flow Monitoring
 ↓
Call Ends
 ↓
Analytics Stored
```
