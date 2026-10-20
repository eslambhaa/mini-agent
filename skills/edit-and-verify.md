# Skill draft: edit-and-verify

Pattern seen 58 times in successful tasks: read_file -> edit_file -> run_bash (47x); search_files -> edit_file -> run_bash (9x); run_bash -> edit_file -> run_bash (2x)

## When to use
When the task asks to change an existing file and check that it still works.

## Steps
1. Find the file (search_files by name or content) or read it (read_file).
2. Change the exact lines with edit_file, keeping old_text unique.
3. Run the file with run_bash to verify the change.

## Status
DRAFT. Waiting for user approval before moving to skills/.
