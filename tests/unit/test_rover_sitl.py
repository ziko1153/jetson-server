import json
from pathlib import Path

from app.tools.rover_sitl import Process, command_is_gateway_rover, needs_restart, restore_saved_session, rover_simulators


def test_only_a_system_one_udp_rover_counts_as_the_gateway_vehicle() -> None:
    matching = "python sim_vehicle.py -v Rover -f rover-skid --sysid 1 --no-mavproxy -A --serial0=udpclient:127.0.0.1:14551"
    assert command_is_gateway_rover(matching, 14551)
    assert not command_is_gateway_rover(matching.replace("--sysid 1", "--sysid 2"), 14551)
    assert not command_is_gateway_rover(matching.replace("--sysid 1", "--sysid 10"), 14551)
    assert not command_is_gateway_rover(matching.replace("14551", "14550"), 14551)
    assert not command_is_gateway_rover(matching.replace("--no-mavproxy", "--mavproxy"), 14551)


def test_a_running_sysid_two_rover_is_restarted_and_a_matching_one_is_reused() -> None:
    state = Path("/tmp/bhimrul-rover")
    old = Process(1, 1, f"python sim_vehicle.py -v Rover -f rover-skid --sysid 2 --no-mavproxy --use-dir {state}")
    current = Process(
        2,
        2,
        f"python sim_vehicle.py -v Rover -f rover-skid --sysid 1 --no-mavproxy --use-dir {state} -A --serial0=udpclient:127.0.0.1:14551",
    )
    assert needs_restart([old], state, 14551)
    assert not needs_restart([current], state, 14551)
    assert needs_restart([current, old], state, 14551)
    assert needs_restart([], state, 14551)
    assert rover_simulators([old, current], state) == [old, current]


def test_restore_puts_back_the_direct_rover_profile(tmp_path: Path) -> None:
    sitl = tmp_path / "sitl"
    sitl.mkdir()
    calls = sitl / "calls"
    for name in ("stop-sitl.sh", "start-sitl.sh", "start-router.sh"):
        script = sitl / name
        script.write_text(f"#!/bin/sh\necho \"$0 $*\" >> {calls}\n", encoding="utf-8")
        script.chmod(0o755)
    root = tmp_path / "project"
    session = root / "data" / "simulation"
    session.mkdir(parents=True)
    (session / "sitl-session.json").write_text(
        json.dumps(
            {
                "sitl_directory": str(sitl),
                "router_was_running": True,
                "rover_was_running": True,
                "replaced_rover": True,
            }
        ),
        encoding="utf-8",
    )
    message = restore_saved_session(root)
    recorded = calls.read_text(encoding="utf-8")
    assert "stop-sitl.sh rover" in recorded
    assert "start-sitl.sh rover" in recorded
    assert "start-router.sh" not in recorded
    assert message == "Restored the direct Rover SITL profile and its router."
    assert not (session / "sitl-session.json").is_file()


def test_restore_only_restarts_the_router_when_the_rover_was_reused(tmp_path: Path, monkeypatch) -> None:
    sitl = tmp_path / "sitl"
    sitl.mkdir()
    calls = sitl / "calls"
    script = sitl / "start-router.sh"
    script.write_text(f"#!/bin/sh\necho \"$0 $*\" >> {calls}\n", encoding="utf-8")
    script.chmod(0o755)
    (sitl / "stop-sitl.sh").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    root = tmp_path / "project"
    session = root / "data" / "simulation"
    session.mkdir(parents=True)
    (session / "sitl-session.json").write_text(
        json.dumps(
            {
                "sitl_directory": str(sitl),
                "router_was_running": True,
                "rover_was_running": True,
                "replaced_rover": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.tools.rover_sitl.list_processes", lambda: [])
    message = restore_saved_session(root)
    assert "start-router.sh" in calls.read_text(encoding="utf-8")
    assert message == "Restored the SITL router."
    assert not (session / "sitl-session.json").is_file()
