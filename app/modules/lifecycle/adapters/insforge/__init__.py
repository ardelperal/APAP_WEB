"""InsForge adapter package for the lifecycle slice (LIFECYCLE-03, PR-B).

The InsForge transport is the only vendor currently wired into
the slice; the SQL builders + the port implementation live under
this namespace so the migration to the legacy Access adapter
(when it lands) is a parallel package, not a refactor.
"""
