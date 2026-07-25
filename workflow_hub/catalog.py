from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?$")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
INVALID_REPOSITORY_SEGMENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def normalize_version(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value)
    if not match:
        raise ValueError("版本必须是 major.minor 或 major.minor.patch")
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


def validate_repository_segment(value: str, label: str) -> str:
    if not value:
        raise ValueError(f"{label}不能为空")
    if len(value) > 80:
        raise ValueError(f"{label}不能超过 80 个字符")
    if value in {".", ".."} or value.endswith((".", " ")):
        raise ValueError(f"{label}不能用作仓库目录")
    if INVALID_REPOSITORY_SEGMENT.search(value):
        raise ValueError(f'{label}不能包含 <>:"/\\|?* 或控制字符')
    if value.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label}不能使用系统保留名称")
    return value


def product_repository_path(category: str, name: str) -> str:
    return f"workflows/{validate_repository_segment(category, '类别')}/{validate_repository_segment(name, '名称')}"


def version_repository_path(product_path: str, version: str) -> str:
    normalize_version(version)
    return f"{product_path}/versions/v{version}"


def prepare_publish_product(data: dict) -> dict:
    prepared = dict(data)
    category = str(prepared.get("category", "")).strip()
    name = str(prepared.get("name", "")).strip()
    workflow_id = str(prepared.get("id", "")).strip()
    prepared["category"] = category
    prepared["name"] = name
    prepared["id"] = workflow_id
    product_path = product_repository_path(category, name)
    prepared["repository_path"] = product_path
    versions = []
    for item in prepared.get("versions", []):
        version = dict(item)
        number = str(version.get("version", "")).strip()
        version["version"] = number
        version["release_tag"] = f"{workflow_id}-v{number}"
        version["repository_path"] = version_repository_path(product_path, number)
        versions.append(version)
    prepared["versions"] = versions
    return prepared


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Repository(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    author: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(default="", max_length=500)] = ""


class Asset(StrictModel):
    url: HttpUrl
    size: Annotated[int, Field(gt=0, le=268_435_456)]
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Preview(StrictModel):
    url: HttpUrl
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ComfyCompatibility(StrictModel):
    minimum: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    maximum: Annotated[str, Field(min_length=1, max_length=32)] | None = None


class NodeDependency(StrictModel):
    registry_id: Annotated[str, Field(min_length=1, max_length=150)] | None = None
    name: Annotated[str, Field(min_length=1, max_length=150)]
    version: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    required: bool = True
    manual: bool = False
    source_url: HttpUrl | None = None

    @model_validator(mode="after")
    def mapped_or_manual(self) -> "NodeDependency":
        if self.manual == (self.registry_id is not None):
            raise ValueError("依赖必须是 Registry 依赖或手动依赖之一")
        return self


class ModelDependency(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=150)]
    type: Annotated[str, Field(min_length=1, max_length=80)]
    filename: Annotated[str, Field(min_length=1, max_length=240)]
    source_url: HttpUrl
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None


class BundledInput(StrictModel):
    source: Annotated[str, Field(min_length=1, max_length=240)]
    archive: Annotated[str, Field(min_length=1, max_length=300)]
    size: Annotated[int, Field(gt=0, le=67_108_864)]
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    node_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=500)


class WorkflowVersion(StrictModel):
    version: str
    published_at: datetime
    release_tag: Annotated[str, Field(min_length=1, max_length=200)]
    changelog: Annotated[str, Field(min_length=1, max_length=20_000)]
    comfyui: ComfyCompatibility = Field(default_factory=ComfyCompatibility)
    package: Asset
    preview: Preview | None = None
    custom_nodes: list[NodeDependency] = Field(default_factory=list, max_length=500)
    inputs: list[BundledInput] = Field(default_factory=list, max_length=500)
    models: list[ModelDependency] = Field(default_factory=list, max_length=500)
    repository_path: Annotated[str, Field(min_length=1, max_length=320)]

    @field_validator("version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        normalize_version(value)
        return value


class WorkflowProduct(StrictModel):
    id: Annotated[str, Field(min_length=1, max_length=80)]
    name: Annotated[str, Field(min_length=1, max_length=80)]
    category: Annotated[str, Field(min_length=1, max_length=80)]
    summary: Annotated[str, Field(default="", max_length=300)] = ""
    description: Annotated[str, Field(default="", max_length=20_000)] = ""
    tags: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(default_factory=list, max_length=20)
    archived: bool = False
    cover: Preview | None = None
    versions: list[WorkflowVersion] = Field(default_factory=list, max_length=500)
    repository_path: Annotated[str, Field(min_length=1, max_length=240)]

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not ID_RE.fullmatch(value):
            raise ValueError("工作流 ID 只能包含小写字母、数字和单连字符")
        return value

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return validate_repository_segment(value, "名称")

    @field_validator("category")
    @classmethod
    def valid_category(cls, value: str) -> str:
        return validate_repository_segment(value, "类别")

    @model_validator(mode="after")
    def unique_versions(self) -> "WorkflowProduct":
        expected_product_path = product_repository_path(self.category, self.name)
        if self.repository_path != expected_product_path:
            raise ValueError(f"工作流仓库路径必须是 {expected_product_path}")
        normalized = [normalize_version(item.version) for item in self.versions]
        if len(normalized) != len(set(normalized)):
            raise ValueError("同一工作流不能包含规范化后相同的版本")
        for item in self.versions:
            expected = f"{self.id}-v{item.version}"
            if item.release_tag != expected:
                raise ValueError(f"Release tag 必须是 {expected}")
            expected_version_path = version_repository_path(self.repository_path, item.version)
            if item.repository_path != expected_version_path:
                raise ValueError(f"版本仓库路径必须是 {expected_version_path}")
        return self


class Catalog(StrictModel):
    schema_version: Literal[1] = 1
    repository: Repository
    workflows: list[WorkflowProduct] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_ids(self) -> "Catalog":
        ids = [item.id for item in self.workflows]
        if len(ids) != len(set(ids)):
            raise ValueError("工作流 ID 必须在仓库内唯一")
        paths = [item.repository_path.casefold() for item in self.workflows]
        if len(paths) != len(set(paths)):
            raise ValueError("同一类别下的工作流名称必须唯一")
        return self


def merge_product(catalog: Catalog, product: WorkflowProduct) -> Catalog:
    items = list(catalog.workflows)
    for index, existing in enumerate(items):
        if existing.id != product.id:
            continue
        old_versions = {normalize_version(item.version) for item in existing.versions}
        for version in product.versions:
            if normalize_version(version.version) in old_versions:
                raise ValueError(f"版本 {version.version} 已发布")
        relocated_versions = [
            version.model_copy(
                update={"repository_path": version_repository_path(product.repository_path, version.version)}
            )
            for version in existing.versions
        ]
        items[index] = existing.model_copy(
            update={
                "name": product.name,
                "category": product.category,
                "summary": product.summary,
                "description": product.description,
                "tags": product.tags,
                "archived": product.archived,
                "cover": product.cover or existing.cover,
                "repository_path": product.repository_path,
                "versions": relocated_versions + product.versions,
            }
        )
        return Catalog.model_validate(catalog.model_copy(update={"workflows": items}).model_dump(mode="json"))
    return Catalog.model_validate(catalog.model_copy(update={"workflows": items + [product]}).model_dump(mode="json"))
