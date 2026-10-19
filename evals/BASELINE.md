# Baseline: Qwen2.5-Coder 3B

- Date: 2026-10-19
- Commit: 165edb0
- Runs: 6 (two sets of 3), 5 tasks each
- Success rate: 90% average (86.7% in the latest set)
- Avg steps per task: about 3.9
- JSON parse errors: 0
- Only recurring failure: 5_json_generation (3 of 6 runs)

## Update after commit de10d45 (prompt rules)

- Runs: 6, 5 tasks each
- Success rate: 93.3% average
- 5_json_generation: passed 6 of 6
- Failures (one each): 2_python_bugfix, 4_bash_automation
- Avg steps per task: about 4.0

## Update after tools fixes (search by name, unknown-tool message)

- Runs: 3 (latest set), 5 tasks each
- Success rate: 100%
- Avg steps per task: 4.2
- JSON parse errors: 0
- No failures; 4_bash_automation passed 3 of 3
