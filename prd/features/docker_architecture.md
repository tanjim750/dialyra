# Dialyra Docker Architecture Documentation

# Overview

Dialyra is designed using a multi-container Docker architecture to ensure:

- scalability
- isolation
- realtime performance
- easier deployments
- production reliability

The platform separates telephony, business logic, and realtime IVR execution into dedicated services.

---

# Core Containers

Dialyra uses the following primary containers:

```text
dialyra_flask
dialyra_fastagi
dialyra_asterisk
```

Additional infrastructure containers:

```text
PostgreSQL
Redis
```

---

# High-Level Architecture

```text
                    ┌──────────────────────┐
                    │   dialyra_flask     │
                    │ Business/API Layer  │
                    └──────────┬──────────┘
                               │
                               │ REST APIs
                               │ AMI Commands
                               ▼
                    ┌──────────────────────┐
                    │  dialyra_asterisk   │
                    │ SIP/RTP Engine      │
                    └──────────┬──────────┘
                               │
                               │ AGI TCP
                               ▼
                    ┌──────────────────────┐
                    │  dialyra_fastagi    │
                    │ Realtime IVR Engine │
                    └──────────┬──────────┘
                               │
                               ▼
                         PostgreSQL
                               │
                               ▼
                             Redis
```

---

# Container Responsibilities

---

# 1. dialyra_flask

## Purpose

Acts as the main business logic and control layer.

---

## Responsibilities

### Tenant Management
- multi-business management
- user management
- permissions

### Campaign Management
- outbound campaigns
- schedules
- retry logic
- caller ID configuration

### SIP Trunk Management
- trunk configuration
- authentication
- provider mapping

### IVR Configuration
- menu structures
- DTMF mappings
- queue mapping
- playback mapping

### Audio Asset Management
- upload audio
- delete audio
- organize business-specific sounds
- generate TTS audio

### AMI Control
- originate calls
- monitor events
- manage call lifecycle

### API Layer
- frontend APIs
- webhooks
- analytics APIs

---

## Recommended Stack

```text
Flask / FastAPI
SQLAlchemy
Redis
PostgreSQL
```

---

# 2. dialyra_fastagi

## Purpose

Handles realtime call interaction and dynamic IVR execution.

---

## Responsibilities

### Dynamic IVR Execution
- playback decisions
- menu navigation
- DTMF handling

### Runtime Call Logic
- database-driven routing
- dynamic menu loading
- queue decisions
- retry handling

### AI Integration
- speech workflows
- AI voice logic
- conversational routing

### AGI TCP Server

Receives AGI requests from Asterisk:

```text
agi://dialyra_fastagi:4573
```

---

## Recommended Stack

```text
Python asyncio
uvloop
FastAGI Server
Redis
```

---

# 3. dialyra_asterisk

## Purpose

Acts as the telephony and media engine.

---

## Responsibilities

### SIP Communication
- SIP trunks
- SIP registration
- outbound calling
- inbound calls

### RTP Media Handling
- audio playback
- transcoding
- media streaming
- recording

### Dialplan Execution
- entrypoint routing
- AGI execution
- fallback routing

### Telephony Features
- queues
- transfers
- bridges
- recordings

---

# Recommended Production Configuration

Use:

```yaml
network_mode: host
```

Reason:
- RTP stability
- SIP stability
- avoids NAT problems
- avoids Docker UDP translation issues

---

# Shared Infrastructure

---

# PostgreSQL

## Purpose

Central persistent database for all services.

---

## Used By

```text
dialyra_flask
dialyra_fastagi
dialyra_asterisk (optional realtime)
```

---

## Stores

- tenant data
- campaigns
- IVR configuration
- SIP trunks
- call logs
- analytics
- queue configuration

---

# Redis

## Purpose

Realtime coordination and event layer.

---

## Used By

```text
dialyra_flask
dialyra_fastagi
workers
AMI listeners
websocket services
```

