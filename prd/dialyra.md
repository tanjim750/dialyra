# Dialyra — Intelligent Outbound Calling & IVR Platform

## Project Purpose

Dialyra is a scalable outbound calling and IVR automation platform designed to help businesses automate customer communication using programmable call flows, SIP telephony, dynamic audio playback, and real-time call interaction.

The platform allows businesses to:

* Make automated outbound calls
* Build dynamic IVR workflows
* Handle DTMF user interactions
* Play conditional audio responses
* Use Text-to-Speech generated audio
* Transfer calls to live agents
* Track and monitor call sessions
* Manage campaigns and retry logic

The system architecture is divided into three major layers:

```text
Flask API Layer
↓
FastAGI Runtime Layer
↓
Asterisk Telephony Layer
```

---

# Core Features

## 1. Business & Workspace Management

Manage multiple businesses/workspaces inside the platform with isolated configurations, SIP trunks, flows, campaigns, and assets.

### Purpose

Provides multi-tenant architecture for supporting multiple organizations from a single system.

---

## 2. Authentication & Role Management

Authentication system for admins, business owners, agents, and managers with permission-based access control.

### Purpose

Ensures secure access and operational separation between users and businesses.

---

## 3. SIP Trunk Management

Configure and manage SIP providers and business-specific SIP trunks for outbound calling.

### Purpose

Allows businesses to route calls through their own telecom providers or shared global trunks.

---

## 4. Outbound Call Origination

Initiate outbound calls using Asterisk AMI originate actions.

### Purpose

Acts as the entry point for automated calling campaigns and live call workflows.

---

## 5. Dynamic Flow Engine

A node-based runtime flow system that controls call behavior dynamically.

### Purpose

Provides programmable IVR and automation logic without hardcoding dialplans.

### Example Flow Actions

* Play audio
* Gather DTMF input
* Conditional branching
* Call transfer
* Webhook execution
* Hangup handling

---

## 6. Conditional Audio Playback

Play specific audio files based on runtime conditions and user interactions.

### Purpose

Allows dynamic and contextual call experiences.

### Example

* Ringing audio
* Welcome message
* Order confirmation message
* Conditional branch responses

---

## 7. Text-to-Speech (TTS) Generation

Generate audio files dynamically from text using TTS engines.

### Purpose

Enables businesses to create automated voice responses without manual recordings.

---

## 8. DTMF Input Processing

Capture and process keypad inputs during calls.

### Purpose

Enables interactive IVR experiences and menu navigation.

### Example

```text
Press 1 for order details
Press 2 to confirm order
Press 3 to speak with an agent
```

---

## 9. Call Session & Event Tracking

Track real-time call state and events.

### Purpose

Provides observability and runtime tracking for calls.

### Tracked Information

* Call status
* Duration
* Answered state
* DTMF inputs
* Current flow node
* Recording path

---

## 10. Campaign Management

Create and manage outbound calling campaigns.

### Purpose

Allows batch calling workflows for marketing, notifications, reminders, and verification systems.

---

## 11. Retry & Failed Call Handling

Automatically retry failed or unanswered calls based on configurable policies.

### Purpose

Improves delivery reliability and call completion rates.

---

## 12. Agent Call Transfer

Transfer active calls to live support agents or departments.

### Purpose

Enables hybrid automated + human-assisted call handling.

---

## 13. Audio Asset Management

Upload, organize, and manage all audio assets used in flows.

### Purpose

Provides centralized control over audio playback resources.

---

## 14. Webhook & External API Integration

Trigger external APIs and webhooks during call execution.

### Purpose

Allows integration with external business systems and automation pipelines.

### Example

* CRM updates
* Order verification
* Status synchronization
* Notification systems

---

## 15. Real-time Call Monitoring

Monitor active calls and runtime events in real time.

### Purpose

Provides operational visibility for administrators and support teams.

---

## 16. Call Recording Management

Store and manage call recordings.

### Purpose

Supports compliance, auditing, training, and customer support review workflows.

---

## 17. Queue & Concurrent Call Handling

Manage concurrent outbound calls and call queues.

### Purpose

Ensures scalable and controlled outbound call execution.

---

## 18. FastAGI Runtime Execution

Execute dynamic call logic through FastAGI instead of static Asterisk dialplans.

### Purpose

Keeps business logic centralized, dynamic, and scalable.

---

## 19. Call Analytics & Reporting

Generate reports and analytics for call activities and campaign performance.

### Purpose

Provides operational insights and business intelligence.

### Example Metrics

* Answer rate
* Failed calls
* Retry success
* Average call duration
* DTMF interaction rate

---

## 20. Scheduler & Automated Calling System

Schedule calls and campaigns for future execution.

### Purpose

Enables automated outbound operations based on time, events, or business triggers.

### Example

* Appointment reminders
* Payment reminders
* Promotional campaigns
* Verification calls
