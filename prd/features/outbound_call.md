# 4. Outbound Call Origination

# Purpose

Outbound Call Origination is responsible for initiating automated outbound calls from Dialyra through Asterisk using configured SIP trunks.

This feature is the execution entry point of the entire calling system.

Every automated call begins from this layer.

It connects:

```text id="f1"
Business Logic
↓
Call Execution
↓
Telephony Infrastructure
```

---

# Core Goals

## 1. Programmatic Call Initiation

Allow the system to create outbound calls dynamically through APIs, campaigns, schedulers, or runtime events.

---

## 2. Dynamic Call Flow Execution

Every outbound call should attach to a runtime flow.

Example:

```text id="f2"
Call User
↓
Play Welcome Audio
↓
Collect DTMF
↓
Transfer to Agent
```

---

## 3. SIP-Agnostic Execution

The originate system should work regardless of:

* SIP provider
* authentication type
* transport
* business configuration

---

# High-Level Architecture

```text id="f3"
Flask API
 ↓
AMI Originate
 ↓
Asterisk
 ↓
Dialplan/FastAGI
 ↓
SIP Trunk
 ↓
Destination Number
```

---

# Main Responsibilities

The originate layer handles:

* outbound call creation
* SIP trunk selection
* flow assignment
* campaign linkage
* retry orchestration
* runtime variable injection
* call tracking initialization

---

# Core Components

# 1. Originate API Layer

Receives outbound call requests.

---

## Example

```http id="h1"
POST /api/calls/originate
```

---

# 2. Call Validation Layer

Validates:

* business access
* SIP availability
* destination number
* concurrency limits
* campaign rules

---

# 3. Routing Layer

Determines:

* which SIP trunk to use
* which flow to attach
* retry behavior
* caller ID

---

# 4. AMI Originate Layer

Sends originate action to Asterisk.

---

# 5. Runtime Flow Execution

Asterisk enters:

```text id="f4"
FastAGI runtime
```

or

```text id="f5"
dynamic dialplan context
```

---

# Call Origination Flow

# Step 1 — API Request

Client requests outbound call.

---

## Example Payload

```json id="j1"
{
  "phone_number": "8801XXXXXXXXX",
  "flow_id": "uuid",
  "sip_trunk_id": "uuid",
  "caller_id": "Dialyra",
  "campaign_id": "uuid"
}
```

---

# Step 2 — Authentication

Validate:

* JWT
* business ownership
* permissions

---

# Step 3 — SIP Selection

Determine:

* business SIP
* global SIP
* failover trunk

---

# Step 4 — Create Call Session

Insert runtime session into DB.

---

# Step 5 — AMI Originate

Flask sends:

```text id="f6"
Action: Originate
```

to Asterisk.

---

# Step 6 — Asterisk Creates Channel

Example:

```text id="f7"
Local/8801xxxx@outbound
```

---

# Step 7 — Dialplan/FastAGI Starts

Call enters runtime execution engine.

---

# Step 8 — Customer Receives Call

Flow execution begins after answer.

---

# AMI Originate Architecture

# Why Use AMI?

Because AMI provides:

* remote control
* async call execution
* event tracking
* scalable automation

---

# AMI Responsibilities

AMI handles:

* originate requests
* channel monitoring
* hangup events
* call state events
* bridge events

---

# Example Originate Flow

```text id="f8"
Flask
 ↓
AMI TCP Connection
 ↓
Asterisk Manager Interface
 ↓
Originate Action
 ↓
Asterisk Channel
```

---

# Originate Strategies

# 1. Local Channel Originate (Recommended)

Recommended architecture.

---

## Example

```text id="f9"
Channel: Local/8801xxxx@outbound
```

---

## Benefits

* flexible routing
* FastAGI integration
* runtime variables
* easier debugging

---

# 2. Direct PJSIP Originate

Example:

```text id="f10"
PJSIP/8801xxxx@provider
```

---

## Drawback

Less flexible for advanced runtime logic.

---

# Recommended Final Approach

Use:

```text id="f11"
Local Channel
```

for all production originates.

---

# Runtime Variables

Originate should inject metadata into runtime.

---

# Example Variables

| Variable        | Purpose           |
| --------------- | ----------------- |
| BUSINESS_ID     | Workspace context |
| FLOW_ID         | Runtime flow      |
| CAMPAIGN_ID     | Campaign tracking |
| SIP_TRUNK_ID    | Selected provider |
| CALL_SESSION_ID | Runtime tracking  |
| CUSTOMER_NUMBER | Destination       |
| RETRY_COUNT     | Retry tracking    |

