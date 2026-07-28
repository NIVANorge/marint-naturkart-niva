"""Execute notebooks/02_modelling.ipynb, skipping cells tagged 'skip_training'."""

import copy
from pathlib import Path

import nbformat
from nbclient import NotebookClient

NOTEBOOK_PATH = Path(__file__).resolve().parent.parent / "notebooks" / "02_modelling.ipynb"
SKIP_TAG = "skip_training"


def main() -> None:
    nb = nbformat.read(NOTEBOOK_PATH, as_version=4)

    skip_ids = {
        cell["id"] for cell in nb.cells if SKIP_TAG in cell.get("metadata", {}).get("tags", [])
    }

    run_nb = copy.deepcopy(nb)
    run_nb.cells = [cell for cell in run_nb.cells if cell["id"] not in skip_ids]

    client = NotebookClient(run_nb, resources={"metadata": {"path": str(NOTEBOOK_PATH.parent)}})
    client.execute()

    executed_by_id = {cell["id"]: cell for cell in run_nb.cells}
    for i, cell in enumerate(nb.cells):
        if cell["id"] in executed_by_id:
            nb.cells[i] = executed_by_id[cell["id"]]

    nbformat.write(nb, NOTEBOOK_PATH)


if __name__ == "__main__":
    main()
