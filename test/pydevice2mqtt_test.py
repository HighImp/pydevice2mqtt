"""
Test for pydevice2mqtt module
"""

import pytest
from unittest.mock import MagicMock
import unittest.mock
from pathlib import Path

EXAMPLE_MQTT_SETTINGS = {
    "pw": "secret",
    "user": "user",
    "ip": "test",
    "port": 1883,
    "bridge_name": "TestNode",
    "discovery_prefix": "homeassistant",
    "operating_prefix": "pydevice2mqtt",
    "logging": "True"}

EXAMPLE_DATA = {str: "Test_String", int: 42, bool: True}


def create_config_file(path: Path, device_classes: dict = None) -> None:
    """
    Generate a fast config file to create mocked bridges
    :param path: filename for resulting config file
    :param device_classes: dict of classes to create ({<classname>:<classobj>})
    """
    import pydevice2mqtt
    path.unlink(missing_ok=True)
    all_devices: dict = {}
    if device_classes is None:
        device_classes = pydevice2mqtt.supported_device_classes()

    for classname, device_class in device_classes.items():

        config_requirement = device_class.get_config_req()

        device_config_dict = {}
        for entry_name, entry_type in config_requirement.items():
            device_config_dict[entry_name] = EXAMPLE_DATA[entry_type]

        all_devices[classname] = [device_config_dict]

    pydevice2mqtt.DeviceBridge.update_config(devices=all_devices,
                                             mqtt_settings=EXAMPLE_MQTT_SETTINGS,
                                             config_file=path, force_update=False)


def create_device_bridge(mocked_module, device_classes: dict = None):
    """
    Create a mocked device bridge
    :param mocked_module: mocked pydevice2mqtt module
    :param device_classes: dict of classes to create ({<classname>:<classobj>})
    :return: mocked DeviceBridge Instance
    """
    test_config_file = Path("test.yaml")
    create_config_file(path=test_config_file, device_classes=device_classes)
    return mocked_module.DeviceBridge(config_file=test_config_file)


def test_device_configuration():
    test_config_file = Path("test.yaml")
    create_config_file(test_config_file)


def test_mqtt_channels(mocker):
    import pydevice2mqtt

    mqtt_client: MagicMock = mocker.patch("pydevice2mqtt.pydevice2mqtt.mqtt.Client")
    mocker.patch("pydevice2mqtt.remote_devices.espeak")
    mocker.patch("pydevice2mqtt.remote_devices.gpiozero")

    my_bridge: pydevice2mqtt.DeviceBridge = create_device_bridge(pydevice2mqtt)

    subscribed_channels = []

    for uid, device in my_bridge.get_devices().items():

        device: pydevice2mqtt.RemoteDevice
        assert device.get_name() == EXAMPLE_DATA[str]
        for topic, function in device.get_device_topics().items():
            assert topic not in subscribed_channels
            if str(topic).endswith("state"):
                assert function is None
            elif str(topic).endswith("set") or str(topic).endswith("command"):
                assert function is not None
            subscribed_channels.append(topic)

        discover_topic, discover_info = device.get_discovery()
        assert str(discover_topic).startswith(EXAMPLE_MQTT_SETTINGS["discovery_prefix"])
        assert str(discover_topic).endswith("config")
        assert str(discover_info["state_topic"]).startswith(EXAMPLE_MQTT_SETTINGS["operating_prefix"])
        assert str(discover_info["state_topic"]).endswith("state")
    assert mqtt_client.called

def test_arbitrary_sensor(mocker):
    import pydevice2mqtt

    mqtt_client: MagicMock = mocker.patch("pydevice2mqtt.pydevice2mqtt.mqtt.Client")
    mocker.patch("pydevice2mqtt.remote_devices.espeak")
    mocker.patch("pydevice2mqtt.remote_devices.gpiozero")

    device_class = {"ArbitrarySensor": pydevice2mqtt.remote_devices.ArbitrarySensor}

    my_bridge: pydevice2mqtt.DeviceBridge = create_device_bridge(mocked_module=pydevice2mqtt,
                                                                 device_classes=device_class)

    sensor_instance: pydevice2mqtt.remote_devices.ArbitrarySensor
    expected_uid = f"ArbitrarySensor_{EXAMPLE_DATA[str]}"

    sensor_instance = my_bridge.get_devices()[expected_uid]
    assert sensor_instance.get_uid() == expected_uid
    assert sensor_instance.get_object_id() == EXAMPLE_DATA[str]
    assert sensor_instance.get_name() == EXAMPLE_DATA[str]
    assert len(mqtt_client.mock_calls) == 3
    sensor_instance.set_value(1)
    assert len(mqtt_client.mock_calls) == 4
    set_value_call_kwargs = mqtt_client.mock_calls[-1].kwargs
    assert set_value_call_kwargs["payload"] == '{"value": 1}'


if __name__ == "__main__":
    pytest.main(["-s", __file__])
