"""Install the mnk Jupyter kernel with correct PROJ/GDAL env vars.

When running on JupyterHub with a conda base environment, the kernel would
otherwise inherit conflicting PROJ_DATA/GDAL_DATA paths. Running this script
via `pixi run install-kernel` bakes the pixi environment paths into kernel.json.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    subprocess.run(
        [sys.executable, "-m", "ipykernel", "install", "--user", "--name", "mnk", "--display-name", "mnk"],
        check=True,
    )

    kernel_json = Path.home() / ".local/share/jupyter/kernels/mnk/kernel.json"
    with open(kernel_json) as f:
        kernel = json.load(f)

    import site
    import pyproj

    conda_prefix = os.environ.get("CONDA_PREFIX", "")
    proj_data = os.path.join(conda_prefix, "share", "proj") if conda_prefix else pyproj.datadir.get_data_dir()
    gdal_data = os.path.join(conda_prefix, "share", "gdal") if conda_prefix else ""
    project_root = str(Path(__file__).resolve().parent.parent)
    site_packages = os.pathsep.join(site.getsitepackages())

    kernel["argv"][0] = sys.executable
    kernel["env"] = {
        "PROJ_DATA": proj_data,
        "PROJ_LIB": proj_data,
        "GDAL_DATA": gdal_data,
        "PYTHONPATH": f"{project_root}{os.pathsep}{site_packages}",
    }

    with open(kernel_json, "w") as f:
        json.dump(kernel, f, indent=1)

    print(f"Kernel installed: {kernel_json}")
    print(f"  PROJ_DATA={proj_data}")
    print(f"  GDAL_DATA={gdal_data}")


if __name__ == "__main__":
    main()
