from collections import namedtuple, defaultdict

MQTTChannel = namedtuple("MQTTChannel", ["topic", "on_message"])
import json


class RemoteDevice:

    def __init__(self, device_settings, mqtt_settings):
        self.__operation_channels = defaultdict(MQTTChannel)
        self._discovery_topic = f"{mqtt_settings['discovery_prefix']}/" \
                                f"{device_settings['component']}/" \
                                f"{mqtt_settings['node_id']}/" \
                                f"{device_settings['object_id']}/"

        self._operating_topic = f"{mqtt_settings['operating_prefix']}/" \
                                f"{mqtt_settings['node_id']}/" \
                                f"{device_settings['object_id']}/"

        self._config = {"topic": self._discovery_topic + "config"}

        self._add_channel(channel_name="state_topic",
                          subchannel="state",
                          on_message=None)

        self._component = device_settings['component']
        self._config["name"] = device_settings["name"]
        # config_dict["device_class"] = self._component
        self._config["unique_id"] = device_settings["uid"]
        self._publish = mqtt_settings["f_publish"]

    def _update(self, channel_name, message):
        topic = self.__operation_channels[channel_name].topic

        if not isinstance(message, str):
            message = json.dumps(message)

        self._publish(topic=topic,
                      payload=message,
                      retain=False,
                      qos=1)

    def _add_channel(self, channel_name, subchannel, on_message=None):
        self.__operation_channels[channel_name] = MQTTChannel(self._operating_topic + subchannel, on_message)

    def get_name(self):
        return self._config["name"]

    def get_config(self):
        auto_config = {**self._config, **{name: channel.topic for (name, channel) in self.__operation_channels.items()}}
        topic = auto_config.pop("topic")

        return {"topic": topic, "message": auto_config}

    def get_topic_functions(self):
        return dict([channel for name, channel in self.__operation_channels.items() if channel.on_message is not None])


def supported_devices():
    import sys, inspect
    clsmembers = inspect.getmembers(sys.modules[__name__], inspect.isclass)
    return dict((name, obj) for name, obj in clsmembers if name != "RemoteDevice")


class RPI_GPIO(RemoteDevice):

    def __init__(self, device_settings, mqtt_settings):
        super(RPI_GPIO, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)

        self._direction = "input"
        self._pin = device_settings["pin"]
        if device_settings["component"] == "binary_sensor":
            self._direction = "input"

        elif device_settings["component"] == "switch":
            self._direction = "output"
            self._add_channel(channel_name="command_topic",
                              subchannel="set",
                              on_message=self._on_set)

    def _on_set(self, message):
        print(self.get_name(), message)

    def publish_state(self, state: bool):
        if state:
            message = "ON"
        else:
            message = "OFF"

        self._update(channel_name="state_topic",
                     message=message)


class RPI_RGB(RemoteDevice):

    def __init__(self, device_settings, mqtt_settings):
        super(RPI_RGB, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)
        self._config["schema"] = "json"
        self._config["rgb"] = "true"
        # self._config["brightness"] = "true"

        self._add_channel(channel_name="command_topic",
                          subchannel="set",
                          on_message=self._on_set)

    def _on_set(self, message):
        print(self.get_name(), message)
