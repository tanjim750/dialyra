# 16. Call Recording Management

# Purpose

Call Recording Management enables Dialyra to record, store, retrieve, and analyze voice calls automatically.

It supports:

* compliance recording
* QA review
* training data generation
* dispute resolution
* AI-based speech analysis (future)

---

# Core Goals

## 1. Automatic Call Recording

Record calls without manual intervention.

---

## 2. Secure Storage System

Store recordings per business securely and isolated.

---

## 3. Fast Retrieval

Allow quick playback and download.

---

## 4. Recording Control

Enable:

* start/stop recording
* per-call configuration
* flow-based recording rules

---

# High-Level Architecture

```text id="f1"
Asterisk (MixMonitor / Monitor)
 ↓
Recording Worker
 ↓
Storage Layer
 ↓
Metadata DB
 ↓
Playback API / Dashboard
```

---

# Main Concepts

# 1. Call Recording

Audio file generated during a call.

---

# 2. Recording Session

Logical representation of recording lifecycle.

---

# 3. Recording Policy

Rules that decide when to record.

---

# Main Entities

# 1. Call Recording

Stores recording metadata.

---

## Fields

| Field           | Type      |
| --------------- | --------- |
| id              | UUID      |
| business_id     | FK        |
| call_session_id | FK        |
| file_path       | String    |
| duration        | Integer   |
| file_size       | Integer   |
| format          | String    |
| status          | Enum      |
| started_at      | Timestamp |
| ended_at        | Timestamp |

---

# Recording Status Types

| Status     | Meaning            |
| ---------- | ------------------ |
| started    | recording active   |
| stopped    | recording finished |
| failed     | recording error    |
| processing | post-processing    |
| ready      | available          |

---

# 2. Recording Policy

Defines rules for recording behavior.

---

## Fields

| Field           | Type    |
| --------------- | ------- |
| id              | UUID    |
| business_id     | FK      |
| name            | String  |
| enabled         | Boolean |
| record_inbound  | Boolean |
| record_outbound | Boolean |
| record_agents   | Boolean |
| record_ivr      | Boolean |
| condition_json  | JSON    |

---

# Recording Policy Examples

## Always Record

```text id="f2"
record_inbound = true
record_outbound = true
```

---

## Conditional Record

```json id="j1"
{
  "min_duration": 30,
  "only_vip_calls": true
}
```

---

# Asterisk Integration Methods

## 1. MixMonitor (Recommended)

Records both sides of call in one file.

---

## 2. Monitor (Legacy)

Separate audio channels.

---

## Recording Flow

```text id="f3"
Call Starts
 ↓
Asterisk Trigger MixMonitor
 ↓
Audio Recording Begins
 ↓
Call Ends
 ↓
File Finalized
```

---

# File Storage Architecture

## Recommended Structure

```text id="f4"
recordings/
 └── business_id/
      └── year/
           └── month/
                └── call_id.wav
```

---

## Example

```text id="f5"
recordings/123/2026/05/abc123.wav
```

---

# Storage Options

## 1. Local Disk

* fast
* simple
* single server

---

## 2. Object Storage (Recommended for scale)

* S3 / MinIO / R2
* distributed access
* backup support

---

# Recording Lifecycle

```text id="f6"
Call Start
 ↓
Recording Start
 ↓
Call Active
 ↓
Recording Stop
 ↓
Processing
 ↓
Storage Save
 ↓
Available for Playback
```

---

# Post Processing Pipeline

After recording ends:

* normalize audio
* compress file
* convert format
* generate waveform (optional)

---

# Example Formats

| Format | Use Case           |
| ------ | ------------------ |
| WAV    | high quality       |
| MP3    | storage optimized  |
| GSM    | telephony standard |

---

# Recording Metadata Tracking

Each recording stores:

* duration
* agent involved
* call outcome
* flow path reference

---

# Call Session Linkage

Recording always tied to:

```text id="f7"
Call Session → Recording
```

---

# Playback System

## Features

* instant playback
* seek support
* download option
* streaming playback

---

# Playback Flow

```text id="f8"
User Request
 ↓
Auth Check
 ↓
Fetch Recording
 ↓
Stream Audio
```

---

# Security Model

## 1. Business Isolation

Each business can only access own recordings.

---

## 2. Role-Based Access

* admin: full access
* supervisor: limited access
* agent: optional access

---

## 3. Signed URLs (Optional)

Secure temporary playback links.

---

# Recording Controls in Flow Engine

## Node-Based Control

Example:

```text id="f9"
If VIP customer → enable recording
```

---

## Dynamic Control

Start/stop recording during call.

---

# Call Recording Events

| Event              | Meaning             |
| ------------------ | ------------------- |
| recording.started  | recording begins    |
| recording.stopped  | recording ends      |
| recording.failed   | error occurred      |
| recording.uploaded | stored successfully |

---

# Event Flow

```text id="f10"
Asterisk Event
 ↓
Recording Manager
 ↓
File System
 ↓
Database Update
 ↓
Webhook Trigger (optional)
```

---

# Webhook Integration

Send recording event externally:

```json id="j2"
{
  "event": "recording.completed",
  "call_id": "abc",
  "file_url": "..."
}
```

---

# Retention Policy

Control how long recordings stay.

---

## Example Rules

| Rule      | Action       |
| --------- | ------------ |
| 30 days   | auto delete  |
| 1 year    | archive      |
| unlimited | keep forever |

---

# Archival System

Move old recordings to:

* cold storage
* S3 Glacier
* backup server

---

# Failure Handling

Handle:

* missing audio file
* disk failure
* partial recording
* corrupted file

---

# Recovery Strategy

* retry upload
* rebuild metadata
* mark as failed safely

---

# Performance Considerations

* streaming vs full download
* chunked uploads
* background processing workers

---

# Scalability Considerations

Large systems require:

* distributed storage
* async upload workers
* CDN for playback
* indexing system for search

---

# Search & Indexing (Future)

Enable search by:

* phone number
* agent
* duration
* keyword (transcription)

---

# AI Integration (Future)

* speech-to-text
* sentiment analysis
* keyword detection
* compliance monitoring

---

# Example AI Use Case

```text id="f11"
Detect angry customer → flag recording
```

---

# Recommended API Endpoints

## Start Recording

```http id="h1"
POST /api/recordings/start
```

---

## Stop Recording

```http id="h2"
POST /api/recordings/stop
```

---

## Get Recordings

```http id="h3"
GET /api/recordings
```

---

## Download Recording

```http id="h4"
GET /api/recordings/{id}/download
```

---

## Stream Recording

```http id="h5"
GET /api/recordings/{id}/stream
```

---

# Suggested Implementation Order

## Phase 1

1. MixMonitor integration
2. file storage system
3. metadata database
4. basic playback API

---

## Phase 2

1. recording policies
2. role-based access
3. webhook events
4. retention system

---

## Phase 3

1. cloud storage integration
2. streaming optimization
3. transcription support
4. AI analytics

---

# Final Architecture Summary

```text id="f12"
Asterisk Call
 ↓
MixMonitor Recording
 ↓
File Storage
 ↓
Recording Service
 ↓
Database
 ↓
Playback API
```

---

# Final Runtime Flow

```text id="f13"
Call Starts
 ↓
Recording Begins
 ↓
Call Ends
 ↓
File Stored
 ↓
Metadata Saved
 ↓
Available for Playback
```
