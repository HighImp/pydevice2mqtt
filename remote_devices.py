import json
import time
from collections import namedtuple, defaultdict

# special_modules = list()
# special_modules.append("subprocess")
# special_modules.append("gpiozero")
#
# self._threading_module = __import__("threading", fromlist=["threading"])
# self._subprocess_module = __import__("subprocess", fromlist=["subprocess"])
#
# try:
#     import

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

        self._logging_channel = None
        if mqtt_settings["logging"] is not None:
            self._logging_channel = f"{mqtt_settings['operating_prefix']}/" \
                                    f"{mqtt_settings['node_id']}/" \
                                    f"{device_settings['object_id']}/" \
                                    f"{mqtt_settings['logging']}/"

        self._config = {"topic": self._discovery_prefix + "config"}

        self._add_channel(channel_name="state_topic",
                          sub_topic="state",
                          on_message=None)

        self._component = device_settings['component']
        self._config["name"] = device_settings["name"]

        self._config["unique_id"] = device_settings["uid"]
        self._publish = mqtt_settings["f_publish"]

    def _print_log(self, *args, **kwargs):

        print_string = "".join(map(str, args))
        print(print_string, **kwargs)
        if self._logging_channel is not None:
            self._publish(topic=self._logging_channel,
                          payload=print_string,
                          retain=False,
                          qos=1)

    def _update(self, channel_name: str, message: any) -> None:
        """
        Publish the message in json format to the channel name
        (must be added by add_channel first)

        :param channel_name: name of the device channel
        :param message: any type of json dumpable data to publish
        :return: None
        """

        topic = self._operation_topics[channel_name].topic

        if not isinstance(message, str):
            message = json.dumps(message)

        self._publish(topic=topic,
                      payload=message,
                      retain=False,
                      qos=1)

    def _add_channel(self, channel_name: str, sub_topic: str, on_message=None) -> None:
        """
        Add a channel to the internal channel storage,
        to enable listening (if on message is not None) and publish

        :param channel_name: name of the channel
        :param sub_topic: mqtt subtopic after the device topic (read hassio documentation)
        :param on_message: function to call if a message is received on this channel
        :return: None
        """

        self._operation_topics[channel_name] = MQTTChannel(self._operating_prefix + sub_topic, on_message)

    def get_name(self) -> str:
        """
        Get the given of the component, defined in config

        :return: name of the component
        """
        return self._config["name"]

    def get_config(self) -> dict:
        """"
        Generate the config dictionary in MQTT Discovery stile

        :return: auto discover dictionary with the discovery channel as key
        """

        auto_config = {**self._config, **{name: channel.topic for (name, channel) in self._operation_topics.items()}}
        topic = auto_config.pop("topic")

        return {"topic": topic, "message": auto_config}

    def get_device_topics(self) -> dict:
        """
        Return all mqtt topics this device will listen on or publish to,
        dict with the mqtt topic as key and the callback function (if set) as value

        :return: dict in form of {topic:callback_function}
        """
        return dict([channel for name, channel in self._operation_topics.items()])


def supported_devices() -> dict:
    """
    generates a dictionary with all supported devices,
    and the class name as key, the object as value

    :return: dict with the supported devices
    """

    import sys
    import inspect
    cls_members = inspect.getmembers(sys.modules[__name__], inspect.isclass)
    return dict((name, obj) for name, obj in cls_members if name != "RemoteDevice")


class RPI_GPIO(RemoteDevice):
    """
    Raspberry PI Remote Gpio device
    Remote device to configure and control GPIOs of an Raspberry Pi via MQTT and
    especially in hassio via auto configuration, supporting switch and binary sensor format
    """

    def __init__(self, device_settings, mqtt_settings):
        super(RPI_GPIO, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)

        try:
            import gpiozero
        except ImportError:
            err_msg = "Could not import gpiozero. Unable to create this remote device!"
            self._print_log(err_msg)
            raise ImportError(err_msg)

        self._gpiozero_device = None
        self._inverted = device_settings["inverted"]
        if device_settings["component"] == "binary_sensor":
            self._gpiozero_device = gpiozero.DigitalInputDevice(pin=device_settings["pin"])

            self._gpiozero_device.when_activated = lambda msg="ON": self._handle_pinchange(msg)
            self._gpiozero_device.when_deactivated = lambda msg="OFF": self._handle_pinchange(msg)

        elif device_settings["component"] == "switch":
            self._add_channel(channel_name="command_topic",
                              sub_topic="set",
                              on_message=self._handle_command)
            self._gpiozero_device = gpiozero.DigitalOutputDevice(pin=device_settings["pin"])

    def _handle_command(self, target_state):

        if self._inverted:
            target_state = "ON" if target_state == "OFF" else "OFF"

        if target_state == "ON":
            self._gpiozero_device.on()

        elif target_state == "OFF":
            self._gpiozero_device.off()

        self._update(channel_name="state_topic",
                     message=target_state)

    def _handle_pinchange(self, target_state):
        if self._inverted:
            target_state = "ON" if target_state == "OFF" else "OFF"

        self._update(channel_name="state_topic",
                     message=target_state)


