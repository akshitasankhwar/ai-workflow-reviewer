"""Allows `python -m reviewer ...` -> delegates to cli.main()."""
from .cli import main

raise SystemExit(main())
