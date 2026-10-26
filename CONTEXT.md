# Dots & Dashes

A personal, keyboard-first bullet journal. Its core job is task management through bullet journal rituals, with forward planning and light notes as secondary jobs.

## Language

### Entries

**Entry**:
A single classified line in the journal: a Task, an Event or a Note.
_Avoid_: Item, bullet, record

**Task**:
An Entry representing something to do; the only kind of Entry that has a Task State.
_Avoid_: To-do, action item

**Event**:
An Entry representing something that happens on a particular day.
_Avoid_: Appointment, meeting

**Note**:
An Entry holding information or a reflection; it can stand alone or be nested under one Task or Event.
_Avoid_: Comment, memo

**Nested Note**:
A Note attached to a Task or Event. Nesting is exactly one level deep.

**Signifier**:
An optional marker on an Entry that adds emphasis. An Entry can carry both: **Priority** (`*`) and **Inspiration** (`!`).
_Avoid_: Tag, flag, label

**Prefix**:
The leading characters typed at capture time that set an Entry's Signifiers and type (for example `*. `).

**Timed Entry**:
An Entry with a time of day. Time is always optional.

**Anchor**:
The Timed Entry nearest above an untimed Entry on the same day. The untimed Entry stays after its Anchor wherever the Anchor goes.

### Task States

**Open**: A Task not yet acted on.

**Completed** (×): A Task that is finished.
_Avoid_: Done

**Migrated** (>): A Task carried forward to the day being planned (today, or tomorrow during a night-before Daily Migration) or to the current month's task list; a new Open copy exists there.

**Scheduled** (<): A Task pushed to a later date (a later Daily Log this month, or the Future Log); a new Open copy exists there.

**Cancelled** (struck through): A Task deliberately abandoned.
_Avoid_: Dropped, deleted

**Migration Chain**:
The sequence of copies a Task leaves behind as it is migrated or scheduled. Its length is the Task's **Migration Count** (shown as `>>3`).

### Logs

**Daily Log**:
The page of Entries for one day.
_Avoid_: Day page, today view

**Monthly Log**:
The current or a past month's page: a calendar of that month's Events plus the month's task list. Months after the current one have no Monthly Log.

**Future Log**:
Entries for months after the current one, grouped by month; each may have a specific date.

### Capture and Triage

**Capture**:
Raw text jotted down quickly, not yet classified as any kind of Entry.
_Avoid_: Inbox item, draft

**Inbox**:
The holding area where Captures wait for Triage.

**Triage**:
Turning a Capture into an Entry, by reading its text with the Prefix rules, and placing it on a Daily Log, the Monthly Log or the Future Log.

### Rituals

**Daily Migration**:
Reviewing open Tasks from earlier days and deciding for each: complete, migrate, schedule or cancel. It is optional and can happen anytime.

**Day being planned**:
The day a Migration plans for, decided by the server in the User's timezone: from 18:00 it is the night before, planning tomorrow; otherwise today. Daily Migration lets the User plan the other day instead. A Task only moves forward, never back to an earlier day.

**Monthly Review**:
The ritual on the first of the month: dealing with last month's leftover Open Tasks and pulling this month's Future Log Entries into the new Monthly Log.

### People

**User**:
The single owner of the journal.

**Canary User**:
A separate synthetic User whose journal exists only for monitoring, isolated from the real one.

## Relationships

- An **Entry** lives on exactly one of: a **Daily Log**, the **Monthly Log**'s task list or the **Future Log**. A **Capture** lives only in the **Inbox**.
- An **Event** always belongs to a day, except in the **Future Log**, where its date is optional.
- A **Nested Note** follows its parent when the parent is migrated or scheduled. The original keeps only its state marker.
- **Monthly Review** marks the pulled **Future Log** Tasks **Migrated**, leaving Open copies on their day or the new Monthly Log's task list. Pulled Events and Notes have no Task State, so they just move; an undated Event waits in the review until it is given a day.
- Only **Tasks** are migrated or scheduled. Moving an **Event** just changes its date, and standalone **Notes** stay on their day.
- A **Daily Log** can exist for any date, including future dates this month, which is where Scheduled Tasks land.
- **Delete** removes an Entry or Capture that should never have existed. **Cancelled** is a recorded decision about a Task.

## Flagged ambiguities

- "Item" was used for both Inbox contents and Future Log contents. Resolved: Inbox holds **Captures**, which are unclassified. The Future Log holds **Entries**.
- "Done", "dropped" and "completed" were used for overlapping states. Resolved: **Completed** and **Cancelled**.
