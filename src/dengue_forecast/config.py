"""Configuração central do projeto (caminhos e parâmetros de rede)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_repo_root(start: Path | None = None) -> Path:
    """Sobe diretórios até achar pyproject.toml (ou usa CWD)."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return cur


class Settings(BaseSettings):
    """Settings carregáveis via env (`DFC_*`)."""

    model_config = SettingsConfigDict(env_prefix="DFC_", env_file=".env", extra="ignore")

    repo_root: Path = Field(default_factory=find_repo_root)
    data_dir: Path | None = None
    warehouse_path: Path | None = None
    http_timeout_s: float = 60.0
    http_max_retries: int = 5
    rate_limit_rps: float = 2.0
    user_agent: str = "dengue-forecast-br/0.1 (+https://github.com/EricGuerrize/dengue-forecast-br)"

    @property
    def root(self) -> Path:
        return self.repo_root

    @property
    def data(self) -> Path:
        return self.data_dir or (self.root / "data")

    @property
    def bronze(self) -> Path:
        return self.data / "bronze"

    @property
    def sample(self) -> Path:
        return self.data / "sample"

    @property
    def artifacts(self) -> Path:
        return self.data / "artifacts"

    @property
    def forecast(self) -> Path:
        return self.data / "forecast"

    @property
    def warehouse(self) -> Path:
        return self.warehouse_path or (self.data / "warehouse.duckdb")


def get_settings() -> Settings:
    return Settings()
