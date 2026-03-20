from __future__ import annotations

import json
from pathlib import Path

from battinfo import Workspace


def main() -> None:
    example_root = Path(__file__).resolve().parent
    cell_type_dir = example_root / "cell-types"
    workspace_root = Path(".battinfo/manual-cell-types-demo")
    sources = sorted(
        path
        for path in cell_type_dir.glob("*.json")
        if "template" not in path.stem.lower()
    )

    workspace = Workspace(root=workspace_root, clean=True)
    loaded = workspace.load_cell_types(*sources)

    save_result = workspace.save()

    print("Loaded cell types:")
    for cell_type in loaded:
        print(f"- {cell_type.id} :: {cell_type.manufacturer} {cell_type.model}")

    print()
    print(f"Workspace root: {workspace_root}")
    print(f"Saved cell-type count: {len(save_result['cell_types'])}")
    print(f"Index path: {workspace.index_path}")

    rendered = workspace.render()
    print()
    print("Rendered canonical records:")
    print(json.dumps(rendered["cell_types"], indent=2))


if __name__ == "__main__":
    main()
