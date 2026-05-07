# 1. Business & Workspace Management

# Purpose

Business & Workspace Management is the foundational layer of Dialyra.
The entire system is designed as a multi-tenant outbound calling platform where multiple businesses can independently manage their telephony operations from a single infrastructure.

Each business acts as an isolated workspace containing:

* Business information
* Users and permissions
* SIP trunks
* Audio assets
* TTS assets
* Call flows
* Campaigns
* Call logs
* Analytics
* Agent configurations

This layer ensures complete separation between organizations while allowing centralized infrastructure management.

---

# Core Goals

## 1. Multi-Tenant Architecture

Allow multiple businesses to use the same Dialyra infrastructure independently.

Example:

```text id="f1"
Business A
 ├── own SIP trunks
 ├── own flows
 ├── own campaigns
 └── own agents

Business B
 ├── own assets
 ├── own IVR logic
 ├── own analytics
 └── own users
```

---

## 2. Resource Isolation

Every business resource must remain isolated.

### Isolation Scope

* SIP credentials
* Audio files
* Flow definitions
* Call sessions
* Campaigns
* Analytics
* API access
* Recordings

---

## 3. Centralized Infrastructure

Despite isolation, all businesses use the same:

* Flask backend
* PostgreSQL database
* Redis queues
* FastAGI runtime
* Asterisk cluster

---

# Main Entities

# 1. Business

Represents an organization/workspace.

## Purpose

Acts as the root entity for all business-owned resources.

---

## Business Fields

| Field         | Type      | Purpose              |
| ------------- | --------- | -------------------- |
| id            | UUID      | Primary identifier   |
| name          | String    | Business name        |
| slug          | String    | Unique business slug |
| owner_name    | String    | Business owner       |
| email         | String    | Contact email        |
| phone         | String    | Contact number       |
| website       | String    | Business website     |
| business_type | String    | Industry/category    |
| address       | Text      | Business address     |
| timezone      | String    | Business timezone    |
| status        | Enum      | active/suspended     |
| created_at    | Timestamp | Creation time        |

---

# 2. Workspace User

Users associated with a business.

## Purpose

Allows multiple team members to manage a business workspace.

---

## User Roles

| Role    | Purpose                   |
| ------- | ------------------------- |
| owner   | Full control              |
| admin   | Manage operations         |
| manager | Campaign management       |
| agent   | Receive transferred calls |
| viewer  | Read-only access          |

---

## Workspace User Fields

| Field         | Type      |
| ------------- | --------- |
| id            | UUID      |
| business_id   | FK        |
| full_name     | String    |
| email         | String    |
| password_hash | String    |
| role          | Enum      |
| status        | Enum      |
| last_login    | Timestamp |

---

# 3. Business SIP Trunk

Stores SIP configurations owned by a business.

## Purpose

Allows each business to use its own telecom provider.

---

## SIP Fields

| Field         | Type      |
| ------------- | --------- |
| id            | UUID      |
| business_id   | FK        |
| name          | String    |
| provider_name | String    |
| host          | String    |
| username      | String    |
| password      | Encrypted |
| port          | Integer   |
| transport     | Enum      |
| trunk_type    | Enum      |
| is_global     | Boolean   |
| is_active     | Boolean   |

---

# 4. Audio Asset

Stores uploaded or generated audio files.

## Purpose

Used for IVR playback and runtime audio execution.

---

## Audio Fields

| Field       | Type      |
| ----------- | --------- |
| id          | UUID      |
| business_id | FK        |
| title       | String    |
| type        | Enum      |
| source_text | Text      |
| file_path   | String    |
| duration    | Float     |
| language    | String    |
| created_by  | FK User   |
| created_at  | Timestamp |

---

# 5. Flow

Represents programmable call logic.

## Purpose

Controls IVR behavior dynamically.

---

## Flow Fields

| Field         | Type    |
| ------------- | ------- |
| id            | UUID    |
| business_id   | FK      |
| name          | String  |
| description   | Text    |
| start_node_id | UUID    |
| status        | Enum    |
| version       | Integer |
| created_by    | FK User |

