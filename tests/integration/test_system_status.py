"""System status keeps the existing route and adds vehicle health."""


def test_system_status_includes_host_and_vehicle_sections(client) -> None:
    first = client.get("/api/v1/system/status")
    second = client.get("/api/v1/system/status")
    assert first.status_code == 200
    body = second.json()
    assert body["camera_count"] == 6
    assert body["cameras"]["media_server"] == "stopped"
    if body["host"]["system"] == "Darwin":
        assert body["host"]["temperature_c"] is None
        assert body["host"]["gpu_percent"] is None
        assert body["host"]["nvidia_metrics"] == "unavailable"
    assert body["host"]["memory"]["total_bytes"] > 0
    assert body["mavlink"]["enabled"] is False
    assert body["mavlink"]["running"] is False
    assert body["rcwm"]["enabled"] is False
    assert body["esp32"]["connected"] is False
    assert body["rcwm"]["positions"] == "estimates"
    assert body["rcwm"]["software_stop_is_hardware_estop"] is False
