---
name: investigate-incident
description: Run the saved order investigation program with the current request parameters and report its verified result.
---

# Run the saved investigation

1. Copy `gmail_sender`, `mailbox`, `scenario`, `mongo_database`, `logfire_project`,
   `notion_database_name` and `now_utc` from the current request into `parameters`.
   Ask for missing inputs; never substitute values from an earlier execution.
   Message, customer, trace and Notion IDs are discovered by the script.
2. Discover the following exact tool names together in one `search_tools` call
   (`queries` contains one name per item). Confirm that all are available:

   - `gmail_GMAIL_FETCH_EMAILS`
   - `gmail_GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID`
   - `gmail_GMAIL_GET_PROFILE`
   - `logfire_query_run`
   - `logfire_query_schema_reference`
   - `mongo_find`
   - `notion_NOTION_FETCH_DATABASE`
   - `notion_NOTION_FETCH_ROW`
   - `notion_NOTION_INSERT_ROW_DATABASE`
   - `notion_NOTION_QUERY_DATABASE_WITH_FILTER`
   - `notion_NOTION_SEARCH_NOTION_PAGE`
   - `notion_NOTION_UPDATE_PAGE`

3. Execute the saved file inside `run_code`. Bind `params` to a dictionary containing
   the seven current request values (serialize `now_utc` as an ISO timestamp).
   Then use this invocation; do not read the script into the model context, copy its
   body or regenerate it:

   ```python
   from pathlib import Path
   from typing import Any

   # Define params with the seven values from the current request.
   run_investigation: Any = None
   exec(Path("/skills/investigate-incident/scripts/investigate.py").read_text())
   result = await run_investigation(params)
   result
   ```

   The read-only mount exposes the packaged file inside Monty; its MCP functions
   are the tools discovered in step 2. Do not run this file with host Python or Shell.
4. If `verification.complete` is true, report the returned diagnosis in English
   using only its observed evidence. A verified empty inbox result is also complete.
5. If discovery or script execution fails, or `verification.complete` is false,
   use `read_file` to read `investigate-incident/references/direct-procedure.md`.
   Pass that relative path exactly. Do not add the `/skills/` prefix: that mount
   exists only for `Path` inside `run_code`, and `read_file` rejects it.
   Follow that procedure with the current request and observed partial results.
   First establish what actually completed: a failed call can still have written
   data. Look up the selected message's incident and read it before deciding whether
   to create, update or reuse it. Resume the missing work with the available tools
   and Code Mode; do not blindly replay the script or duplicate confirmed effects.
   Verify the final result as the procedure requires. If recovery remains blocked,
   report the blocker and confirmed partial effects rather than claiming completion.

Do not overwrite the packaged script during recovery. Script improvement and
publishing a new version remain separate from this investigation.
