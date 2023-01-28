#!/usr/bin/env python3

import json
import logging
import os
from pathlib import Path
from typing import List, Dict

import paho.mqtt.client as mqtt
import yaml

from pydevice2mqtt.remote_devices import RemoteDevice, supported_device_classes


# def main():
#     logging.basicConfig(filename='../../All.log', filemode='w', level=logging.DEBUG)
#     dirname = os.path.dirname(__file__)
#
#     new_device: dict = {"ArbitrarySensor": [
#         {"name": "Batteriestrom1",
#          "device_class": "current",
#          "unit_of_measurement": "A",
#          "object_id": "BMP_STR1"},
#         {"name": "Batteriestrom2",
#          "device_class": "current",
#          "unit_of_measurement": "A",
#          "object_id": "BMP_STR2"},
#         {"name": "Batteriestrom3",
#          "device_class": "current",
#          "unit_of_measurement": "A",
#          "object_id": "BMP_STR3"}
#     ]}
#
#     remote_config = os.path.join(dirname, "../../test/remote_config.yaml")
#     DeviceBridge.update_config(devices=new_device, config_file=Path("../../test/remote_config.yaml"), force_update=True)
#
#     a = DeviceBridge(remote_config)
#     a.delete_devices()
#     logging.info("Enter loop!")
#     a.loop()


