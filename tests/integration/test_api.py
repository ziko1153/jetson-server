def test_registry_lists_six_stable_cameras(client) -> None:
    response = client.get("/api/v1/cameras")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 6
    assert [item["id"] for item in payload["items"]] == [f"CAM-00{index}" for index in range(1, 7)]
    front = payload["items"][0]
    assert front["name"] == "Front Camera"
    assert front["direct_stream_url"] == "rtsp://192.168.144.101:554/"
    assert front["gateway_stream_url"].endswith("/camera/CAM-001")
    assert "camera-secret" not in response.text
    assert "password" not in response.text


def test_rename_persists_across_restart(gateway_root, client) -> None:
    renamed = client.patch("/api/v1/cameras/CAM-002", json={"name": "Rear Left"})
    assert renamed.status_code == 200
    assert renamed.json()["id"] == "CAM-002"
    from fastapi.testclient import TestClient

    from app.api.router import create_app
    from app.core.config import load_settings

    with TestClient(create_app(load_settings(gateway_root))) as restarted:
        cameras = restarted.get("/api/v1/cameras").json()["items"]
        camera = next(c for c in cameras if c["id"] == "CAM-002")
    assert camera["name"] == "Rear Left"


def test_invalid_camera_and_connection_is_rejected(client) -> None:
    invalid = client.patch("/api/v1/cameras/CAM-001", json={"host": "http://bad", "path": "/../secret"})
    assert invalid.status_code == 422


def test_capabilities_stay_unknown_until_a_probe_is_requested(client) -> None:
    response = client.get("/api/v1/cameras/CAM-001/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "unknown"
    assert body["codecs"] is None
    assert body["resolutions"] is None
    assert body["configuration_supported"] is False


def test_readonly_driver_refuses_physical_changes_and_audits_them(client) -> None:
    patched = client.patch("/api/v1/cameras/CAM-003", json={"driver": "readonly_rtsp"})
    assert patched.status_code == 200
    rejected = client.put(
        "/api/v1/cameras/CAM-003/settings",
        json={"target": "physical", "width": 1280, "height": 720, "fps": 15},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "physical_configuration_unsupported"
    history = client.get("/api/v1/audit/camera-configurations")
    assert history.status_code == 200
    assert history.json()["items"][0]["success"] is False
    assert history.json()["items"][0]["camera_id"] == "CAM-003"


def test_gateway_settings_do_not_claim_to_change_the_camera(client) -> None:
    response = client.put(
        "/api/v1/cameras/CAM-004/settings",
        json={"target": "gateway", "width": 640, "height": 360, "stream_profile": "low"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied_to"] == "gateway"
    assert body["gateway_profile"] == "low"
    assert "physical camera was not changed" in body["note"]


def test_disabled_auth_allows_anonymous_calls_and_bearer_mode_does_not(gateway_root) -> None:
    from fastapi.testclient import TestClient

    from app.api.router import create_app
    from app.core.config import AuthConfig, load_settings

    settings = load_settings(gateway_root).model_copy(update={"auth": AuthConfig(mode="bearer")})
    with TestClient(create_app(settings)) as api:
        denied = api.get("/api/v1/health")
        assert denied.status_code == 401
        allowed = api.get("/api/v1/health", headers={"Authorization": "Bearer test-token"})
        assert allowed.status_code == 200
        assert allowed.json()["auth"] == "bearer"


def test_stream_start_without_media_server_is_unavailable(client) -> None:
    response = client.post("/api/v1/streams/CAM-001/start", json={"mode": "passthrough"})
    assert response.status_code == 503
    metrics = client.get("/api/v1/streams/CAM-001/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["measured_fps"] is None
    assert metrics.json()["configured_fps"] == 25
    assert "not measurements" in " ".join(metrics.json()["measurement_notes"])


def test_mosaic_validation_revision_and_presets(client) -> None:
    layouts = client.get("/api/v1/mosaic/layouts")
    assert layouts.status_code == 200
    names = {item["name"] for item in layouts.json()["items"]}
    assert {"single", "side_by_side", "three_focus", "grid_2x2", "five_3_over_2", "grid_3x2", "custom"} <= names
    current = client.get("/api/v1/mosaic")
    assert current.status_code == 200
    assert len(current.json()["tiles"]) == 6
    created = client.put(
        "/api/v1/mosaic",
        json={
            "layout": "three_focus",
            "owner": "gcs-1",
            "output": {"width": 1280, "height": 720, "fps": 15, "bitrate_kbps": 1500, "codec": "h264"},
            "camera_ids": ["CAM-001", "CAM-003", "CAM-005"],
        },
    )
    assert created.status_code == 200
    assert created.json()["revision"] == 2
    assert [tile["camera_id"] for tile in created.json()["tiles"]] == ["CAM-001", "CAM-003", "CAM-005"]
    conflict = client.put(
        "/api/v1/mosaic",
        json={
            "layout": "single",
            "output": {"width": 640, "height": 360, "fps": 10, "bitrate_kbps": 400, "codec": "h264"},
            "camera_ids": ["CAM-002"],
        },
    )
    assert conflict.status_code == 409
    replaced = client.put(
        "/api/v1/mosaic",
        json={
            "expected_revision": 2,
            "owner": "gcs-1",
            "layout": "custom",
            "output": {"width": 640, "height": 360, "fps": 10, "bitrate_kbps": 400, "codec": "h264"},
            "tiles": [
                {"camera_id": "CAM-001", "x": 0, "y": 0, "width": 640, "height": 180, "scaling": "fit"},
                {"camera_id": "CAM-002", "x": 0, "y": 200, "width": 320, "height": 180, "scaling": "fill"},
            ],
        },
    )
    assert replaced.status_code == 422
    too_big = client.put(
        "/api/v1/mosaic",
        json={
            "expected_revision": 2,
            "layout": "single",
            "output": {"width": 3840, "height": 2160, "fps": 30, "bitrate_kbps": 8000, "codec": "h264"},
            "camera_ids": ["CAM-001"],
        },
    )
    assert too_big.status_code == 422
    assert too_big.json()["error"]["code"] == "resource_limit"


def test_health_reports_platform_without_claiming_media_is_running(client) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["auth"] == "disabled"
    capabilities = client.get("/api/v1/system/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["individual_streams"] == "passthrough"
    assert capabilities.json()["media_backend"]["nvidia_encoder"] is False