---

# Example Runtime Context

```text id="f12"
Originate
 ↓
Set Variables
 ↓
FastAGI Reads Variables
 ↓
Dynamic Execution
```

---

# Call Session Creation

Every originate creates:

```text id="f13"
Call Session
```

before dialing begins.

---

# Purpose

Tracks:

* call lifecycle
* analytics
* retries
* recordings
* DTMF events

---

# Call States

# Suggested States

| State      | Meaning           |
| ---------- | ----------------- |
| queued     | waiting           |
| initiating | AMI sent          |
| ringing    | endpoint ringing  |
| answered   | customer answered |
| completed  | successful        |
| failed     | failed            |
| busy       | busy              |
| no_answer  | unanswered        |
| canceled   | stopped           |

---

# Retry Handling

Failed calls may automatically retry.

---

# Retry Conditions

| Condition      | Retry?   |
| -------------- | -------- |
| no answer      | yes      |
| busy           | yes      |
| rejected       | optional |
| invalid number | no       |

---

# Retry Strategy Example

```text id="f14"
Attempt 1
 ↓ failed
Wait 10 minutes
 ↓
Attempt 2
 ↓ failed
Wait 1 hour
 ↓
Attempt 3
```

---

# Concurrency Management

Originate system must enforce:

* CPS (calls per second)
* concurrent calls
* provider limits

---

# Why Important?

Prevents:

* SIP bans
* provider overload
* VPS overload

---

# Queue-Based Origination (Recommended)

Do NOT directly originate large campaigns synchronously.

Use:

```text id="f15"
Redis Queue
```

---

# Recommended Flow

```text id="f16"
Campaign
 ↓
Queue
 ↓
Worker
 ↓
AMI Originate
```

---

# Benefits

* scalable
* fault tolerant
* retry capable
* rate limited

---

# Caller ID Handling

Originate layer controls:

* caller name
* caller number
* masking
* business branding

---

# Example

```text id="f17"
CallerID: Dialyra Support <096xxxxxxx>
```

---

# Event Tracking

AMI events should update runtime state.

---

# Important Events

| Event       | Purpose         |
| ----------- | --------------- |
| Newchannel  | channel created |
| DialBegin   | dialing started |
| DialEnd     | dial finished   |
| BridgeEnter | answered        |
| Hangup      | call ended      |

---

# FastAGI Integration

After answer:

```text id="f18"
Asterisk
 ↓
FastAGI
 ↓
Flow Execution
```

---

# Why Important?

This enables:

* dynamic IVR
* AI automation
* real-time branching
* webhook execution

---

# Security Requirements

# 1. Permission Checks

Only authorized users may originate calls.

---

# 2. Number Validation

Validate:

* formatting
* country rules
* blacklist

---

# 3. Rate Limiting

Prevent abuse/spam.

---

# 4. Audit Logging

Track:

* who initiated
* when
* which business
* which SIP trunk

---

# Recommended API Endpoints

# Originate Single Call

```http id="h2"
POST /api/calls/originate
```

---

# Bulk Originate

```http id="h3"
POST /api/calls/bulk
```

---

# Cancel Call

```http id="h4"
POST /api/calls/{id}/cancel
```

---

# Get Call Status

```http id="h5"
GET /api/calls/{id}
```

---

# Active Calls

```http id="h6"
GET /api/calls/active
```

---

# Initial Implementation Plan

# Phase 1

Implement:

1. AMI connection service
2. originate API
3. Local channel originate
4. call session model

---

# Phase 2

Implement:

1. event listeners
2. status tracking
3. retry handling
4. concurrency control

---

# Phase 3

Implement:

1. distributed workers
2. Redis queue
3. advanced routing
4. smart retry engine

---

# Recommended Final Architecture

```text id="f19"
Flask
 ├── API
 ├── Auth
 ├── Queue
 └── AMI Client

Asterisk
 ├── SIP
 ├── RTP
 ├── Dialplan
 └── FastAGI

PostgreSQL
 └── Runtime Storage

Redis
 └── Queue + Rate Limiting
```

---

# Final Runtime Flow

```text id="f20"
Campaign/API
 ↓
Originate Request
 ↓
AMI
 ↓
Asterisk
 ↓
SIP Provider
 ↓
Customer
 ↓
FastAGI Runtime
 ↓
Flow Execution
```
