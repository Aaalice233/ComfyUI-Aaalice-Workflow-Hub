# Publisher Guide

Open the workflow you intend to publish in ComfyUI, then launch **Workflow Hub** from the top bar. The publisher captures the current canvas and keeps its filename visible as context rather than making it a separate step.

The publisher uses one page:

1. Choose an authorized public repository. The choice is remembered. Expand **Create repository** only when needed; newly created repositories must still be added to the public [Aaalice Workflow Hub Publisher](https://github.com/apps/aaalice-workflow-hub-publisher) installation.
2. Choose an existing workflow or create one. Categories are read from the repository as a flat, single-level list, and a new category can be entered directly. New workflows only need a name; the stable ID is generated automatically.
3. Enter a `1.12` or `1.12.3` version and release notes, then review the detected custom nodes, `Load Image` assets, and Lora Manager references. Authors still choose LoRAs individually.

The publisher no longer requests a cover. Validate or publish directly from the same page. The transaction creates a draft release, uploads the ZIP and selected LoRA assets, publishes the release, and conditionally updates the catalog.

Published versions cannot be overwritten or deleted. A concurrent catalog change is merged and retried once. If the release succeeds but catalog synchronization fails, a recoverable pending publication is retained.

See the [protocol](protocol.md) and [security boundaries](security.md).
