## TASK_001 — Geometry foundation

**Objective:** Establish validated spherical geometry independently of image processing.

**Delivered:** Typed coordinate contracts, great-circle calculations, radiant comparison, tests, CI and initial documentation.

**Validation:** 18 tests passed; Black, Ruff, pre-commit and package build passed.

**Key decisions:**
- Ordered trails encode observed motion.
- Proximity and directional consistency remain separate.
- Degenerate great circles fail explicitly.

**Remaining limitations:** No pixel/WCS ingestion or propagated uncertainty.
