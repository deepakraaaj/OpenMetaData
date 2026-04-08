from pathlib import Path

from app.repositories.filesystem import WorkspaceRepository
from app.utils.serialization import write_json


def test_load_domain_groups_falls_back_to_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    output_dir = tmp_path / "output"
    repo = WorkspaceRepository(config_dir, output_dir)

    write_json(
        config_dir / "domain_groups" / "fleet.json",
        {
            "source_name": "fleet",
            "groups": {
                "Vehicles": ["vehicle"],
                "Trips": ["trip"],
            },
        },
    )

    groups = repo.load_domain_groups("fleet")

    assert groups == {
        "Vehicles": ["vehicle"],
        "Trips": ["trip"],
    }


def test_load_domain_groups_prefers_output_over_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    output_dir = tmp_path / "output"
    repo = WorkspaceRepository(config_dir, output_dir)

    write_json(
        config_dir / "domain_groups" / "fleet.json",
        {
            "source_name": "fleet",
            "groups": {"Config Groups": ["vehicle"]},
        },
    )
    write_json(
        output_dir / "fleet" / "domain_groups.json",
        {
            "source_name": "fleet",
            "groups": {"Output Groups": ["trip"]},
        },
    )

    groups = repo.load_domain_groups("fleet")

    assert groups == {"Output Groups": ["trip"]}
