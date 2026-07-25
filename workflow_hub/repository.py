from __future__ import annotations

import json
from pathlib import PurePosixPath

from .catalog import Catalog, WorkflowProduct, WorkflowVersion, normalize_version


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _version_link(product: WorkflowProduct, version: WorkflowVersion) -> str:
    relative = version.repository_path.removeprefix(f"{product.repository_path}/")
    return f"{relative}/workflow.json"


def render_product_readme(product: WorkflowProduct) -> bytes:
    versions = sorted(product.versions, key=lambda item: normalize_version(item.version), reverse=True)
    lines = [f"# {product.name}", "", f"类别：{product.category}"]
    if product.summary:
        lines.extend(["", product.summary])
    if product.description:
        lines.extend(["", product.description])
    lines.extend(["", "## 版本", "", "| 版本 | 更新日期 | 工作流文件 | 完整安装包 |", "| --- | --- | --- | --- |"])
    for version in versions:
        published = version.published_at.date().isoformat()
        lines.append(
            f"| v{_markdown(version.version)} | {published} | "
            f"[workflow.json]({_version_link(product, version)}) | "
            f"[ZIP]({version.package.url}) |"
        )
    return ("\n".join(lines) + "\n").encode()


def render_workflows_readme(catalog: Catalog) -> bytes:
    lines = [
        f"# {catalog.repository.name}",
        "",
        catalog.repository.description or "可浏览和下载的 ComfyUI 工作流。",
        "",
        "| 类别 | 工作流 | 最新版本 |",
        "| --- | --- | --- |",
    ]
    products = sorted(
        (item for item in catalog.workflows if not item.archived),
        key=lambda item: (item.category.casefold(), item.name.casefold()),
    )
    for product in products:
        latest = max(product.versions, key=lambda item: normalize_version(item.version))
        relative = product.repository_path.removeprefix("workflows/")
        lines.append(
            f"| {_markdown(product.category)} | "
            f"[{_markdown(product.name)}]({relative}/) | "
            f"[v{_markdown(latest.version)}]({relative}/versions/v{latest.version}/workflow.json) |"
        )
    return ("\n".join(lines) + "\n").encode()


def build_projection_files(catalog: Catalog, product: WorkflowProduct) -> dict[str, bytes]:
    return {
        "workflow-catalog.json": json_bytes(catalog.model_dump(mode="json")),
        "workflows/README.md": render_workflows_readme(catalog),
        f"{product.repository_path}/README.md": render_product_readme(product),
        f"{product.repository_path}/product.json": json_bytes(
            {"schema_version": catalog.schema_version, **product.model_dump(mode="json")}
        ),
    }


def build_repository_files(
    catalog: Catalog,
    product: WorkflowProduct,
    version: WorkflowVersion,
    version_files: dict[str, bytes],
) -> dict[str, bytes]:
    files = build_projection_files(catalog, product)
    for name, content in version_files.items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"版本文件路径无效: {name}")
        files[f"{version.repository_path}/{path.as_posix()}"] = content
    return files
