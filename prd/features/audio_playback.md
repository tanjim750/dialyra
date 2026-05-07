# 6. Conditional Audio Playback

# Purpose

Conditional Audio Playback is responsible for dynamically playing specific audio during different stages of a call based on runtime conditions, flow logic, customer interaction, or business events.

This system allows Dialyra to create personalized and intelligent call experiences instead of static IVR playback.

The playback behavior is controlled by the Dynamic Flow Engine during runtime.

---

# Core Goals

## 1. Dynamic Runtime Audio Execution

Play different audio depending on:

* call stage
* DTMF input
* business logic
* API response
* retry count
* customer state
* campaign status

---

## 2. Business-Specific Audio Isolation

Each business manages its own audio assets independently.

---

## 3. Real-Time Audio Selection

Audio should be selected dynamically during active calls.

---

# High-Level Architecture

```text id="f1"
Flow Engine
 ↓
Playback Decision
 ↓
Audio Asset Resolver
 ↓
Asterisk Playback
 ↓
Customer Hears Audio
```

---

# Playback Scenarios

# 1. Initial Greeting

Example:

```text id="f2"
"Welcome to ABC Store"
```

---

# 2. Menu Prompt

Example:

```text id="f3"
"Press 1 for order details"
```

---

# 3. Invalid Input

Example:

```text id="f4"
"Invalid option selected"
```

---

# 4. Timeout Prompt

Example:

```text id="f5"
"No input detected"
```

---

# 5. Order Confirmation

Example:

```text id="f6"
"Your order has been confirmed"
```

---

# 6. Retry Notification

Example:

```text id="f7"
"We are trying to reconnect"
```

---

# 7. Call Completion

Example:

```text id="f8"
"Thank you for using our service"
```

---

# Audio Playback Types

# 1. Static Uploaded Audio

Pre-recorded WAV files uploaded by businesses.

---

## Example

```text id="f9"
welcome.wav
```

---

# 2. TTS Generated Audio

Generated dynamically from text.

---

## Example

```text id="f10"
"Your OTP is 5234"
```

---

# 3. Runtime Generated Audio

Generated during active call execution.

---

## Example

```text id="f11"
API response
 ↓
Generate TTS
 ↓
Immediate playback
```

---

# Main Entities

# 1. Audio Asset

Stores uploaded/generated audio metadata.

---

## Audio Asset Fields

| Field          | Type      |
| -------------- | --------- |
| id             | UUID      |
| business_id    | FK        |
| title          | String    |
| asset_type     | Enum      |
| source_text    | Text      |
| file_name      | String    |
| file_path      | String    |
| duration       | Float     |
| language       | String    |
| voice_provider | String    |
| sample_rate    | Integer   |
| created_by     | FK        |
| created_at     | Timestamp |

---

# 2. Audio Playback Rule

Optional advanced abstraction layer.

---

## Purpose

Maps conditions to playback assets.

---

## Playback Rule Fields

| Field           | Type   |
| --------------- | ------ |
| id              | UUID   |
| business_id     | FK     |
| event_type      | Enum   |
| condition_type  | Enum   |
| condition_value | String |
| audio_asset_id  | FK     |

---

# Recommended File Structure

```text id="f12"
/var/lib/asterisk/sounds/dialyra/
 ├── business_1/
 │    ├── welcome.wav
 │    ├── invalid.wav
 │    └── order_confirm.wav
 │
 ├── business_2/
 │    ├── intro.wav
 │    └── support.wav
```

---

# Supported Runtime Conditions

# 1. Call State

Example:

| State     | Audio       |
| --------- | ----------- |
| ringing   | ringing.wav |
| answered  | welcome.wav |
| completed | goodbye.wav |

---

# 2. DTMF Input

Example:

```text id="f13"
if pressed == 1
 → play order_details.wav
```

---

# 3. Timeout

Example:

```text id="f14"
No input
 ↓
Play timeout.wav
```

---

# 4. Invalid Input

Example:

```text id="f15"
Pressed unsupported key
 ↓
Play invalid.wav
```

---

# 5. API Response

Example:

```text id="f16"
Order Status = Delivered
 ↓
Play delivered.wav
```

---

# Runtime Playback Flow

# Step 1 — Flow Node Executes

Example:

```text id="f17"
play_audio
```

---

# Step 2 — Runtime Resolves Asset

System determines:

* business audio
* TTS asset
* generated file

---

# Step 3 — FastAGI Sends Playback Command

Example:

```text id="f18"
STREAM FILE
```

or

```text id="f19"
Playback()
```

---

