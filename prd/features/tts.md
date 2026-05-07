# 7. Text-to-Speech (TTS) Generation

# Purpose

The TTS Generation system converts business-defined text into telephony-compatible speech audio that can be dynamically played during calls.

This enables Dialyra to generate scalable, customizable, and dynamic voice interactions without requiring businesses to manually record every audio file.

---

# Core Goals

## 1. Dynamic Voice Generation

Generate audio from text automatically.

---

## 2. Runtime Personalization

Allow dynamic call content generation.

---

## 3. Reduce Manual Audio Recording

Businesses should not need to upload every possible audio variation manually.

---

## 4. Multi-Language Support

Support:

* Bangla
* English
* multilingual calls

---

# High-Level Architecture

```text id="f1"
Business Text
 ↓
TTS Engine
 ↓
Audio Generation
 ↓
WAV Conversion
 ↓
Asterisk Playback
```

---

# Core Use Cases

# 1. Menu Playback

Example:

```text id="f2"
"Press 1 for sales"
```

---

# 2. Order Confirmation

Example:

```text id="f3"
"Your order has been confirmed"
```

---

# 3. OTP Delivery

Example:

```text id="f4"
"Your verification code is 4821"
```

---

# 4. Dynamic Customer Data

Example:

```text id="f5"
"Your due amount is 500 taka"
```

---

# 5. Runtime API Responses

Example:

```text id="f6"
Webhook Response
 ↓
Generate TTS
 ↓
Play during active call
```

---

# Core Architecture Types

# 1. Pre-Generated TTS

Text converted before call execution.

---

## Workflow

```text id="f7"
Text Saved
 ↓
Generate WAV
 ↓
Store Audio Asset
 ↓
Playback Later
```

---

## Advantages

* fast playback
* lower runtime CPU usage
* reliable

---

# 2. Runtime TTS

Generated during active calls.

---

## Workflow

```text id="f8"
Call Active
 ↓
Generate TTS
 ↓
Immediate Playback
```

---

## Advantages

* highly dynamic
* personalized
* API-driven

---

# Recommended Initial Strategy

Start with:

```text id="f9"
Pre-generated TTS
```

because runtime TTS adds:

* latency
* concurrency complexity
* streaming complexity

---

# Main Entities

# 1. TTS Request

Stores text generation requests.

---

## Fields

| Field             | Type      |
| ----------------- | --------- |
| id                | UUID      |
| business_id       | FK        |
| text              | Text      |
| language          | String    |
| voice_name        | String    |
| provider          | Enum      |
| generation_status | Enum      |
| audio_asset_id    | FK        |
| created_by        | FK        |
| created_at        | Timestamp |

---

# 2. Audio Asset

Generated TTS ultimately becomes an Audio Asset.

---

# TTS Providers

# 1. Google TTS

Good:

* simple
* low-cost
* multilingual

---

# 2. Azure Cognitive Speech

Good:

* neural voices
* high quality

---

# 3. Amazon Polly

Good:

* scalable
* production-ready

---

# 4. ElevenLabs

Good:

* ultra-natural AI voice

---

# 5. Local Offline TTS

Example:

```text id="f10"
Coqui TTS
Piper
eSpeak
```

---

# Recommended Initial Provider

Start with:

```text id="f11"
Google TTS or Piper
```

because implementation is simpler.

---

# Audio Generation Pipeline

# Step 1 — Receive Text

Example:

```text id="f12"
"Your order has been confirmed"
```

---

# Step 2 — Normalize Text

Clean:

* special characters
* unsupported symbols
* extra spaces

---

# Step 3 — Generate Raw Audio

TTS engine produces:

* mp3
* wav
* ogg

---

# Step 4 — Convert to Asterisk Format

Convert to:

```text id="f13"
8kHz mono WAV PCM
```

---

# Step 5 — Store Audio Asset

Save inside:

```text id="f14"
/var/lib/asterisk/sounds/dialyra/
```

---

# Step 6 — Register Metadata

Store DB record.

---

# Recommended File Naming Strategy

```text id="f15"
business_id/hash.wav
```

---

# Example

```text id="f16"
1/tts_92af2d.wav
```

---

# Why Hash-Based Naming?

Because:

* duplicate prevention
* cache optimization
* easy regeneration

