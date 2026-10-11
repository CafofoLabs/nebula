from pathlib import Path
import tomllib

root = Path(__file__).resolve().parents[1]
project = tomllib.loads((root / "nebula.toml").read_text())["project"]["name"]
release = (root / "VERSION").read_text().strip()
extensions = ["myst_parser"]
html_theme = "sphinx_rtd_theme"
exclude_patterns = ["_build", "assets", "**/.DS_Store"]
myst_heading_anchors = 3