---

## Redis Responsibilities

### Event Bus
- AMI events
- call events
- queue events

### Realtime State
- active calls
- IVR session state
- temporary DTMF state

### Queue System
- outbound job queues
- retry queues
- scheduled call processing

### Realtime Dashboard Updates
- websocket updates
- live analytics
- agent monitoring

---

# Important Principle

```text
PostgreSQL = source of truth
Redis = realtime state layer
```

---

# Shared Volumes

---

# Audio Assets

Shared between:

```text
dialyra_flask
dialyra_asterisk
```

---

## Purpose

Allows Flask to:
- upload audio
- remove audio
- generate TTS
- organize tenant-specific sounds

while Asterisk immediately accesses them for playback.

---

# Host Directory

```text
./shared/sounds
```

---

# Flask Mount

```text
/shared/sounds
```

---

# Asterisk Mount

```text
/var/lib/asterisk/sounds
```

---

# Recordings

Optional shared recording volume:

```text
./shared/recordings
```

Mounted to:

```text
/var/spool/asterisk/monitor
```

---

# Internal Communication

---

# Flask → Asterisk

Uses:

```text
AMI (Port 5038)
```

Purpose:
- originate calls
- monitor events
- queue control
- call management

---

# Asterisk → FastAGI

Uses:

```text
AGI TCP
```

Example:

```asterisk
AGI(agi://dialyra_fastagi:4573/ivr)
```

---

# FastAGI → PostgreSQL

Used for:
- IVR lookup
- tenant lookup
- menu configuration
- playback mapping

---

# FastAGI → Redis

Used for:
- session state
- realtime coordination
- event publishing

---

# Recommended Docker Compose Structure

```text
services:
  dialyra_flask
  dialyra_fastagi
  dialyra_asterisk
  postgres
  redis
```

---

# Recommended Folder Structure

```text
Dialyra/
│
├── docker-compose.yml
│
├── dialyra_flask/
│
├── dialyra_fastagi/
│
├── asterisk/
│   ├── extensions.conf
│   ├── pjsip.conf
│   ├── manager.conf
│   ├── ari.conf
│   └── realtime.conf
│
├── shared/
│   ├── sounds/
│   └── recordings/
│
└── postgres/
```

---

# Recommended Networking

---

# Asterisk Networking

Recommended:

```yaml
network_mode: host
```

Reason:
- SIP stability
- RTP stability
- reduced NAT issues
- reduced UDP problems

---

# Flask / FastAGI Networking

Recommended:

```yaml
networks:
  - dialyra-net
```

Bridge networking is sufficient.

---

# Important Architecture Principles

---

# Keep Services Separate

Do NOT combine:
- Flask
- FastAGI
- Asterisk

inside one container.

Benefits:
- safer deployments
- independent restarts
- easier debugging
- cleaner scaling
- service isolation

---

# Use Shared Volumes Instead of Shared Containers

Shared filesystem access should happen through:

```text
Docker volumes
```

not by combining services into one container.

---

# Persist Important Data

Always persist:

```text
/etc/asterisk
/var/lib/asterisk/sounds
/var/spool/asterisk/monitor
```

using Docker volumes.

---

# Security Recommendations

Never expose publicly:
- AMI
- ARI

Recommended:
- firewall restrictions
- VPN access
- internal-only networking
- fail2ban

---

# Long-Term Scalability

This architecture supports:

- multi-tenant SaaS
- AI voice systems
- outbound dialers
- realtime IVR
- predictive dialing
- analytics
- call queues
- conversational AI
- realtime dashboards

---

# Final System Architecture

```text
dialyra_flask
    ↓
Business Logic / APIs / Campaign Engine

dialyra_fastagi
    ↓
Realtime IVR Decision Engine

dialyra_asterisk
    ↓
SIP + RTP + Media Execution
```

This architecture provides a scalable and production-ready foundation for Dialyra.