---

# TTS Caching Strategy

Avoid generating same text repeatedly.

---

# Example

```text id="f17"
"Press 1 for support"
```

generated once and reused.

---

# Suggested Cache Key

```text id="f18"
hash(text + language + voice)
```

---

# Runtime Playback Flow

```text id="f19"
Flow Node
 ↓
Resolve TTS Asset
 ↓
Playback
```

---

# Runtime Dynamic TTS Flow

```text id="f20"
Webhook
 ↓
Get Dynamic Data
 ↓
Generate Speech
 ↓
Play Audio
```

---

# Language Support

# Recommended Initial Languages

| Language | Priority |
| -------- | -------- |
| Bangla   | High     |
| English  | High     |

---

# Multi-Language Flow Example

```text id="f21"
Press 1 for Bangla
Press 2 for English
```

---

# Voice Configuration

Businesses may configure:

| Property       | Example      |
| -------------- | ------------ |
| voice type     | male/female  |
| speaking speed | normal/slow  |
| language       | bn/en        |
| provider       | Google/Azure |

---

# Flow Integration

TTS integrates directly into:

```text id="f22"
say_text node
```

---

# Example Node Config

```json id="j1"
{
  "text": "Your order is confirmed",
  "language": "bn",
  "voice": "female"
}
```

---

# Advanced Dynamic Variables

Support placeholders.

---

# Example

```text id="f23"
Hello {{customer_name}}
```

---

# Runtime Variable Injection

```text id="f24"
Hello Tanjim
```

---

# Template Rendering Flow

```text id="f25"
Template
 ↓
Inject Variables
 ↓
Generate Final Text
 ↓
Generate Audio
```

---

# Recommended Initial Constraints

| Constraint             | Value      |
| ---------------------- | ---------- |
| max text length        | 1000 chars |
| supported languages    | bn/en      |
| supported format       | wav        |
| max generation timeout | 10 sec     |

---

# Background Processing

TTS generation should ideally run asynchronously.

---

# Recommended Queue Flow

```text id="f26"
Flask API
 ↓
Redis Queue
 ↓
Worker
 ↓
Generate TTS
 ↓
Store Asset
```

---

# Why Async?

Because TTS generation:

* can be slow
* may use external APIs
* should not block API response

---

# Recommended Worker Stack

| Component | Purpose     |
| --------- | ----------- |
| Redis     | queue       |
| RQ/Celery | task worker |
| Flask     | API         |

---

# Runtime TTS Challenges

# 1. Latency

Live generation may delay calls.

---

# 2. Concurrent Calls

Multiple simultaneous TTS requests.

---

# 3. API Cost

External provider billing.

---

# 4. Streaming Complexity

Real-time playback is harder.

---

# Suggested Initial Strategy

```text id="f27"
Generate first
Play later
```

---

# Security Considerations

# 1. Text Validation

Prevent:

* malicious injection
* unsupported characters

---

# 2. API Rate Limiting

Protect TTS provider usage.

---

# 3. Business Isolation

Businesses access only their own TTS assets.

---

# Recommended API Endpoints

# Generate TTS

```http id="h1"
POST /api/tts/generate
```

---

# Get TTS Status

```http id="h2"
GET /api/tts/{id}
```

---

# List TTS Assets

```http id="h3"
GET /api/tts
```

---

# Delete TTS Asset

```http id="h4"
DELETE /api/tts/{id}
```

---

# Preview TTS Audio

```http id="h5"
GET /api/tts/{id}/preview
```

---

# Suggested Initial Implementation Order

# Phase 1

Implement:

1. basic TTS generation
2. WAV conversion
3. audio storage
4. playback integration

---

# Phase 2

Implement:

1. caching
2. variable injection
3. async workers
4. multilingual support

---

# Phase 3

Implement:

1. runtime streaming TTS
2. AI conversational speech
3. voice cloning
4. emotion-aware speech

---

# Final Architecture Summary

```text id="f28"
Text
 ↓
TTS Engine
 ↓
WAV Conversion
 ↓
Audio Asset
 ↓
Playback
```

---

# Final Runtime Flow

```text id="f29"
Flow Node
 ↓
Generate/Resolve TTS
 ↓
Playback
 ↓
Continue Flow
```
