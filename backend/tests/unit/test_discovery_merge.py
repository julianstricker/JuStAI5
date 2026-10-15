from justai_sdk.ports.discovery import DiscoveredDevice

from justai.devices.discovery import merge_discoveries


def tapo() -> DiscoveredDevice:
    return DiscoveredDevice(fingerprint="tapo:1", host="192.168.0.217", manufacturer="TP-Link",
                            model="Tapo camera", protocols=["tapo", "rtsp", "onvif"],
                            suggested_driver="tapo", suggested_config={"host": "192.168.0.217"},
                            discovered_by="tapo")


def onvif() -> DiscoveredDevice:
    return DiscoveredDevice(fingerprint="onvif:1", host="192.168.0.217", name="C200", model="C200",
                            manufacturer="tp-link", protocols=["onvif"], suggested_driver="onvif",
                            suggested_config={"host": "192.168.0.217", "port": 2020}, discovered_by="onvif")


def test_vendor_driver_wins_but_real_model_is_kept_in_any_order() -> None:
    for merged in (merge_discoveries(tapo(), onvif()), merge_discoveries(onvif(), tapo())):
        assert merged.suggested_driver == "tapo"
        assert merged.suggested_config == {"host": "192.168.0.217"}
        assert merged.model == "C200" and merged.name == "C200"
        assert merged.protocols == ["onvif", "rtsp", "tapo"]


def test_mdns_only_fills_missing_fields() -> None:
    mdns = DiscoveredDevice(fingerprint="mdns:1", host="192.168.0.217", name="tapo-c200.local",
                            protocols=["mdns:_http"], discovered_by="mdns")
    merged = merge_discoveries(onvif(), mdns)
    assert merged.suggested_driver == "onvif" and merged.name == "C200"
