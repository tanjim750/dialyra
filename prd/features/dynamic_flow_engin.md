# 5. Dynamic Flow Engine

# Purpose

The Dynamic Flow Engine is the core intelligence layer of Dialyra.

It controls how calls behave during runtime by executing programmable flow logic dynamically instead of relying on static Asterisk dialplans.

This engine allows businesses to build:

* IVR systems
* automated conversations
* branching call logic
* DTMF-driven interactions
* webhook-based workflows
* AI-assisted call flows
* agent transfer pipelines

without manually editing Asterisk configurations.

---

# Core Philosophy

Traditional Asterisk systems rely heavily on:

```text id="f1"
extensions.conf
```

which becomes difficult to maintain for dynamic business logic.

Dialyra replaces static telephony logic with:

```text id="f2"
Database-driven runtime flow execution
```

---

# Core Goals

## 1. Fully Dynamic Call Logic

Every call should behave based on database-driven runtime flows.

---

## 2. Node-Based Architecture

Flows are composed of connected nodes.

Example:

```text id="f3"
Start
 ↓
Play Welcome Audio
 ↓
Gather Input
 ↓
Condition Branch
 ├── 1 → Order Details
 ├── 2 → Confirm Order
 └── 3 → Transfer Agent
```

---

## 3. Runtime Execution

Flow decisions happen live during the active call.

---

## 4. Business Isolation

Each business owns its own flows independently.

---

# High-Level Architecture

```text id="f4"
Flask API
 ↓
Flow Definition Storage
 ↓
PostgreSQL
 ↓
FastAGI Runtime
 ↓
Asterisk Call Session
```

---

# Main Components

# 1. Flow

Represents the entire runtime workflow.

---

## Purpose

Acts as the root container of connected nodes.

---

## Flow Fields

| Field         | Type      |
| ------------- | --------- |
| id            | UUID      |
| business_id   | FK        |
| name          | String    |
| description   | Text      |
| status        | Enum      |
| start_node_id | UUID      |
| version       | Integer   |
| created_by    | FK        |
| created_at    | Timestamp |

---

# 2. Flow Node

Represents a single executable runtime action.

---

## Purpose

Controls one specific telephony operation.

---

## Node Fields

| Field      | Type      |
| ---------- | --------- |
| id         | UUID      |
| flow_id    | FK        |
| type       | Enum      |
| config     | JSON      |
| position_x | Float     |
| position_y | Float     |
| created_at | Timestamp |

---

# 3. Flow Edge

Represents node connections.

---

## Purpose

Defines runtime transitions between nodes.

---

## Edge Fields

| Field           | Type   |
| --------------- | ------ |
| id              | UUID   |
| flow_id         | FK     |
| source_node_id  | FK     |
| target_node_id  | FK     |
| condition_type  | Enum   |
| condition_value | String |

---

# Why Edge-Based Architecture?

Because it enables:

* branching
* loops
* conditions
* reusable runtime traversal

---

# Flow Execution Model

# Runtime Traversal

The engine traverses nodes dynamically during the call.

---

# Example

```text id="f5"
Node 1 → play_audio
 ↓
Node 2 → gather_input
 ↓
Node 3 → conditional branch
 ↓
Node 4 → transfer_call
```

---

# Core Node Types

# 1. play_audio

Plays uploaded audio files.

---

## Example

```text id="f6"
welcome.wav
```

---

# 2. say_text

Generate/play TTS audio.

---

## Example

```text id="f7"
"Your order has been confirmed."
```

---

# 3. gather_input

Collect DTMF input.

---

## Example

```text id="f8"
Press 1 for support
Press 2 for sales
```

---

# 4. condition

Evaluates runtime conditions.

---

## Example

```text id="f9"
if digit == 1
```

---

# 5. transfer_call

Transfers call to agent or queue.

---

# 6. webhook

Calls external APIs during runtime.

---

## Example

```text id="f10"
Verify order status
```

---

# 7. wait

Pauses execution.

---

# 8. hangup

Ends call gracefully.

---

# 9. record_call

Starts/stops recording.

---

# 10. goto

Jumps to another node.

---

# Runtime Execution Engine

# Recommended Architecture

```text id="f11"
Asterisk
 ↓
FastAGI
 ↓
Flow Runtime Executor
 ↓
Database Flow Traversal
```

---

# Why FastAGI?

Because FastAGI allows:

* external business logic
* dynamic execution
* scalable runtime processing
* language flexibility
* centralized orchestration

---

# Runtime Call Context

Every active call should contain runtime state.

---

# Runtime Context Example

