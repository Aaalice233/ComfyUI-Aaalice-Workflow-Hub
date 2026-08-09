<p align="center">
  <img src="assets/banner.png" alt="ComfyUI-Aaalice-Workflow-Hub" width="100%">
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <strong>English</strong>
</p>

# ComfyUI-Aaalice-Workflow-Hub

A public workflow subscription, publishing, and version-management extension for ComfyUI. Authors and subscribers use the same extension, opened from the **Workflow Hub** button in ComfyUI's top bar.

## ✨ Features

### 📥 Subscribe and download

- Subscribe to public GitHub repositories containing `workflow-catalog.json`; search, filter, and browse version history and changelogs in one aggregated catalog.
- Download and verify workflow packages by version: workflows go to the current user's `workflows/`, bundled images go to `input/` with references untouched; downloaded files can be opened in their folder or loaded into the current canvas with their native ComfyUI file identity and filename preserved.
- Native ComfyUI update notifications (silent checks every 4 hours by default, with a configurable on/off switch and 1–168 hour interval); each new version triggers one native toast, and undownloaded updates keep a badge on the toolbar button.
- A preflight check compares core and plugin dependencies before downloading; differences are explained in a dialog, and you can skip the check or synchronize plugins and recheck. The core is never modified automatically.
- One-click plugin completion: Git dependencies install at their locked commits with `requirements.txt` handled automatically, while legacy Registry dependencies go through ComfyUI-Manager. Progress, per-plugin logs, and errors stay in one view, and downloads still work when completion is unavailable.

### 📤 Publish and manage

- Publish directly from the current canvas through four guided stages: review resources, enter details, confirm, and complete. Version numbers are parsed from filenames automatically.
- Git plugin worktrees under `custom_nodes` are scanned and locked to GitHub URLs and full commits, with unrelated plugins deselectable. Bundled images are packaged automatically. LoRA references only trigger a warning and are never bundled or downloaded.
- Optional cover image (up to 10 MiB), used as both the workflow cover and the version preview.
- The Manage tab supports editing metadata, archiving, editing changelogs, and deleting versions or entire workflows. Changelogs can be imported directly from a local Markdown file. Every operation shows staged progress, logs, and results in the Activity panel, and history can be cleaned up.
- Sign in through GitHub Device Flow; credentials prefer the system keyring.

### 🌐 General

- Chinese or English interface following the ComfyUI locale automatically.
- Automatically adapts to the Aki launcher's Git/PyPI mirrors, detects the PortableGit bundled with comfyui-xiao, and inherits the Windows system proxy.
- State and cache are isolated per ComfyUI user.

## 📦 Installation

**Option 1 (recommended)**: search for `ComfyUI-Aaalice-Workflow-Hub` in ComfyUI-Manager; Python dependencies are installed automatically.

**Option 2 (manual)**: place this repository under `ComfyUI/custom_nodes/` and run `pip install -r requirements.txt`.

Requires ComfyUI Frontend `1.33.9+`; ComfyUI-Manager `3.0+` is supported, `4.2.1+` recommended.

## 🚀 Usage

1. Restart ComfyUI and click **Workflow Hub** in the top bar. A normal click opens the panel inside ComfyUI; `Shift+click` opens a separate window.
2. Subscriptions do not require GitHub sign-in; publishing uses Device Flow when prompted.
3. Before their first publish, authors must install the public [Aaalice Workflow Hub Publisher](https://github.com/apps/aaalice-workflow-hub-publisher) GitHub App on the target repository — see the [publisher guide](docs/publisher-guide.en.md).

Downloaded files:

```text
user/<current-user>/workflows/<name>-v<version>.json
input/<original-workflow-image-reference>
```

## ⚠️ Boundaries

- Public GitHub repositories only; no private repositories, other Git services, or arbitrary download hosts.
- Never downloads models or LoRAs automatically, never installs/upgrades/downgrades nodes silently, and never executes scripts from workflow repositories.
- Published versions cannot be overwritten; downloaded local files are only removed by explicit user action.

## 📚 Documentation

- [Publisher guide (English)](docs/publisher-guide.en.md) · [作者发布指南（中文）](docs/publisher-guide.zh-CN.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Workflow catalog and package protocol](docs/protocol.md)
- [Security boundaries](docs/security.md)

## 📄 License

[MIT](LICENSE)
