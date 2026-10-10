---
name: Managed development command paths
description: Working-directory constraint for custom artifact development commands.
---

Managed artifact development commands start from the artifact directory, not the workspace root.

**Why:** A custom Python command using a workspace-relative filename failed because the artifact directory was prepended again.

**How to apply:** Resolve development command paths from the registered artifact directory. Check the production run contract separately rather than assuming the same working directory.
