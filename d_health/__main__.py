"""Allow ``python -m d_health`` to dispatch to the CLI."""
from d_health.cli import main

raise SystemExit(main())
