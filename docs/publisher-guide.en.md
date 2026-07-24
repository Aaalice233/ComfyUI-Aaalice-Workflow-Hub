# Publisher Guide

1. In **Publish**, choose the current canvas or a saved workflow in the current ComfyUI user directory.
2. Sign in to GitHub and choose an authorized public repository. Install the public [Aaalice Workflow Hub Publisher](https://github.com/apps/aaalice-workflow-hub-publisher) and add newly created repositories to its installation.
3. Enter an immutable workflow ID, display metadata, a `1.12` or `1.12.3` version, and release notes.
4. Review node dependencies. Use a Registry ID and tested version when mapped; mark unmatched dependencies with `manual: true`.
5. Declare models manually with name, type, filename, source URL, and an optional SHA-256.
6. Validate, then publish. The transaction creates a draft release, uploads the ZIP, publishes the release, and conditionally updates the catalog.

Published versions cannot be overwritten or deleted. A concurrent catalog change is merged and retried once. If the release succeeds but catalog synchronization fails, a recoverable pending publication is retained.

See the [protocol](protocol.md) and [security boundaries](security.md).