---

# 6. Flow Node

Individual runtime execution blocks.

## Purpose

Represents executable telephony actions.

---

## Node Types

| Node Type     | Purpose           |
| ------------- | ----------------- |
| play_audio    | Play audio        |
| say_text      | TTS playback      |
| gather_input  | Collect DTMF      |
| condition     | Branching         |
| transfer_call | Transfer to agent |
| webhook       | External API      |
| hangup        | End call          |

---

## Flow Node Fields

| Field      | Type  |
| ---------- | ----- |
| id         | UUID  |
| flow_id    | FK    |
| type       | Enum  |
| config     | JSON  |
| position_x | Float |
| position_y | Float |

---

# 7. Campaign

Outbound call execution group.

## Purpose

Manages bulk calling operations.

---

## Campaign Fields

| Field        | Type      |
| ------------ | --------- |
| id           | UUID      |
| business_id  | FK        |
| flow_id      | FK        |
| name         | String    |
| status       | Enum      |
| retry_policy | JSON      |
| scheduled_at | Timestamp |

---

# 8. Call Session

Runtime call tracking entity.

## Purpose

Tracks every active/completed call.

---

## Call Session Fields

| Field           | Type      |
| --------------- | --------- |
| id              | UUID      |
| business_id     | FK        |
| campaign_id     | FK        |
| flow_id         | FK        |
| phone_number    | String    |
| status          | Enum      |
| current_node_id | UUID      |
| started_at      | Timestamp |
| ended_at        | Timestamp |
| duration        | Integer   |

---

# Workspace Isolation Strategy

Every major entity includes:

```text id="f2"
business_id
```

This guarantees:

* logical separation
* query-level isolation
* scalable multi-tenancy

---

# File Storage Structure

Recommended VPS structure:

```text id="f3"
/var/lib/asterisk/sounds/dialyra/
 ├── business_1/
 │    ├── welcome.wav
 │    ├── confirm.wav
 │    └── retry.wav
 │
 ├── business_2/
 │    ├── intro.wav
 │    └── support.wav
```

---

# API Design Flow

# Step 1 — Create Business

```http id="h1"
POST /api/businesses
```

Creates:

* business
* owner user
* default workspace

---

# Step 2 — Business Authentication

```http id="h2"
POST /api/auth/login
```

Returns:

* JWT token
* workspace context

---

# Step 3 — Add SIP Trunk

```http id="h3"
POST /api/businesses/{id}/sip-trunks
```

Stores provider configuration.

---

# Step 4 — Upload Audio / Generate TTS

```http id="h4"
POST /api/audio-assets
```

OR

```http id="h5"
POST /api/tts/generate
```

---

# Step 5 — Create Flow

```http id="h6"
POST /api/flows
```

Defines runtime call logic.

---

# Step 6 — Launch Campaign

```http id="h7"
POST /api/campaigns
```

Starts outbound calling workflow.

---

# Runtime Architecture

# Flask Layer

Responsible for:

* APIs
* authentication
* DB operations
* business management
* flow definitions
* campaign management

---

# FastAGI Layer

Responsible for:

* runtime node execution
* DTMF processing
* conditional logic
* live call traversal

---

# Asterisk Layer

Responsible for:

* SIP
* RTP/media
* audio playback
* call bridging
* call recording

---

# Recommended Initial Development Order

## Phase 1

Implement:

1. Business model
2. User model
3. JWT authentication
4. SIP trunk model
5. Audio asset management

---

## Phase 2

Implement:

1. Flow model
2. Flow node model
3. Flow execution engine
4. DTMF handling

---

## Phase 3

Implement:

1. Campaigns
2. Call sessions
3. Retry system
4. Scheduler

---

# Final Architecture Summary

```text id="f4"
Business
 ├── Users
 ├── SIP Trunks
 ├── Audio Assets
 ├── Flows
 │    └── Nodes
 ├── Campaigns
 └── Call Sessions
```