# Step 4 — Customer Hears Audio

---

# Recommended Audio Formats

# Primary Format

```text id="f20"
wav
```

---

# Recommended Audio Specs

| Property    | Value   |
| ----------- | ------- |
| Codec       | PCM     |
| Sample Rate | 8000 Hz |
| Channels    | Mono    |

---

# Why Important?

Asterisk performs best with telephony-optimized WAV files.

---

# Audio Upload Workflow

# Step 1 — Upload Audio

```http id="h1"
POST /api/audio-assets/upload
```

---

# Step 2 — Validate Audio

Checks:

* format
* duration
* codec
* file size

---

# Step 3 — Convert Audio

Normalize for Asterisk compatibility.

---

# Step 4 — Store File

Save into business directory.

---

# TTS Workflow

# Step 1 — Submit Text

```http id="h2"
POST /api/tts/generate
```

---

# Step 2 — Generate WAV

Using:

* Google TTS
* Azure TTS
* ElevenLabs
* local TTS engine

---

# Step 3 — Save Asset

Store as Audio Asset.

---

# Runtime TTS Playback

Possible future enhancement:

```text id="f21"
Generate TTS during active call
```

---

# Example

```text id="f22"
"Your verification code is 8341"
```

---

# Playback Control Features

# 1. Interruptible Playback

Allow DTMF interruption.

---

## Example

```text id="f23"
Press any key to skip
```

---

# 2. Non-Interruptible Playback

Force complete playback before input.

---

# 3. Playback Timeout

Maximum allowed playback duration.

---

# 4. Repeat Count

Example:

```text id="f24"
Repeat menu 3 times
```

---

# Audio Queueing

Flow engine may queue multiple audio assets.

---

# Example

```text id="f25"
welcome.wav
 ↓
menu.wav
 ↓
confirmation.wav
```

---

# Runtime Audio Context

Each playback should track:

| Variable            | Purpose      |
| ------------------- | ------------ |
| current_audio_id    | active asset |
| playback_started_at | metrics      |
| playback_completed  | state        |
| interrupted_by_dtmf | interaction  |

---

# Event Tracking

Playback events should be logged.

---

# Important Playback Events

| Event                | Purpose       |
| -------------------- | ------------- |
| playback_started     | monitoring    |
| playback_completed   | analytics     |
| playback_interrupted | DTMF tracking |
| playback_failed      | debugging     |

---

# Conditional Playback Example

# Example Flow

```text id="f26"
Customer answers
 ↓
Play welcome.wav
 ↓
Gather input
 ↓
If pressed 1
    ↓
    Play order.wav

If pressed 2
    ↓
    Play support.wav
```

---

# Advanced Playback Features (Future)

# 1. Dynamic Audio Stitching

Combine multiple audio clips.

---

# Example

```text id="f27"
Hello
 + customer_name.wav
 + your order is confirmed
```

---

# 2. AI Voice Playback

AI-generated conversational speech.

---

# 3. Multi-Language Playback

Detect customer language dynamically.

---

# Example

```text id="f28"
BN → Bangla audio
EN → English audio
```

---

# 4. Personalized Playback

Customer-specific audio generation.

---

# Security Considerations

# 1. Business Isolation

Businesses must not access other audio assets.

---

# 2. File Validation

Prevent malicious uploads.

---

# 3. Storage Limits

Limit:

* file size
* duration
* total storage

---

# Recommended API Endpoints

# Upload Audio

```http id="h3"
POST /api/audio-assets/upload
```

---

# Generate TTS

```http id="h4"
POST /api/tts/generate
```

---

# List Audio Assets

```http id="h5"
GET /api/audio-assets
```

---

# Delete Audio Asset

```http id="h6"
DELETE /api/audio-assets/{id}
```

---

# Preview Audio

```http id="h7"
GET /api/audio-assets/{id}/preview
```

---

# Initial Development Order

# Phase 1

Implement:

1. audio asset model
2. upload system
3. WAV conversion
4. playback node

---

# Phase 2

Implement:

1. TTS generation
2. DTMF interruption
3. timeout playback
4. playback analytics

---

# Phase 3

Implement:

1. runtime TTS
2. multilingual playback
3. personalized audio
4. AI voices

---

# Final Architecture Summary

```text id="f29"
Audio Asset
 ↓
Flow Node
 ↓
FastAGI
 ↓
Asterisk Playback
 ↓
Customer
```

---

# Final Runtime Flow

```text id="f30"
Flow Decision
 ↓
Resolve Audio
 ↓
Playback
 ↓
Track Events
 ↓
Continue Flow
```
