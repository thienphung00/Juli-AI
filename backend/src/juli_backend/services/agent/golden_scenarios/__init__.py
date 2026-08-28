"""Golden scenarios: capture, validate, and replay (issue #1311, ADR-084 d.2).

Public interface:

```python
from juli_backend.services.agent.golden_scenarios import (
    GoldenScenario,
    load_scenario,
    capture_run_as_scenario,
    seed_replay_run,
    append_continuation,
)
```

- `GoldenScenario` — schema for a captured scenario
- `load_scenario(path)` — load scenario from JSON file
- `capture_run_as_scenario(session, run_id)` — capture a real run
- `seed_replay_run(session, run_id, scenario)` — seed events for replay
- `append_continuation(session, run_id, option_id, scenario)` — append decision outcome
"""

from juli_backend.services.agent.golden_scenarios.capture import (
    capture_run_as_scenario,
)
from juli_backend.services.agent.golden_scenarios.replay import (
    append_continuation,
    seed_replay_run,
)
from juli_backend.services.agent.golden_scenarios.scenarios import (
    GoldenScenario,
    load_scenario,
)

__all__ = [
    "GoldenScenario",
    "load_scenario",
    "capture_run_as_scenario",
    "seed_replay_run",
    "append_continuation",
]
