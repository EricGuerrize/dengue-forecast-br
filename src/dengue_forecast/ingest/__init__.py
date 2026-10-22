"""Pipelines de ingestão bronze."""

from dengue_forecast.ingest.ibge import ingest_ibge
from dengue_forecast.ingest.infodengue import ingest_infodengue
from dengue_forecast.ingest.inmet import ingest_inmet
from dengue_forecast.ingest.sinan import ingest_sinan

__all__ = ["ingest_ibge", "ingest_infodengue", "ingest_inmet", "ingest_sinan"]