class RPI_RGB(RemoteDevice):

    def __init__(self, device_settings, mqtt_settings):

        super(RPI_RGB, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)

        try:
            import gpiozero
        except ImportError:
            err_msg = "Could not import gpiozero. Unable to create this remote device!"
            self._print_log(err_msg)
            raise ImportError(err_msg)

        self._config["schema"] = "json"
        self._config["rgb"] = "true"

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

                # may brightness here?
                color = dict((key, (1 if color[key] >= 1 else 0)) for key in color)

                rgb_tuple = (color["r"], color["g"], color["b"])
                self._gpiozero_device.value = rgb_tuple


        except KeyError:
            self._print_log(f"Unsupported command structure: {message}")

    def _publish_state(self, rgb):

        if isinstance(rgb[0], float):
            rgb = [int(value * 255) for value in rgb]

        message = f"{rgb[0]}, {rgb[1]}, {rgb[2]}"
        self._update(channel_name="rgb_state_topic",
                     message=message)


class ESpeakTTS(RemoteDevice):
    def __init__(self, device_settings, mqtt_settings):
        super(ESpeakTTS, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)

        try:
            self._espeak_module = __import__("espeak", fromlist=["espeak"])
        except ImportError:
            err_msg = "Could not import espeak. Unable to create this remote device!"
            self._print_log(err_msg)
            raise ImportError(err_msg)

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
            self._print_log("No text key provided in message!")


class SubprocessCall(RemoteDevice):
    """
    Remote Subprocess call via MQTT
    the call is defined in the config

    Will be treated as an switch with: "on" start, and "off" killing
    an ongoing subprocess. The state channel will publish "on" during an ongoing process
    """

    def __init__(self, device_settings, mqtt_settings):
        super(SubprocessCall, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)

        try:
            self._threading_module = __import__("threading", fromlist=["threading"])
            self._subprocess_module = __import__("subprocess", fromlist=["subprocess"])
        except ImportError:
            err_msg = "Could not import threading and/or subprocess. Unable to create this remote device!"
            self._print_log(err_msg)
            raise ImportError(err_msg)

        self._call = [device_settings["exec_path"]]
        try:
            args = device_settings["arguments"]
            if isinstance(args, dict):
                self._call.extend([param+" "+args[param] for param in args])
            if isinstance(args, list):
                self._call.extend(args)
            if isinstance(args, str):
                self._call.extend(args.split(" "))

        except KeyError:
            pass

        self._print_log("Device created: SubprocessCall is: ", self._call)
        
        try:
            self._looptime = device_settings["looptime"]
        except KeyError:
            self._looptime = 1

        self._running_process = None
        self._observation_thread = None
        self._add_channel(channel_name="command_topic",
                          sub_topic="set",
                          on_message=self._handle_command)

    def _observation_function(self, pOpen, looptime: int = 1):

        self._update(channel_name="state_topic",
                     message="ON")

        while pOpen.poll() is None:
            time.sleep(looptime)

        self._update(channel_name="state_topic",
                     message="OFF")
        self._running_process = None

    def _handle_command(self, target_state: str):
        """
        Handle incoming call request,
        if target state is "ON", the call will be fired (no multirun)
        if target state is "OFF", the process will be killed

        :param target_state: "ON" or "OFF"
        """

        if target_state == "ON":

            if self._running_process is not None:
                self._print_log("Error: Subprocess is still running, multirun not supported")
                return

            try:
                self._running_process = self._subprocess_module.Popen(self._call)
            except Exception as error:
                self._print_log("{}".format(error))
            else:
                thread_args = {"pOpen": self._running_process, "looptime": self._looptime}
                self._observation_thread = self._threading_module.Thread(target=self._observation_function,
                                                                         kwargs=thread_args)
                self._observation_thread.start()
            return

        if target_state == "OFF":
            if self._running_process is None:
                self._print_log("Process already stopped")
                return

            self._running_process.kill()
