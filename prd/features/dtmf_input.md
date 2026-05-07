# 8. DTMF Input Processing

# Purpose

DTMF Input Processing is responsible for collecting, validating, interpreting, and routing keypad input during active calls.

This is one of the most critical systems in Dialyra because it powers:

* IVR navigation
* menu selection
* customer interaction
* flow branching
* confirmations
* retry logic
* dynamic decision making

---

# What is DTMF?

DTMF stands for:

```text id="f1"
Dual-Tone Multi-Frequency
```

These are the keypad tones generated when users press:

```text id="f2"
0-9
*
#
```

during a phone call.

---

# Core Goals

## 1. Real-Time Input Collection

Capture user keypad input during active calls.

---

## 2. Dynamic Flow Branching

Route call execution based on pressed digits.

---

## 3. Retry & Validation Logic

Handle:

* invalid input
* timeout
* retry attempts

---

## 4. Runtime Interaction

Allow customers to actively navigate flows.

---

# High-Level Architecture

```text id="f3"
Audio Prompt
 ↓
Wait for DTMF
 ↓
Capture Input
 ↓
Validate Input
 ↓
Flow Decision
 ↓
Next Node
```

---

# Core Use Cases

# 1. IVR Menu Navigation

Example:

```text id="f4"
Press 1 for support
Press 2 for sales
```

---

# 2. Order Confirmation

Example:

```text id="f5"
Press 1 to confirm order
```

---

# 3. Language Selection

Example:

```text id="f6"
Press 1 for Bangla
Press 2 for English
```

---

# 4. Retry Logic

Example:

```text id="f7"
Invalid option selected
```

---

# 5. PIN/OTP Collection

Example:

```text id="f8"
Enter your 4 digit PIN
```

---

# Main Runtime Flow

```text id="f9"
Play Menu
 ↓
Wait for Input
 ↓
User presses key
 ↓
Validate
 ↓
Execute Next Node
```

---

# Main Flow Node

# gather_input

This is the primary DTMF collection node.

---

# Example Node Config

```json id="j1"
{
  "type": "gather_input",
  "max_digits": 1,
  "timeout": 5,
  "allowed_inputs": ["1", "2", "3"]
}
```

---

# Core gather_input Properties

| Property        | Purpose                     |
| --------------- | --------------------------- |
| max_digits      | maximum allowed digits      |
| timeout         | wait duration               |
| retries         | retry attempts              |
| terminator_key  | optional end key            |
| allowed_inputs  | valid digits                |
| interrupt_audio | allow input during playback |

---

# DTMF Collection Modes

# 1. Single Digit Input

Example:

```text id="f10"
Press 1 for support
```

---

# 2. Multi-Digit Input

Example:

```text id="f11"
Enter your 6 digit OTP
```

---

# 3. Terminator-Based Input

Example:

```text id="f12"
Enter account number followed by #
```

---

# Runtime DTMF Flow

# Step 1 — Playback Menu

Example:

```text id="f13"
"Press 1 for support"
```

---

# Step 2 — Enable DTMF Listener

Asterisk waits for keypad input.

---

# Step 3 — Capture Digits

Example:

```text id="f14"
User pressed 1
```

---

# Step 4 — Validate Input

Check:

* valid key
* max digits
* timeout

---

# Step 5 — Route Flow

Move to connected node.

---

# Example Flow Routing

```text id="f15"
1 → Support Flow
2 → Sales Flow
3 → Agent Transfer
```

---

# Invalid Input Handling

# Example

```text id="f16"
User pressed 9
```

but valid options are:

```text id="f17"
1, 2, 3
```

---

# Runtime Behavior

```text id="f18"
Play invalid input audio
 ↓
Retry menu
```

---

# Timeout Handling

# Example

```text id="f19"
No key pressed within 5 seconds
```

---

# Runtime Behavior

```text id="f20"
Replay menu
```

or

