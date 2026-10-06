"""Registry of the public datasets and a cached downloader."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .settings import RAW_DIR

log = logging.getLogger(__name__)

USER_AGENT = "global-disease-surveillance/1.0 (student research project)"


@dataclass(frozen=True)
class Source:
    key: str
    filename: str
    url: str
    provider: str
    licence: str


SOURCES: dict[str, Source] = {
    s.key: s
    for s in [
        Source(
            "covid19",
            "who_covid19_weekly.csv",
            "https://srhdpeuwpubsa.blob.core.windows.net/whdh/COVID/WHO-COVID-19-global-data.csv",
            "World Health Organization - COVID-19 dashboard",
            "CC BY 4.0",
        ),
        Source(
            "mpox",
            "owid_mpox.csv",
            "https://catalog.ourworldindata.org/explorers/who/latest/monkeypox/monkeypox.csv",
            "Our World in Data, from WHO mpox surveillance",
            "CC BY 4.0",
        ),
        Source(
            "dengue",
            "opendengue_national_v1_3.zip",
            "https://raw.githubusercontent.com/OpenDengue/master-repo/main/data/releases/V1.3/National_extract_V1_3.zip",
            "OpenDengue v1.3 (Clarke et al., 2024)",
            "CC BY 4.0",
        ),
        Source(
            "cholera_cases",
            "gho_cholera_cases.json",
            "https://ghoapi.azureedge.net/api/CHOLERA_0000000001",
            "WHO Global Health Observatory",
            "CC BY-NC-SA 3.0 IGO",
        ),
        Source(
            "measles_cases",
            "gho_measles_cases.json",
            "https://ghoapi.azureedge.net/api/WHS3_62",
            "WHO Global Health Observatory",
            "CC BY-NC-SA 3.0 IGO",
        ),
        Source(
            "countries",
            "ne_50m_admin_0_countries.geojson",
            "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson",
            "Natural Earth 1:50m admin-0 countries",
            "Public domain",
        ),
    ]
}


def path_for(key: str) -> Path:
    return RAW_DIR / SOURCES[key].filename


def download(key: str, *, force: bool = False, retries: int = 3) -> Path:
    """Fetch one source into data/raw (no-op when already cached)."""
    src = SOURCES[key]
    dest = path_for(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        log.info("cached   %s", dest.name)
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with requests.get(src.url, stream=True, timeout=180, headers={"User-Agent": USER_AGENT}) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        fh.write(chunk)
            tmp.replace(dest)
            log.info("fetched  %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)
            return dest
        except requests.RequestException as exc:
            log.warning("attempt %d/%d failed for %s: %s", attempt, retries, src.key, exc)
            time.sleep(5 * attempt)
    raise RuntimeError(f"could not download {src.url}")


def download_all(force: bool = False) -> dict[str, Path]:
    return {key: download(key, force=force) for key in SOURCES}
