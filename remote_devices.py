import json
from collections import namedtuple, defaultdict

import gpiozero

MQTTChannel = namedtuple("MQTTChannel", ["topic", "on_message"])


class RemoteDevice:

    def __init__(self, device_settings, mqtt_settings):
        self._operation_topics = defaultdict(MQTTChannel)
        self._discovery_prefix = f"{mqtt_settings['discovery_prefix']}/" \
                                 f"{device_settings['component']}/" \
                                 f"{mqtt_settings['node_id']}/" \
                                 f"{device_settings['object_id']}/"

        self._operating_prefix = f"{mqtt_settings['operating_prefix']}/" \
                                 f"{mqtt_settings['node_id']}/" \
                                 f"{device_settings['object_id']}/"

        self._config = {"topic": self._discovery_prefix + "config"}

        self._add_channel(channel_name="state_topic",
                          sub_topic="state",
                          on_message=None)

        self._component = device_settings['component']
        self._config["name"] = device_settings["name"]
        # config_dict["device_class"] = self._component
        self._config["unique_id"] = device_settings["uid"]
        self._publish = mqtt_settings["f_publish"]

    def _update(self, channel_name, message):
        topic = self._operation_topics[channel_name].topic

        if not isinstance(message, str):
            message = json.dumps(message)

        self._publish(topic=topic,
                      payload=message,
                      retain=False,
                      qos=1)

    def _add_channel(self, channel_name, sub_topic, on_message=None):
        self._operation_topics[channel_name] = MQTTChannel(self._operating_prefix + sub_topic, on_message)

    def get_name(self):
        return self._config["name"]

    def get_config(self):
        auto_config = {**self._config, **{name: channel.topic for (name, channel) in self._operation_topics.items()}}
        topic = auto_config.pop("topic")

        return {"topic": topic, "message": auto_config}

    def get_device_topics(self):
        return dict([channel for name, channel in self._operation_topics.items()])

def supported_devices():
    import sys, inspect
    clsmembers = inspect.getmembers(sys.modules[__name__], inspect.isclass)
    return dict((name, obj) for name, obj in clsmembers if name != "RemoteDevice")


class RPI_GPIO(RemoteDevice):

    def __init__(self, device_settings, mqtt_settings):
        super(RPI_GPIO, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)

        self._gpiozero_device = None
        self._inverted = device_settings["inverted"]
        if device_settings["component"] == "binary_sensor":
            self._gpiozero_device = gpiozero.DigitalInputDevice(pin=device_settings["pin"])

            self._gpiozero_device.when_activated = lambda msg="ON": self._on_set(msg)
            self._gpiozero_device.when_deactivated = lambda msg="OFF": self._on_set(msg)

        elif device_settings["component"] == "switch":
            self._add_channel(channel_name="command_topic",
                              sub_topic="set",
                              on_message=self._on_set)
            self._gpiozero_device = gpiozero.DigitalOutputDevice(pin=device_settings["pin"])

    def _on_set(self, message):

        if self._inverted:
            message = "ON" if message == "OFF" else "OFF"

        if message == "ON":
            self._gpiozero_device.on()
            self._update(channel_name="state_topic",
                         message=message)
        elif message == "OFF":
            self._gpiozero_device.off()
            self._update(channel_name="state_topic",
                         message=message)


class RPI_RGB(RemoteDevice):

    def __init__(self, device_settings, mqtt_settings):
        super(RPI_RGB, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)
        self._config["schema"] = "json"
        self._config["rgb"] = "true"
        self._config["brightness"] = device_settings["pwm_led"]

        self._add_channel(channel_name="command_topic",
                          sub_topic="set",
                          on_message=self._on_set)

        self._add_channel(channel_name="rgb_state_topic",
                          sub_topic="rgb_state",
                          on_message=None)

        self._gpiozero_device = gpiozero.RGBLED(red=device_settings["pin_r"],
                                                green=device_settings["pin_g"],
                                                blue=device_settings["pin_b"],
                                                active_high=device_settings["active_high"],
                                                pwm=device_settings["pwm_led"])

    def _on_set(self, message):

        message = json.loads(message)
        try:
            if message["state"] == "OFF":
                self._gpiozero_device.off()
                return

            if message["state"] == "ON":
                try:
                    color = message["color"]
                except KeyError:
                    try:
                        brightness = int(255 * message["brightness"])
                    except:
                        brightness = 255
                    color = {"r": brightness, "g": brightness, "b": brightness}


                if not self._config["brightness"]:
                    color = dict((key, (1 if color[key] >= 1 else 0)) for key in color)

                rgb_tuple = (color["r"], color["g"], color["b"])
                self._gpiozero_device.value = rgb_tuple


        except KeyError:
            print(f"Unsupported command structure: {message}")

    def _publish_state(self, rgb):

        if isinstance(rgb[0], float):
            rgb = [int(value*255) for value in rgb]

        message = f"{rgb[0]}, {rgb[1]}, {rgb[2]}"
        self._update(channel_name="rgb_state_topic",
                     message=message)

class ESpeakTTS(RemoteDevice):
    def __init__(self, device_settings, mqtt_settings):
        super(ESpeakTTS, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)

        self._espeak_module = __import__("espeak", fromlist=["espeak"])

        self._config["schema"] = "json"

        self._add_channel(channel_name="command_topic",
                          sub_topic="say",
                          on_message=self._on_say)

        parameter = self._espeak_module.espeak.Parameter
        self._espeak_module.espeak.set_voice(device_settings["voice"])
        self._espeak_module.espeak.set_parameter(parameter.Rate, device_settings["rate"])
        self._espeak_module.espeak.set_parameter(parameter.Pitch, device_settings["pitch"])

        self._espeak_module.espeak.synth("Sprachsyntheese ist activ!")

    def _on_say(self, msg):

        try:
            if isinstance(msg, str):
                text = msg
            else:
                text = str(msg["text"])
            self._espeak_module.espeak.synth(text)
        except (KeyError, TypeError):
            print("No text key provided in message!")