```text id="f21"
Transfer to agent
```

---

# Retry Logic

# Example

| Attempt | Action             |
| ------- | ------------------ |
| 1       | replay menu        |
| 2       | replay warning     |
| 3       | hangup or transfer |

---

# Runtime State Tracking

Each call session should maintain:

| Variable         | Purpose           |
| ---------------- | ----------------- |
| current_input    | latest DTMF       |
| retry_count      | invalid attempts  |
| timeout_count    | timeout tracking  |
| collected_digits | multi-digit state |

---

# Recommended Runtime Storage

Store active state in:

```text id="f22"
Redis
```

---

# Why Redis?

Because DTMF processing requires:

* low latency
* fast runtime state updates
* temporary session tracking

---

# Asterisk Integration

# Recommended Method

Use:

```text id="f23"
AGI GET DATA
```

or

```text id="f24"
STREAM FILE
```

with digit listening.

---

# Example Runtime Sequence

```text id="f25"
Play audio
 ↓
Listen for DTMF
 ↓
Return captured digits
```

---

# Interruptible Playback

Users may press keys during playback.

---

# Example

```text id="f26"
Press any time to continue
```

---

# Non-Interruptible Playback

Force complete audio playback before input.

---

# Example

```text id="f27"
Legal disclaimer
```

---

# Multi-Level Menu Example

```text id="f28"
Main Menu
 ├── 1 → Orders
 │      ├── 1 → Quantity
 │      ├── 2 → Price
 │      └── 3 → Cancel
 │
 └── 2 → Agent
```

---

# Edge-Based DTMF Routing

Flow edges define keypad routing.

---

# Example

| Source Node  | Digit | Target Node  |
| ------------ | ----- | ------------ |
| gather_input | 1     | order_node   |
| gather_input | 2     | support_node |

---

# Database Design

# DTMF Input Log

Tracks interaction history.

---

## Fields

| Field           | Type      |
| --------------- | --------- |
| id              | UUID      |
| call_session_id | FK        |
| flow_node_id    | FK        |
| input_value     | String    |
| input_status    | Enum      |
| created_at      | Timestamp |

---

# Input Status Types

| Status   | Meaning             |
| -------- | ------------------- |
| valid    | accepted            |
| invalid  | unsupported         |
| timeout  | no input            |
| exceeded | max retries reached |

---

# Analytics Possibilities

DTMF logs enable:

* menu usage analytics
* drop-off analysis
* retry tracking
* UX optimization

---

# Example Analytics

```text id="f29"
80% users press 1
15% users timeout
5% users invalid input
```

---

# Security Considerations

# 1. Input Validation

Prevent:

* malformed input
* overflow input

---

# 2. Max Digit Limits

Avoid abuse.

---

# 3. Retry Protection

Prevent infinite loops.

---

# Recommended API Endpoints

# Create Input Node

```http id="h1"
POST /api/flow-nodes/gather-input
```

---

# Update Input Rules

```http id="h2"
PUT /api/flow-nodes/{id}
```

---

# Get DTMF Logs

```http id="h3"
GET /api/call-sessions/{id}/dtmf
```

---

# Suggested Initial Implementation Order

# Phase 1

Implement:

1. single-digit collection
2. timeout handling
3. invalid input handling
4. retry logic

---

# Phase 2

Implement:

1. multi-digit collection
2. interruptible playback
3. runtime Redis state
4. analytics logging

---

# Phase 3

Implement:

1. speech-to-DTMF hybrid input
2. AI intent routing
3. smart retry prediction
4. conversational IVR

---

# Final Architecture Summary

```text id="f30"
Playback
 ↓
Gather Input
 ↓
Validate
 ↓
Route Flow
 ↓
Continue Execution
```

---

# Final Runtime Flow

```text id="f31"
Audio Prompt
 ↓
Wait for DTMF
 ↓
Capture Input
 ↓
Branch Logic
 ↓
Next Node
```
