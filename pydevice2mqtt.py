import json
import time

import paho.mqtt.client as mqtt
import yaml

from remote_devices import RemoteDevice, supported_devices


def main():
    a = RemoteHassio("remote_config.yaml")
    #
    # if input("Delete remote_devices?") == "y":
    #     a.delete_decices()
    #     return
    # else:
    a.configure_devices()

    # for device_name, device in a.get_devices().items():
    #     if device_name == "AutoButton":
    #         for i in range(10):
    #             device._publish_state(i % 2 == 0)
    #             time.sleep(1)

    print("Enter loop!")
    a.loop_forever()


class RemoteHassio:
    _supported_devices = supported_devices()
    _next_node_id = 0

    def __init__(self, config_file):

        with open(config_file, "r") as file:
            remote_description = yaml.load(file, yaml.FullLoader)

        mqtt_settings = remote_description["mqtt_settings"]
        remote_devices = remote_description["remote_devices"]

        self._devices = list()
        self._device_uids = list()

        self._mqtt_client = mqtt.Client()
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_message = self._on_message
        self._mqtt_client.username_pw_set(username=mqtt_settings["user"],
                                          password=mqtt_settings["pw"])

        self._mqtt_client.connect(host=mqtt_settings["ip"],
                                  port=mqtt_settings["port"],
                                  keepalive=60)

        mqtt_settings["f_publish"] = self._mqtt_client.publish

        assert set(remote_devices.keys()).issubset(set(self._supported_devices.keys()))
        for plattform, devices in remote_devices.items():
            for device_setting in devices:
                device_setting["uid"] = self._get_uid(device_setting, mqtt_settings)
                self._devices.append(
                    self._supported_devices[plattform](device_setting, mqtt_settings))

        self._subscibed_channels_dict = {}
        for topic_function_dict in [device.get_device_topics() for device in self._devices]:
            self._subscibed_channels_dict.update(topic_function_dict)

        self._node_id = mqtt_settings["node_id"]
        self._node_channel = f'{mqtt_settings["operating_prefix"]}/{self._node_id}/#'

    def _get_uid(self, device_settings, mqtt_settings):
        device_class = device_settings['component']
        node_id = mqtt_settings['node_id']
        object_id = device_settings['object_id']

        uid = f"{node_id}_{object_id}_{device_class}"
        if uid in self._device_uids:
            raise ValueError(f"UID {uid} is already taken!")
        self._device_uids.append(uid)
        return uid

    def loop_forever(self):
        self._mqtt_client.loop_forever()

    def _on_connect(self, client, userdata, flags, rc):
        client.subscribe(self._node_channel)

        print(f"subscribe on {self._node_channel}")

    def _on_message(self, client, userdata, msg):

        try:
            function = self._subscibed_channels_dict[msg.topic]
            if function is not None:
                print(f"Actor Message: {msg.topic} : {msg.payload.decode()}")
                function(msg.payload.decode())
            else:
                print(f"Sensor Message: {msg.topic} : {msg.payload.decode()}")
        except KeyError:
            print(f"Detect unsubscribed channel for this device: {msg.topic}")

    def configure_devices(self):
        for device in self._devices:  # type: RemoteDevice
            config = device.get_config()
            self._mqtt_client.publish(topic=config["topic"],
                                      payload=json.dumps(config["message"]),
                                      retain=True,
                                      qos=1)
            for key, value in config["message"].items():
                print(f'{key}: "{value}"')

    def delete_decices(self):
        for device in self._devices:  # type: RemoteDevice
            config = device.get_config()
            self._mqtt_client.publish(topic=config["topic"],
                                      payload="")

    def get_devices(self):
        return {device.get_name(): device for device in self._devices}


if __name__ == '__main__':
    main()
