# Publisher Guide

Open the workflow you intend to publish in ComfyUI, then launch **Workflow Hub** from the top bar. The publisher captures the current canvas and keeps its filename visible as context rather than making it a separate step.

The publisher uses three focused stages:

1. **Review resources**: inspect the detected ComfyUI core version, ComfyUI-Manager plugin packages, images referenced by canvas nodes, subgraphs, and sidebar image controls, and Lora Manager references. The server reads the core version and it cannot be edited manually. Detected LoRA references show a warning only; they do not block continuing or publishing, and LoRAs are not bundled or downloaded automatically.
2. **Enter details**: the publisher restores the last public repository, or selects the first available repository when no valid choice is saved; when the current canvas filename ends in `-v0.1` or `_v0.1`, the publisher automatically parses and fills the workflow name and version; then enter the required flat category, name, `1.12` or `1.12.3` version, and release notes. A matching category and name publish a new version of the existing workflow; otherwise a new workflow is created. The stable ID is handled automatically. An optional cover image (PNG, WebP, or JPEG up to 10 MiB) serves as both the workflow card cover and that version's preview; publishing a version without one keeps the existing cover.
3. **Confirm publish**: review the repository, workflow, version, cover, core, and resource counts before validating or publishing.

Create a repository from the second stage only when needed; newly created repositories must still be added to the public [Aaalice Workflow Hub Publisher](https://github.com/apps/aaalice-workflow-hub-publisher) installation. The cover is optional; workflows without one show a placeholder in the hub. The transaction creates a draft release, uploads the ZIP, publishes the release, then atomically commits the category/name/version archive, product metadata, README files, and root catalog.

Published versions cannot be overwritten. Deleting a version or an entire workflow requires explicit confirmation and also removes the matching Releases, tags, and repository directories. A concurrent repository change is merged and retried once. If the release succeeds but the repository commit fails, the pending publication resumes from the generated ZIP and does not depend on the original local images.

## Managing published content

The **Manage** tab is for authors with write access to a repository: after selecting a repository you can edit workflow metadata (renaming or re-categorizing migrates the repository directory in one atomic commit), archive or unarchive, edit any version's changelog (which also rewrites the Release notes), and delete a single version or an entire workflow. Deleting the last version removes the workflow entirely; subscribers' downloaded local copies are not affected. The subscription detail only offers downloading and viewing, with no repository operations.

Plugin dependencies are listed directly from all Manager plugin packages installed for the current user. The author must deselect entries unrelated to the workflow. Raw node types are never published as plugin names.

GitHub clones used for local development are handled in two ways:

- If Manager reports a `cnr_id`, the catalog records that Registry ID. The UI shows the local Git revision to the author, but the commit is not pinned as an installable version; regular users install an available release through Manager.
- Without a `cnr_id`, the catalog records a manual GitHub dependency and preserves the repository URL because Manager has no Registry identity ordinary users can install.

See the [protocol](protocol.md) and [security boundaries](security.md).
