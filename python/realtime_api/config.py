import os
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

DEFAULT_CONFIG_NAME = "config.yaml"

# Mapping from mode name to config file name
MODE_CONFIG_MAP = {
    "server": "config.yaml",
    "sbc": "config.sbc.yaml",
}


class ModelConfig(BaseModel):
    path: str
    url: Optional[str] = None
    auto_download: bool = False
    sha256: Optional[str] = None


class NamedModelConfig(ModelConfig):
    name: str
    human_model: Optional[ModelConfig] = None
    # Optional per-model extra CLI args, APPENDED to the katago-level additional_args
    # for THIS model only. This is the real lever for splitting the two nets across
    # devices (e.g. ["-override-config", "cudaDeviceToUseThread0=1"]); empty by default,
    # so behavior is unchanged unless a config opts in.
    additional_args: List[str] = Field(default_factory=list)


class KataGoConfig(BaseModel):
    path: str
    config_path: str
    models: List[NamedModelConfig] = Field(default_factory=list)
    default_model: Optional[str] = None
    # Legacy single-model accessors: accepted as INPUT (old yaml) and always kept
    # mirroring the default model as OUTPUT, so pre-existing readers keep working.
    model: Optional[ModelConfig] = None
    human_model: Optional[ModelConfig] = None
    additional_args: List[str] = Field(default_factory=list)
    ld_library_paths: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _reject_mixed_schema(cls, data):
        # Detect the schema FORM from raw-input KEY PRESENCE (an after-validator cannot
        # distinguish an omitted `models` key from an explicit `models: []`). Reject any
        # ambiguous/partially-migrated config up front.
        if isinstance(data, dict):
            has_models = "models" in data
            has_legacy = "model" in data or "human_model" in data
            if has_models and has_legacy:
                raise ValueError(
                    "katago config must not mix 'models' with legacy 'model'/'human_model'; use one form"
                )
            if has_models and not data.get("models"):
                raise ValueError("katago.models, when present, must be a non-empty list")
        return data

    @model_validator(mode="after")
    def _normalize_models(self) -> "KataGoConfig":
        # By here the before-validator guarantees exactly one form: legacy (`model`, no
        # `models` key) OR new (non-empty `models`, no legacy fields).
        if not self.models:
            # Legacy form: wrap the single model into a one-element list named "default".
            # This is the ONLY branch that synthesizes a default entry.
            if self.model is None:
                raise ValueError("katago config must define either 'models' or a legacy 'model'")
            self.models = [
                NamedModelConfig(
                    name="default",
                    path=self.model.path,
                    url=self.model.url,
                    auto_download=self.model.auto_download,
                    sha256=self.model.sha256,
                    human_model=self.human_model,
                )
            ]
            self.default_model = "default"
            return self
        # New form: require an explicit default_model (do NOT silently pick the first
        # element — reordering the yaml would otherwise silently change legacy routing).
        names = [m.name for m in self.models]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate model names in katago.models: {names}")
        if self.default_model is None:
            raise ValueError("katago.default_model is required when 'models' is supplied")
        if self.default_model not in names:
            raise ValueError(f"default_model '{self.default_model}' not in models {names}")
        default = next(m for m in self.models if m.name == self.default_model)
        # Mirror the default onto the legacy accessors so pre-existing readers keep working.
        self.model = ModelConfig(
            path=default.path, url=default.url, auto_download=default.auto_download, sha256=default.sha256
        )
        self.human_model = default.human_model
        return self


class ApiConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = True


class AppConfig(BaseModel):
    katago: KataGoConfig
    api: ApiConfig = ApiConfig()


def get_default_config_path() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return str(repo_root / DEFAULT_CONFIG_NAME)


def get_config_path_for_mode(mode: str) -> str:
    config_name = MODE_CONFIG_MAP.get(mode)
    if not config_name:
        valid = ", ".join(sorted(MODE_CONFIG_MAP))
        raise ValueError(f"Unknown mode '{mode}'. Valid modes: {valid}")
    repo_root = Path(__file__).resolve().parents[2]
    return str(repo_root / config_name)


def load_config(path: Optional[str] = None) -> AppConfig:
    config_path = path or os.getenv("KATAGO_CONFIG_FILE") or get_default_config_path()
    config_file = Path(config_path).expanduser()
    if not config_file.is_file():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with config_file.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    config = AppConfig.model_validate(data)

    base_dir = config_file.resolve().parent
    config.katago.path = _resolve_path(base_dir, config.katago.path)
    config.katago.config_path = _resolve_path(base_dir, config.katago.config_path)
    for m in config.katago.models:
        m.path = _resolve_path(base_dir, m.path)
        if m.human_model:
            m.human_model.path = _resolve_path(base_dir, m.human_model.path)
    # keep the legacy accessors pointing at the (now resolved) default model
    default = next(m for m in config.katago.models if m.name == config.katago.default_model)
    if config.katago.model:
        config.katago.model.path = default.path
    if config.katago.human_model and default.human_model:
        config.katago.human_model.path = default.human_model.path
    config.katago.ld_library_paths = [
        _resolve_path(base_dir, path) for path in config.katago.ld_library_paths
    ]
    return config


def _resolve_path(base_dir: Path, value: str) -> str:
    expanded = os.path.expanduser(value)
    if os.path.isabs(expanded):
        return expanded
    return str((base_dir / expanded).resolve())
