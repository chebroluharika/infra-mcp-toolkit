# MongoDB Session Storage Guide

Complete guide to exploring and managing MongoDB sessions for the AI Assistant.

---

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Understanding the Database](#understanding-the-database)
3. [Interactive Login](#interactive-login)
4. [Common Queries](#common-queries)
5. [GUI Tool (MongoDB Compass)](#gui-tool-mongodb-compass)
6. [Maintenance Tasks](#maintenance-tasks)
7. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Check MongoDB Status

```bash
# Check if MongoDB is running
pgrep mongod || echo "MongoDB not running"

# Check port
lsof -i :27017
```

### Login to Database

```bash
# Connect to ai_agents database
mongosh ai_agents
```

You'll see:
```
Current Mongosh Log ID: xxx
Connecting to: mongodb://127.0.0.1:27017/ai_agents
Using MongoDB: 7.0.x

ai_agents>
```

---

## Understanding the Database

### Database Structure

```
ai_agents (database)
├── sessions (collection)        # ADK agent sessions
│   ├── session_id              # UUID
│   ├── app_name                # "qe_dashboard"
│   ├── user_id                 # "session-YYYYMMDD-HHMMSS"
│   ├── state                   # Session state dict
│   ├── events                  # Conversation events
│   ├── created_at              # Timestamp
│   └── updated_at              # Timestamp
│
└── chat_history (collection)   # UI chat messages
    ├── session_id              # "session-YYYYMMDD-HHMMSS"
    ├── release                 # "R134"
    ├── messages                # Array of chat messages
    │   ├── role                # "user" or "assistant"
    │   ├── content             # Message text
    │   ├── tools_used          # Array of tool names
    │   └── logs                # Processing logs
    ├── created_at              # Timestamp
    └── updated_at              # Timestamp
```

### Indexes

Both collections have indexes for fast queries:

**sessions collection:**
- `session_id` (unique)
- `app_name` + `user_id` (compound)
- `updated_at` (for sorting)

**chat_history collection:**
- `session_id` (unique)
- `updated_at` (for sorting)

---

## Interactive Login

### Step 1: Connect to Database

```bash
mongosh ai_agents
```

### Step 2: Explore Collections

```javascript
// Show all collections (like SHOW TABLES in SQL)
show collections

// Output:
// chat_history
// sessions
```

### Step 3: View Data

```javascript
// Count records (like SELECT COUNT(*) in SQL)
db.sessions.countDocuments({})
db.chat_history.countDocuments({})

// View all sessions (like SELECT * FROM sessions)
db.sessions.find()

// View with pretty formatting
db.sessions.find().pretty()

// View one record (like SELECT * LIMIT 1)
db.sessions.findOne()

// Exit
exit
```

---

## Common Queries

### Basic Queries

#### View Latest Sessions

```javascript
// Latest 10 sessions, sorted by update time
db.sessions.find()
  .sort({updated_at: -1})
  .limit(10)
```

#### View Latest Chat Conversations

```javascript
// Latest 5 chats with basic info
db.chat_history.find(
  {},
  {
    session_id: 1,
    release: 1,
    updated_at: 1,
    _id: 0
  }
).sort({updated_at: -1}).limit(5)
```

#### View Full Conversation

```javascript
// Get a specific chat with all messages
db.chat_history.findOne({session_id: "session-20260127-100615"})
```

### Filtering Queries

#### Find Sessions by User ID

```javascript
db.sessions.find({user_id: "session-20260127-100615"})
```

#### Find Chats by Release

```javascript
db.chat_history.find({release: "R134"})
```

#### Find Chats Containing Specific Keywords

```javascript
// Case-insensitive search in messages
db.chat_history.find({
  "messages.content": {$regex: "IRR status", $options: "i"}
})
```

#### Find Recent Sessions (last 24 hours)

```javascript
const yesterday = new Date();
yesterday.setDate(yesterday.getDate() - 1);

db.chat_history.find({
  updated_at: {$gte: yesterday}
}).sort({updated_at: -1})
```

### Aggregation Queries

#### Count Messages Across All Chats

```javascript
db.chat_history.aggregate([
  {$project: {msgCount: {$size: "$messages"}}},
  {$group: {_id: null, total: {$sum: "$msgCount"}}}
])
```

#### Get Tool Usage Statistics

```javascript
db.chat_history.aggregate([
  {$unwind: "$messages"},
  {$match: {"messages.tools_used": {$exists: true, $ne: []}}},
  {$unwind: "$messages.tools_used"},
  {$group: {_id: "$messages.tools_used", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```

#### Get Sessions with Most Messages

```javascript
db.chat_history.aggregate([
  {
    $project: {
      session_id: 1,
      release: 1,
      message_count: {$size: "$messages"},
      updated_at: 1
    }
  },
  {$sort: {message_count: -1}},
  {$limit: 10}
])
```

#### Count Chats by Release

```javascript
db.chat_history.aggregate([
  {$group: {_id: "$release", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```
