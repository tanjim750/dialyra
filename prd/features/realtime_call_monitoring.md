# 15. Real-time Call Monitoring

# Purpose

Real-time Call Monitoring enables live visibility into ongoing calls inside Dialyra.

It allows admins, supervisors, and systems to:

* watch active calls in real time
* track call quality and state
* monitor IVR flow execution
* observe agent performance
* detect failures instantly
* intervene during live calls (future)

---

# Core Goals

## 1. Live Call Visibility

Show all active calls with current state.

---

## 2. Event Streaming

Stream call events instantly from Asterisk + Flow Engine.

---

## 3. Operational Control

Enable supervision and debugging of live flows.

---

## 4. Performance Insights

Track system and agent behavior in real time.

---

# High-Level Architecture

```text id="f1"
Asterisk AMI / ARI Events
 ↓
Event Processor
 ↓
Real-time Stream Layer (WebSocket)
 ↓
Dashboard / API Clients
```

---

# Main Concepts

# 1. Call Session

Represents a single ongoing call lifecycle.

---

# 2. Call Event Stream

Continuous stream of call updates.

---

# 3. Monitoring Channel

WebSocket or SSE channel for live updates.

---

# Main Entities

# 1. Call Session

Tracks each call in system.

---

## Fields

| Field        | Type                    |
| ------------ | ----------------------- |
| id           | UUID                    |
| business_id  | FK                      |
| phone_number | String                  |
| direction    | Enum (inbound/outbound) |
| status       | Enum                    |
| flow_id      | FK                      |
| agent_id     | FK                      |
| start_time   | Timestamp               |
| end_time     | Timestamp               |
| duration     | Integer                 |
| current_node | String                  |

---

# Call Status Types

| Status      | Meaning       |
| ----------- | ------------- |
| initiated   | call started  |
| ringing     | dialing       |
| answered    | connected     |
| in_flow     | IVR running   |
| queued      | waiting agent |
| transferred | agent handoff |
| completed   | finished      |
| failed      | error         |

---

# 2. Call Event

Represents each real-time update.

---

## Fields

| Field           | Type      |
| --------------- | --------- |
| id              | UUID      |
| call_session_id | FK        |
| event_type      | String    |
| payload         | JSON      |
| timestamp       | Timestamp |

---

# Event Types

| Event             | Meaning       |
| ----------------- | ------------- |
| call.initiated    | call started  |
| call.ringing      | dialing       |
| call.answered     | connected     |
| flow.node_entered | IVR step      |
| dtmf.received     | user input    |
| audio.playing     | playback      |
| agent.connected   | human joined  |
| call.ended        | call finished |

---

# Real-Time Streaming Architecture

## Event Flow

```text id="f2"
Asterisk AMI Events
 ↓
Event Normalizer
 ↓
Call Session Updater
 ↓
WebSocket Broadcaster
 ↓
Dashboard UI
```

---

# Real-Time Transport Methods

## 1. WebSocket (Recommended)

* full duplex
* low latency
* real-time updates

---

## 2. Server-Sent Events (SSE)

* simpler alternative
* one-way stream

---

## 3. Polling (Fallback)

* not recommended for production

---

# Live Monitoring Dashboard Features

## 1. Active Calls View

Shows:

* live calls
* duration
* status
* assigned flow

---

## 2. Call Timeline

Step-by-step execution view:

```text id="f3"
Start → IVR → DTMF → Transfer → End
```

---

## 3. Flow Execution Viewer

Shows current node execution in real time.

---

## 4. Agent Monitoring Panel

Shows:

* agent status
* active calls
* load

---

# Call Timeline Structure

```text id="f4"
[00:00] Call Initiated
[00:02] Ringing
[00:05] Answered
[00:06] Flow Node A
[00:12] DTMF Received
[00:15] Agent Transfer
[01:05] Call Ended
```

---

# AMI Integration Layer

Real-time monitoring relies heavily on AMI events:

* NewChannel
* Hangup
* Dial
* Bridge
* DTMF
* UserEvent

---

# Event Processing Pipeline

```text id="f5"
AMI Event
 ↓
Parser
 ↓
Normalize Event
 ↓
Update Call Session
 ↓
Emit WebSocket Event
```

---

# Flow Engine Integration

Monitoring tracks:

* current flow node
* transitions
* conditional branches
* failures

---

# Example Flow Tracking

```text id="f6"
Welcome Node
 ↓
Language Selection
 ↓
Agent Transfer
```

---

# Performance Metrics (Real-Time)

## Call-Level Metrics

* latency per node
* IVR duration
* hold time
* transfer time

---

## System Metrics

* active calls count
* AMI event rate
* websocket connections
* queue depth

---

# Live Event Payload Example

```json id="j1"
{
  "event": "dtmf.received",
  "call_id": "abc123",
  "digit": "1",
  "timestamp": "2026-05-05T12:10:00Z"
}
```

---

# Monitoring Use Cases

## 1. Debugging Flows

Track exactly where call failed.

---

## 2. Customer Support

See live call state when user reports issue.

---

## 3. Campaign Tracking

Monitor outbound campaign performance.

---

## 4. Agent Supervision

Track agent behavior in real time.

---

# Call Interception (Future Feature)

Supervisor can:

* listen live
* whisper to agent
* join call

---

# Event Ordering System

Ensure:

* correct sequence
* no duplicate events
* consistent state updates

---

# Example Ordering Fix

```text id="f7"
DTMF before Answer → corrected by timestamp ordering
```

---

# Failure Handling

Handle:

* missing AMI events
* dropped WebSocket connections
* partial call state updates

---

# Recovery Strategy

On reconnect:

* rebuild session state
* replay last known events

---

# Security Considerations

## 1. Business Isolation

Only show calls for same business.

---

## 2. Authenticated Streams

WebSocket requires token auth.

---

## 3. Sensitive Data Masking

Hide:

* full phone numbers (optional)
* call recordings access

---

# Scalability Considerations

Large systems require:

* event queue (Redis/Kafka)
* horizontal websocket scaling
* AMI load balancing
* distributed session store

---

# Recommended Architecture

```text id="f8"
Asterisk AMI
 ↓
Event Broker (Redis/Kafka)
 ↓
Call Processor Workers
 ↓
WebSocket Gateway
 ↓
Dashboard Clients
```

---

# Suggested Implementation Order

## Phase 1

1. call session model
2. AMI event listener
3. basic websocket stream
4. live call list

---

## Phase 2

1. flow node tracking
2. event timeline
3. agent monitoring
4. retry recovery

---

## Phase 3

1. call interception tools
2. analytics engine
3. distributed scaling
4. AI-based anomaly detection

---

# Final Architecture Summary

```text id="f9"
Asterisk Events
 ↓
Event Processor
 ↓
Call State Store
 ↓
Real-time Stream
 ↓
Monitoring Dashboard
```

---

# Final Runtime Flow

```text id="f10"
Call Starts
 ↓
Events Generated
 ↓
System Updates State
 ↓
UI Updates Instantly
 ↓
Call Ends
 ↓
Final Metrics Stored
```
