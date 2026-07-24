<p align="center">
  <img src="assets/banner.png" alt="ComfyUI-Aaalice-Workflow-Hub" width="100%">
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <strong>English</strong>
</p>

# ComfyUI-Aaalice-Workflow-Hub

A public workflow subscription, publishing, and version-management extension for ComfyUI. Authors and subscribers use the same extension. It opens from the **Workflow Hub** button in ComfyUI's top bar and does not add a sidebar.

## Version 1.0 capabilities

- Subscribe to public GitHub repositories that contain `workflow-catalog.json`, then browse version history, release notes, node dependencies, and model declarations.
- Download and verify Release packages by version. Every version is stored as a separate workflow file, never overwrites an older version, and can be revealed in the system file manager.
- Upload a local JSON workflow file, validate it through a guided flow, and publish it as a GitHub Release.
- Sign in through GitHub App Device Flow. Credentials are stored in the system keyring when available and otherwise remain only in the current process.
- Build custom-node dependency plans and, after explicit confirmation, send install, upgrade, or specifically selected downgrade tasks to ComfyUI-Manager in sequence.
- Use a Chinese or English interface with startup workflow-update toasts, real byte-level download progress, a lightweight activity drawer, and per-ComfyUI-user state and cache isolation.

Models are declared and displayed but never downloaded automatically. The extension supports public GitHub repositories only; it does not support private repositories, other Git services, or arbitrary download hosts. It never changes the node environment silently and has not been published to Comfy Registry.

## Installation and usage

1. Place this repository under `ComfyUI/custom_nodes/` and install the Python dependencies declared in `pyproject.toml`.
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