| Variable        | Purpose          |
| --------------- | ---------------- |
| CALL_SESSION_ID | Runtime tracking |
| BUSINESS_ID     | Tenant isolation |
| FLOW_ID         | Current flow     |
| CURRENT_NODE_ID | Traversal state  |
| DTMF_INPUT      | User input       |
| RETRY_COUNT     | Retry state      |
| CUSTOMER_NUMBER | Destination      |

---

# Runtime Traversal Flow

# Step 1 — Call Starts

Originate triggers FastAGI.

---

# Step 2 — Load Flow

Runtime engine loads:

* flow
* nodes
* edges

from PostgreSQL.

---

# Step 3 — Execute Start Node

Example:

```text id="f12"
play_audio
```

---

# Step 4 — Determine Next Node

Using:

* edges
* conditions
* DTMF results

---

# Step 5 — Continue Traversal

Until:

* hangup
* transfer
* completion

---

# Example Runtime Menu

```text id="f13"
Play:
"Press 1 for order details"

↓
Gather Input

↓
If input == 1

↓
Play Order Info
```

---

# Timeout Handling

Flow engine must support:

* no input timeout
* max retry attempts
* fallback routing

---

# Example

```text id="f14"
No Input
 ↓
Repeat Menu
 ↓
Still no input
 ↓
Transfer Agent
```

---

# Invalid Input Handling

Example:

```text id="f15"
Pressed 9
 ↓
Invalid Option Audio
 ↓
Replay Menu
```

---

# Flow Builder UI Compatibility

The architecture is designed for future visual flow builders.

---

# Example UI

```text id="f16"
[Play Audio]
      ↓
[Gather Input]
   ↙      ↘
[1]      [2]
 ↓         ↓
[Agent] [Order]
```

---

# Database-Driven Logic

Important principle:

```text id="f17"
Business logic should live in DB
NOT in dialplan
```

---

# Benefits

* dynamic updates
* no Asterisk reload
* versioning
* scalable orchestration

---

# Flow Versioning

Flows should support versions.

---

## Purpose

Allows:

* safe updates
* rollback
* campaign stability

---

# Example

```text id="f18"
Flow v1
Flow v2
Flow v3
```

Active calls continue using their assigned version.

---

# Real-Time Runtime State

Runtime state may be cached in:

```text id="f19"
Redis
```

---

# Why?

Because active calls require:

* fast access
* low latency
* temporary state storage

---

# Recommended Runtime Storage Split

| Component            | Storage    |
| -------------------- | ---------- |
| Permanent flow data  | PostgreSQL |
| Active runtime state | Redis      |
| Media playback       | Asterisk   |
| Execution engine     | FastAGI    |

---

# Webhook Integration

Flows may call external systems.

---

# Example

```text id="f20"
Customer presses 1
 ↓
Webhook
 ↓
Fetch order info
 ↓
Generate TTS response
```

---

# AI Integration Future

The architecture naturally supports:

* AI voice agents
* LLM reasoning
* semantic conversation routing
* real-time NLP decisions

because runtime execution is externalized from Asterisk.

---

# Recommended API Endpoints

# Create Flow

```http id="h1"
POST /api/flows
```

---

# Get Flow

```http id="h2"
GET /api/flows/{id}
```

---

# Update Flow

```http id="h3"
PUT /api/flows/{id}
```

---

# Delete Flow

```http id="h4"
DELETE /api/flows/{id}
```

---

# Create Node

```http id="h5"
POST /api/flow-nodes
```

---

# Create Edge

```http id="h6"
POST /api/flow-edges
```

---

# Validate Flow

```http id="h7"
POST /api/flows/{id}/validate
```

---

# Publish Flow

```http id="h8"
POST /api/flows/{id}/publish
```

---

# Runtime Validation Rules

Before publishing:

* no orphan nodes
* valid start node
* no broken edges
* valid node configs
* loop safety checks

---

# Recommended Initial Implementation Order

# Phase 1

Implement:

1. Flow model
2. Node model
3. Edge model
4. basic traversal engine

---

# Phase 2

Implement:

1. DTMF handling
2. timeout handling
3. invalid input logic
4. runtime state tracking

---

# Phase 3

Implement:

1. visual builder
2. webhook execution
3. AI nodes
4. advanced branching

---

# Final Architecture Summary

```text id="f21"
Flow
 ├── Nodes
 └── Edges

Runtime
 ↓
FastAGI Executor
 ↓
Asterisk Call
```

---

# Final Runtime Flow

```text id="f22"
Originate
 ↓
FastAGI
 ↓
Load Flow
 ↓
Execute Nodes
 ↓
Branch Decisions
 ↓
Transfer/Hangup
```
