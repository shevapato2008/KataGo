import os
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_NAME = "config.yaml"


class ModelConfig(BaseModel):
    path: str
    url: Optional[str] = None
    auto_download: bool = False
    sha256: Optional[str] = None


class KataGoConfig(BaseModel):
    path: str
    config_path: str
    model: ModelConfig
    human_model: Optional[ModelConfig] = None
    additional_args: List[str] = Field(default_factory=list)
    ld_library_paths: List[str] = Field(default_factory=list)


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
    config.katago.model.path = _resolve_path(base_dir, config.katago.model.path)
    if config.katago.human_model:
        config.katago.human_model.path = _resolve_path(base_dir, config.katago.human_model.path)
    config.katago.ld_library_paths = [
        _resolve_path(base_dir, path) for path in config.katago.ld_library_paths
    ]
    return config


def _resolve_path(base_dir: Path, value: str) -> str:
    expanded = os.path.expanduser(value)
    if os.path.isabs(expanded):
        return expanded
    return str((base_dir / expanded).resolve())