class DeviceBridge:
    _supported_device_classes = supported_device_classes()

    @classmethod
    def update_config(cls,
                      devices: Dict[str, List[dict]] = None,
                      config_file: Path = "mqtt_dev_config.yaml",
                      mqtt_settings: dict = None,
                      force_update: bool = False):
        """Create a config out of a dictionary.
        Only allowes to create or add devices to a config,
        to ensure that the info for removing will not be deleted

        :param devices: Configuration values for new items (see remote_devices.py for supported devices)
        :param config_file: target file name to create or update
        :param mqtt_settings: all necessary mqtt values
        (pw, user, ip, port, bridge_name, discovery_prefix, operating_prefix, loggin)
        :param force_update: allow updates on MQTT and existing Devices
        :return: Amount of added devices

        """

        config_file = Path(config_file)

        if config_file.is_file() and mqtt_settings is not None and not force_update:
            raise ValueError("MQTT Settings can not be updated for existing file.")

        complete_config: dict = {"remote_devices": {}, "mqtt_settings": {}}

        if config_file.is_file():
            with open(config_file, "r") as config_stream:
                complete_config = yaml.load(config_stream, yaml.SafeLoader)

            if force_update and mqtt_settings:
                complete_config |= mqtt_settings

        elif mqtt_settings is not None:
            needed_mqtt_keys = ["ip", "port", "bridge_name", "discovery_prefix", "operating_prefix"]
            assert all([needed_key in mqtt_settings.keys() for needed_key in needed_mqtt_keys]), \
                "Missing info in mqtt settings"
            complete_config["mqtt_settings"] |= mqtt_settings

        else:
            raise ValueError("MQTT Settings have to be set for new file creation!")

        # check if all devices provide the necessary info
        for device_class_name, device_info_list in devices.items():
            try:
                device_class: RemoteDevice = cls._supported_device_classes[device_class_name]
            except KeyError as err:
                raise AttributeError(f"Device {device_class_name} not supported") from err

            for device_info in device_info_list:
                for key, value_type in device_class.get_config_req().items():
                    try:
                        assert type(device_info[key]) == value_type
                    except [KeyError, AssertionError] as err:
                        raise AttributeError("The Device info did not provide all necessary information") from err

                if device_class_name in complete_config["remote_devices"].keys() and not force_update:
                    # check for duplicates
                    assert all(existing_device["object_id"] != device_info["object_id"]
                               for existing_device in complete_config["remote_devices"][device_class_name]), \
                        f"Found existing Device, updating {device_class_name} " \
                        f"with object_id: {device_info['object_id']} is forbidden!"

        complete_config["remote_devices"] |= devices

        with open(config_file, "w") as config_stream:
            yaml.safe_dump(complete_config, config_stream)

    def __init__(self, config_file: Path):

        super().__init__()
        with Path(config_file).open("r") as file:
            remote_description = yaml.load(file, yaml.FullLoader)

        mqtt_settings = remote_description["mqtt_settings"]
        remote_devices = remote_description["remote_devices"]

        self._devices = dict()
        self._mqtt_client = mqtt.Client()
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_message = self._on_message
        self._mqtt_client.username_pw_set(username=mqtt_settings["user"],
                                          password=mqtt_settings["pw"])

        self._mqtt_client.connect(host=mqtt_settings["ip"],
                                  port=mqtt_settings["port"],
                                  keepalive=60)

        mqtt_settings["f_publish"] = self._mqtt_client.publish

        assert set(remote_devices.keys()).issubset(set(self._supported_device_classes.keys()))
        for remote_device_class, devices in remote_devices.items():
            for device_settings in devices:
                device_settings["uid"] = self._get_uid(remote_device_class=remote_device_class,
                                                       device_settings=device_settings,
                                                       mqtt_settings=mqtt_settings)
                self._devices[device_settings["uid"]] = self._supported_device_classes[remote_device_class](
                    device_settings, mqtt_settings)

        self._subscribed_channels_dict = {}
        for topic_function_dict in [device.get_device_topics() for device in self._devices.values()]:
            self._subscribed_channels_dict.update(topic_function_dict)

        self._bridge_name = mqtt_settings["bridge_name"]
        self._node_channel = f'{mqtt_settings["operating_prefix"]}/{self._bridge_name}/#'

    def _get_uid(self, remote_device_class: str, device_settings: dict, mqtt_settings: dict):
        bridge_name = mqtt_settings['bridge_name']
        object_id = device_settings['object_id']

        uid = f"{bridge_name}_{remote_device_class}_{object_id}"
        if uid in self._devices.keys():
            raise ValueError(f"UID {uid} is already taken!")
        return uid

    def loop(self):
        self._mqtt_client.loop_forever()

    def stop(self) -> None:
        """Abort the MQTT Thread
        """
        self._mqtt_client.loop_stop()
        logging.debug("MQTT Thread Stopped")

    def start(self):
        """Thread to call the "loop forever" function
        """
        self._mqtt_client.loop_start()
        logging.debug("MQTT Thread Started")

    def _on_connect(self, client, userdata, flags, rc):
        client.subscribe(self._node_channel)

        logging.debug(f"subscribe on {self._node_channel}")

    def _on_message(self, client, userdata, msg):

        try:
            function = self._subscribed_channels_dict[msg.topic]
            if function is not None:
                logging.debug(f"Actor Message: {msg.topic} : {msg.payload.decode()}")
                function(msg.payload.decode())
            else:
                logging.debug(f"Sensor Message: {msg.topic} : {msg.payload.decode()}")
        except KeyError:
            logging.warning(f"Detect unsubscribed channel for this node: {msg.topic}")
        except Exception as error:
            logging.error(f"Catching unhandled error inside of an device: {error}")

    def configure_devices(self):
        """Register Bridge Devices by write the config in HASSIO style to the discovery channel
        """
        for uid, device in self._devices.items():
            logging.debug(f"Configure: {uid}")
            discover_info = device.get_discovery()
            self._mqtt_client.publish(topic=discover_info[0],
                                      payload=json.dumps(discover_info[1]),
                                      retain=False,
                                      qos=1)
            for key, value in discover_info["message"].items():
                logging.debug(f'{key}: "{value}"')

    def delete_devices(self):
        """Unregister all devices by flushing the Discovery Channel
        """
        for uid, device in self._devices.items():  # type: RemoteDevice
            logging.debug(f"Unlink: {uid}")
            discover_info = device.get_discovery()
            self._mqtt_client.publish(topic=discover_info[0],
                                      payload="")

    def get_devices(self):
        """Return a dict with all registered devices
        """
        return {uid: device for uid, device in self._devices.items()}
    #
    # def get_mqtt_client(self) -> mqtt.Client:
    #     """Return the MQTT Client directly, for debug and test reasons
    #     """
    #     return self._mqtt_client
