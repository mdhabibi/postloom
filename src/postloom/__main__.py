"""``python -m postloom``: what the desktop shortcuts run."""

try:
    from postloom.interfaces.cli.main import main
except Exception:  # broken install: no terminal may show this, so say it in a dialog
    import traceback

    from postloom.interfaces.desktop.shortcuts import record_failure, tell

    log = record_failure(traceback.format_exc())
    tell(
        "postloom could not start",
        f"Part of postloom didn't load. Running the install line again usually fixes this. "
        f"Details: {log}",
    )
    raise SystemExit(1) from None

raise SystemExit(main())
