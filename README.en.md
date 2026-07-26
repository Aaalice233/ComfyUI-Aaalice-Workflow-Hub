<p align="center">
  <img src="assets/banner.png" alt="ComfyUI-Aaalice-Workflow-Hub" width="100%">
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <strong>English</strong>
</p>

# ComfyUI-Aaalice-Workflow-Hub

A public workflow subscription, publishing, and version-management extension for ComfyUI. Authors and subscribers use the same extension. It opens from the **Workflow Hub** button in ComfyUI's top bar and does not add a sidebar.

## Current capabilities

- Subscribe to public GitHub repositories that contain `workflow-catalog.json`, then browse version history, release notes, plugin dependencies, and model declarations.
- Store every workflow version on the default branch under a readable category/name/version path, so repository visitors can browse, back up, or download source files without searching through Releases.
- Download and verify Release ZIPs by version. Releases are distribution artifacts for installable packages and optional LoRAs, while every local version remains a separate workflow file.
- Capture the current ComfyUI canvas and publish through three focused stages. The version directory, product metadata, README files, and root catalog are updated in one Git commit.
- Record the publisher's current ComfyUI core version automatically and warn subscribers on the download page when their core version does not match, without blocking the download.
- Local images referenced by `Load Image` nodes are included automatically. An optional cover image up to 10 MiB serves as both the workflow cover and that version's preview.
- The Manage tab is for authors with write access: edit metadata, archive, edit version changelogs, and delete versions or entire workflows (including the matching Releases and repository directories); the subscription side only offers downloading and viewing.
- Sign in through GitHub App Device Flow. Credentials are stored in the system keyring when available and otherwise remain only in the current process.
- Build ComfyUI plugin dependency plans and, after explicit confirmation, send install, upgrade, or specifically selected downgrade tasks to ComfyUI-Manager in sequence.
- Use a Chinese or English interface with startup workflow-update toasts, real byte-level download progress, a lightweight activity drawer, and per-ComfyUI-user state and cache isolation.

The publisher lists actual ComfyUI-Manager plugin packages rather than raw node types. When dependency mapping is incomplete, it lists enabled Manager plugins for the author to select. A Git development clone with a Registry ID remains installable by ordinary users through Manager; its local commit is not pinned as a version. The publisher also detects Lora Manager references. Authors may publish selected LoRAs as separate Release assets or clear those references from the pending workflow copy. LoRAs stay outside the main workflow package, and subscribers choose each download explicitly; they are never downloaded automatically. The extension supports public GitHub repositories only; it does not support private repositories, other Git services, or arbitrary download hosts. It never changes the plugin environment silently. The extension itself is published on Comfy Registry (publisher aaalice) and can be installed through ComfyUI-Manager.

## Installation and usage

1. Place this repository under `ComfyUI/custom_nodes/` and run `pip install -r requirements.txt`; ComfyUI-Manager handles these dependencies automatically.
2. Restart ComfyUI. Frontend `1.33.9+` is required, and Manager `4.2.1+` is recommended.
3. Click **Workflow Hub** in the top bar. A normal click opens a non-fullscreen panel inside ComfyUI; `Shift+click` opens a separate window.
4. Subscriptions do not require GitHub sign-in. Publishing uses Device Flow when prompted.

Runtime data is written to `workflow_hub/` inside the current ComfyUI user-data directory. Downloaded workflows are stored under:

```text
workflows/Workflow Hub/{owner}-{repo}/{workflow-id}/{name}-v{version}.json
```

## Documentation

- [Terminology and domain context](CONTEXT.md)
- [Project vision](docs/vision.md)
- [Implemented features](docs/features.md)
- [Workflow catalog and package protocol](docs/protocol.md)
- [Publisher guide (English)](docs/publisher-guide.en.md)
- [作者发布指南（中文）](docs/publisher-guide.zh-CN.md)
- [Security boundaries](docs/security.md)
- [Troubleshooting](docs/troubleshooting.md)
- [GitHub Device Flow and direct publishing ADR](docs/adr/0001-github-app-device-flow.md)
- [Repository archive and Release distribution ADR](docs/adr/0002-repository-archive-and-release-distribution.md)

Development checks:

```powershell
python -m unittest discover -s tests -v
Set-Location frontend
npm ci
npm test
npm run build
```

## License

[MIT](LICENSE)
