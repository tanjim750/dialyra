# 18. FastAGI Runtime Execution

# Purpose

FastAGI Runtime Execution enables Dialyra to execute real-time call logic externally (Flask/Python service) while Asterisk handles media transport.

It acts as a bridge between:

* Asterisk dialplan
* external Python logic engine
* dynamic IVR / AI / business workflows

---

# Core Goals

## 1. Externalized Call Logic

Move IVR logic outside Asterisk dialplan.

---

## 2. Low-Latency Execution

Ensure near real-time response for call flows.

---

## 3. Dynamic Flow Control

Allow runtime decisions during calls:

* play audio
* collect DTMF
* route calls
* trigger APIs

---

## 4. Scalable Call Processing

Decouple Asterisk from business logic.

---

# High-Level Architecture

```text id="f1"
Asterisk Dialplan
 ↓
FastAGI Request
 ↓
Flask FastAGI Server
 ↓
Flow Engine / Logic Layer
 ↓
Response to Asterisk
```

---

# What is FastAGI?

FastAGI = TCP-based protocol where Asterisk:

* sends call metadata
* waits for response
* executes instructions dynamically

---

# Core Concepts

# 1. AGI Request

Asterisk sends call context.

---

# 2. AGI Server

Your Flask app handles request.

---

# 3. AGI Response

Instructions returned to Asterisk.

---

# Execution Flow

```text id="f2"
Call Hits Dialplan
 ↓
AGI Script Triggered
 ↓
FastAGI TCP Request
 ↓
Flask Processes Logic
 ↓
Response Sent Back
 ↓
Asterisk Executes Actions
```

---

# FastAGI vs Normal AGI

| Feature     | AGI           | FastAGI           |
| ----------- | ------------- | ----------------- |
| Execution   | process spawn | persistent server |
| Performance | slower        | faster            |
| scalability | low           | high              |
| recommended | no            | yes               |

---

# Main Entities

# 1. FastAGI Session

Represents a single call execution context.

---

## Fields

| Field           | Type      |
| --------------- | --------- |
| id              | UUID      |
| call_session_id | FK        |
| channel         | String    |
| current_step    | String    |
| state           | JSON      |
| started_at      | Timestamp |

---

# 2. AGI Command Queue

Tracks instructions sent to Asterisk.

---

## Fields

| Field      | Type    |
| ---------- | ------- |
| id         | UUID    |
| session_id | FK      |
| command    | String  |
| params     | JSON    |
| executed   | Boolean |

---

# Dialplan Integration

## Example Dialplan

```text id="f3"
exten => _X.,1,Answer()
 same => n,AGI(agi://127.0.0.1:4573/flow)
 same => n,Hangup()
```

---

# FastAGI Server (Flask)

Runs TCP listener:

* receives request
* parses variables
* executes logic
* responds

---

# Request Flow

```text id="f4"
Asterisk
 ↓
TCP Packet (FastAGI)
 ↓
Flask Server
 ↓
Flow Engine Execution
 ↓
Response
 ↓
Asterisk Action
```

---

# FastAGI Request Data

Asterisk sends:

* caller number
* channel
* uniqueid
* extension
* variables

---

# Example Input

```text id="f5"
agi_callerid: 8801xxxx
agi_channel: PJSIP/1001
agi_extension: 123
```

---

# Response Commands

FastAGI returns instructions:

---

## 1. Play Audio

```text id="f6"
STREAM FILE welcome ""
```

---

## 2. Get DTMF

```text id="f7"
GET DATA enter_pin 5000 4
```

---

## 3. Dial

```text id="f8"
EXEC Dial PJSIP/agent1
```

---

## 4. Set Variable

```text id="f9"
SET VARIABLE customer_id 123
```

---

# Flow Engine Integration

FastAGI calls internal flow engine:

```text id="f10"
AGI Request → Flow Engine → Node Execution
```

---

# Example Flow Execution

```text id="f11"
Start Node
 ↓
Play Welcome Audio
 ↓
Collect Input
 ↓
Branch Logic
 ↓
Agent Transfer
```

---

# Real-Time Decision System

FastAGI enables:

* dynamic IVR
* API-driven flows
* AI responses (future)
* CRM-based routing

---

# State Management

Each call session maintains:

* current node
* variables
* flow history
* user inputs

---

# Example State

```json id="j1"
{
  "step": "menu",
  "language": "bn",
  "customer_id": 101
}
```

---

# Performance Requirements

FastAGI must be:

* <50ms response time
* async capable
* stateless per request
* horizontally scalable

---

# Concurrency Handling

Multiple calls handled via:

* async workers
* event loop
* thread-safe session store

---

# Failure Handling

Handle:

* AGI timeout
* broken TCP connection
* invalid response
* flow crash

---

# Retry Strategy

```text id="f12"
Failure → retry flow step → fallback node
```

---

# Logging System

Track:

* AGI requests
* responses
* execution time
* errors

---

# Debug Example

```text id="f13"
AGI ERROR: timeout at node 3
```

---

# Security Considerations

## 1. Internal Network Only

FastAGI should not be publicly exposed.

---

## 2. Session Validation

Validate:

* channel ID
* call session ID

---

## 3. Rate Limiting

Prevent abuse from malformed calls.

---

# Scalability Design

For production:

* FastAGI cluster
* load balancer (Nginx)
* Redis session store
* stateless Flask workers

---

# Recommended Architecture

```text id="f14"
Asterisk
 ↓
FastAGI Load Balancer
 ↓
Flask Workers
 ↓
Flow Engine
 ↓
Redis State Store
```

---

# Integration with Other Modules

## 1. Audio Management

FastAGI triggers:

* playback
* TTS

---

## 2. Webhooks

Flow steps can call external APIs.

---

## 3. Queue System

FastAGI can route calls into queues.

---

## 4. Agent Transfer

FastAGI decides when to transfer calls.

---

# Suggested Implementation Order

## Phase 1

1. basic FastAGI server
2. simple dialplan integration
3. play audio + input capture
4. session tracking

---

## Phase 2

1. flow engine integration
2. state persistence
3. DTMF branching
4. queue integration

---

## Phase 3

1. AI decision engine
2. distributed scaling
3. advanced routing logic
4. observability tools

---

# Final Architecture Summary

```text id="f15"
Asterisk
 ↓
FastAGI Server
 ↓
Flow Engine
 ↓
Business Logic Layer
 ↓
External Systems
```

---

# Final Runtime Flow

```text id="f16"
Call Starts
 ↓
Asterisk Calls FastAGI
 ↓
Flask Processes Logic
 ↓
Flow Decision Made
 ↓
Asterisk Executes Action
 ↓
Call Continues Dynamically
```
