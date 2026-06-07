"""Configuration models and path helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class KometaConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    config_path: NonEmptyStr | None = None


class DatedConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kometa_destination: NonEmptyStr = Field(
        validation_alias=AliasChoices("kometa_destination", "kometa_target")
    )
    letterboxd_prefix: str = ""
    plex_prefix: str = ""
    days_before: int = 0
    collection_extra: dict[str, object] = Field(default_factory=dict)
    extended_extra: dict[str, object] = Field(default_factory=dict)


class TaggedConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tag: str = ""
    extra: dict[str, object] = Field(default_factory=dict)


class ShowdownConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    showdown_json: NonEmptyStr
    library: str | None = None
    threshold: int = Field(default=4, ge=1)
    sort: Literal["matches_desc", "matches_asc", "none"] = "matches_desc"
    window: int = Field(default=5, ge=1)
    label: NonEmptyStr = "Showdown Spotlight"
    state_file: NonEmptyStr | None = None
    asset_directory: NonEmptyStr | None = None
    kometa_destination: NonEmptyStr | None = None


class RandomCollectionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: NonEmptyStr
    url: NonEmptyStr
    count: int = Field(ge=0)
    seed: NonEmptyStr
    period: Literal["monthly"] = "monthly"
    sync_mode: str = "sync"
    collection_order: str | None = None
    show_missing: bool | None = True
    radarr_add_missing: bool | None = None
    radarr_folder: NonEmptyStr | None = None
    radarr_tag: NonEmptyStr | list[NonEmptyStr] | None = None
    radarr_search: bool | None = None
    extra: dict[str, object] = Field(default_factory=dict)

    def kometa_extra(self) -> dict[str, object]:
        direct_fields = {
            "radarr_add_missing": self.radarr_add_missing,
            "radarr_folder": self.radarr_folder,
            "radarr_tag": self.radarr_tag,
            "radarr_search": self.radarr_search,
            "show_missing": self.show_missing,
        }
        if self.radarr_add_missing is True and self.radarr_search is None:
            direct_fields["radarr_search"] = True
        payload = {
            key: value for key, value in direct_fields.items() if value is not None
        }
        payload.update(self.extra)

        if self.model_extra:
            for key, value in self.model_extra.items():
                if value is not None:
                    payload[key] = value

        return payload


class RandomConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    collections: list[RandomCollectionConfig] = Field(default_factory=list)
    kometa_destination: NonEmptyStr | None = None


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: NonEmptyStr | None = None
    request_timeout: int = Field(default=30, ge=1)
    lists_cache: NonEmptyStr | None = None
    refresh_lists: bool = False
    kometa: KometaConfig = Field(default_factory=KometaConfig)
    dated: DatedConfig | None = None
    tagged: TaggedConfig = Field(default_factory=TaggedConfig)
    showdown: ShowdownConfig | None = None
    random: RandomConfig = Field(default_factory=RandomConfig)

    @model_validator(mode="after")
    def validate_workflow_config(self) -> AppConfig:
        if self.showdown is not None and self.kometa.config_path is None:
            raise ValueError("showdown requires kometa.config_path")
        if (self.dated is not None or self.tagged.tag) and self.username is None:
            raise ValueError("username is required for dated or tagged workflows")
        needs_default_destination = bool(self.tagged.tag or self.random.collections)
        if (
            self.dated is None
            and needs_default_destination
            and self.random.kometa_destination is None
        ):
            raise ValueError(
                "tagged/random workflows require dated.kometa_destination "
                "or random.kometa_destination"
            )
        return self


def load_config(path: Path) -> AppConfig:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return AppConfig.model_validate(payload)


def resolve_path(raw: str | Path | None, base_path: Path) -> Path | None:
    if raw is None:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (base_path / candidate).resolve()
    return candidate
