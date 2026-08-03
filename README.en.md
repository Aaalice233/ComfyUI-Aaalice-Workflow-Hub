<p align="center">
  <img src="assets/banner.png" alt="ComfyUI-Aaalice-Workflow-Hub" width="100%">
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <strong>English</strong>
</p>

# ComfyUI-Aaalice-Workflow-Hub

A public workflow subscription, publishing, and version-management extension for ComfyUI. Authors and subscribers use the same extension. It opens from the **Workflow Hub** button in ComfyUI's top bar and does not add a sidebar.

## Features

### Subscribe and download

- Subscribe to public GitHub repositories containing `workflow-catalog.json`, then search, filter, and browse version history and release notes in one aggregated catalog.
- Every workflow version lives on the default branch under a readable category/name/version path, so repository visitors can browse, back up, or download source files without searching through Releases.
- Download and verify Release ZIPs by version. Each local version is stored as a separate workflow file, and its folder can be opened directly from the detail page.
- The detail page retains each published version's plugin dependencies, bundled images, and LoRA list. Historical LoRAs are downloaded one at a time and only on explicit request — never automatically.
- Publishing records the ComfyUI core version used to build the package; a mismatch shows a compatibility warning on the download page without blocking the download.
- Plugin dependencies produce a read-only plan. Completion first checks network access; new Git dependencies use the ComfyUI environment's Git and may clone/fetch/checkout in parallel at the locked commit, with each plugin's Python `requirements.txt` step counted and logged. Legacy Registry dependencies use ComfyUI-Manager. Both paths show source badges, progress, plugin status, install logs, and errors in one persistent view. Downloads still work when completion is unavailable.

### Publish and manage

- Capture the current ComfyUI canvas and publish through three stages: review resources, enter details, confirm publish; automatically parse a trailing `-v{version}` or `_v{version}` in the filename, fill the name and version, and keep downloaded versions as separate versioned files.
- Scans both Git plugin worktrees under `custom_nodes` and plugins reported by ComfyUI-Manager during publishing, with distinct source badges; the author can deselect unrelated plugins, while Git dependencies lock selected GitHub URLs and full commits and Manager dependencies lock Registry IDs and versions. It also handles bundled images from canvas nodes, subgraphs, and sidebar image controls. Detected LoRA references only show a warning and do not block publishing; LoRAs are not bundled or downloaded automatically.
- An optional cover image (up to 10 MiB) serves as both the workflow cover and that version's preview.
- The Manage tab is for authors with write access: edit metadata, archive, edit version changelogs, and delete versions or entire workflows. The subscription side only offers downloading and viewing.
- Sign in through GitHub App Device Flow. Credentials are stored in the system keyring when available and otherwise remain only in the current process.

### General

- Chinese or English interface following the ComfyUI locale automatically.
- Startup workflow-update toasts, real byte-level download progress, and a lightweight activity drawer.
- State and cache are isolated per ComfyUI user.

## Installation

**Option 1 (recommended)**: search for `ComfyUI-Aaalice-Workflow-Hub` in ComfyUI-Manager. The extension is published on Comfy Registry and Manager installs the Python dependencies automatically.

**Option 2 (manual)**: place this repository under `ComfyUI/custom_nodes/` and run `pip install -r requirements.txt`.

Requires ComfyUI Frontend `1.33.9+`; ComfyUI-Manager `3.0+` is supported, `4.2.1+` recommended.

## Usage

1. Restart ComfyUI and click **Workflow Hub** in the top bar. A normal click opens a non-fullscreen panel inside ComfyUI; `Shift+click` opens a separate window.
2. Subscriptions do not require GitHub sign-in. Publishing uses Device Flow when prompted.
3. Before their first publish, authors must install the public [Aaalice Workflow Hub Publisher](https://github.com/apps/aaalice-workflow-hub-publisher) GitHub App on the target repository — see the [publisher guide](docs/publisher-guide.en.md).

Runtime data is written to `workflow_hub/` inside the current ComfyUI user-data directory. Downloaded workflows are stored under:

```text
workflows/Workflow Hub/{owner}-{repo}/{workflow-id}/{name}-v{version}.json
```

## Boundaries

- Public GitHub repositories only; no private repositories, other Git services, or arbitrary download hosts.
- Never downloads models or LoRAs automatically, never installs/upgrades/downgrades nodes silently, and never executes scripts from workflow repositories.
- Published versions cannot be overwritten; downloaded local files are only removed by explicit user action.

## Documentation

- [Publisher guide (English)](docs/publisher-guide.en.md) · [作者发布指南（中文）](docs/publisher-guide.zh-CN.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Workflow catalog and package protocol](docs/protocol.md)
- [Security boundaries](docs/security.md)
- Design and decisions: [project vision](docs/vision.md) · [implemented features](docs/features.md) · [terminology and domain context](docs/context.md) · [ADR directory](docs/adr/)

## License

[MIT](LICENSE)
