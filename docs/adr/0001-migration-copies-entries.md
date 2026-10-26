# Migrating or scheduling a Task creates a new Entry

When a Task is migrated or scheduled, we create a new Open Entry at the destination and leave the original where it was, marked Migrated (>) or Scheduled (<) and linked to its successor. We chose this over moving the row and incrementing a counter because past Daily Logs should stay a truthful history, as on paper. The Migration Count then comes from the length of the chain, not from a separately maintained number. As a result, Nested Notes are re-parented onto the newest copy, and every query for "current" Tasks must skip non-Open copies.
