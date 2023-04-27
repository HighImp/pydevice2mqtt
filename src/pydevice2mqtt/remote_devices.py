import hashlib
import json
import logging
import time
from collections import namedtuple, defaultdict

try:
    import espeak
except ImportError:
    espeak = None

try:
    import gpiozero
except ImportError:
    gpiozero = None

MQTTChannel = namedtuple("MQTTChannel", ["topic", "on_message"])


class RemoteDevice:
    _BASE_CONFIG_REQ = {
        "name": str,  # Display Name
    }

    _CONFIG_REQ = {}

    def __init__(self, device_settings: dict, mqtt_settings: dict):

        uid_string = f"{mqtt_settings['operating_prefix']}_" \
                     f"{mqtt_settings['bridge_name']}_" \
                     f"{self.__class__.__name__}_" \
                     f"{device_settings['object_id']}"

        uid_hash = hashlib.new("sha1", data=uid_string.encode(), usedforsecurity=False)
        self._uid = uid_hash.hexdigest()[:16]

        self._device_class = device_settings['device_class']

        # prepare auto config dict
        self._config: dict = {"device": {"identifiers": [f"{mqtt_settings['operating_prefix']}_"
                                                         f"{mqtt_settings['bridge_name']}"],
                                         "name": mqtt_settings['bridge_name']}, "name": device_settings["name"],
                              "unique_id": self._uid,
                              "object_id": device_settings["object_id"]}

        # some devices may need special attributes to appear in a special manner in hassio,
        # there are too many to handle all of them, so add them via generic dict from config on demand
        if "opt_attr" in device_settings.keys():
            attribute = None
            try:
                for attribute, value in device_settings["opt_attr"].items():
                    assert attribute not in self._config.keys()
                    self._config[attribute] = value
            except (TypeError, AttributeError, KeyError):
                logging.warning("Could not apply optional attributes!")
            except AssertionError:
                logging.warning(f"Could not overwrite a required item with the optional dict ({attribute})")

        self._discovery_prefix = f"{mqtt_settings['discovery_prefix']}/" \
                                 f"{device_settings['device_class']}/" \
                                 f"{mqtt_settings['bridge_name']}/" \
                                 f"{self.get_id()}/"

        # store the discovery topic
        self._config["discovery_topic"] = f"{self._discovery_prefix}config"

        # prepare mqtt channels
        self._operation_topics = defaultdict(MQTTChannel)
        self._operating_prefix = f"{mqtt_settings['operating_prefix']}/" \
                                 f"{mqtt_settings['bridge_name']}/" \
                                 f"{self.get_id()}/"

        self._logging_channel = None
        if mqtt_settings["logging"]:
            self._logging_channel = f"{mqtt_settings['operating_prefix']}/" \
                                    f"{mqtt_settings['bridge_name']}/" \
                                    f"{self.get_id()}/" \
                                    f"log"

        self._add_channel(channel_name="state_topic",
                          sub_topic="state",
                          on_message=None)

        # connect self._publish to the function publish
        self._publish = mqtt_settings["f_publish"]

    def _log_remote(self, *args, **kwargs):

        level = getattr(kwargs, "Level", logging.DEBUG)
        print_string = "".join(map(str, args))
        logging.log(level=level, msg=print_string)
        if self._logging_channel is not None:
            self._publish(topic=self._logging_channel,
                          payload=print_string,
                          retain=False,
                          qos=0)

    def _update(self, channel_name: str, message: any, retain: bool = False, qos: int = 0) -> None:
        """
        Publish the message in json format to the channel name
        (must be added by add_channel first)

        :param channel_name: name of the device channel
        :param message: any type of json dumpable data to publish
        :param retain: Retain flag for this message
        :param qos: qos level for this message
        :return: None
        """

        topic = self._operation_topics[channel_name].topic

        if not isinstance(message, str):
            message = json.dumps(message)

        self._publish(topic=topic,
                      payload=message,
                      retain=retain,
                      qos=qos)

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

    def get_id(self) -> str:
        """Get a human readable ID of the device,
        unique in this bridge

        :return: ID as string
        """
        return f"{self.__class__.__name__}_{self.get_object_id()}"

    def get_uid(self) -> str:
        """Get a real UID of the endpoint,
        sha1 hash over bridge and device information

        :return: UID as string
        """
        return self._uid

    def get_object_id(self) -> str:
        """Get the object id provided in the config file,
        useful to filter devices of one type
        """
        return self._config['object_id']

    def get_name(self) -> str:
        """
        Get the given name of the device, defined in config

        :return: name of the device
        """
        return self._config["name"]

    def get_discovery(self) -> tuple:
        """"
        Generate the config dictionary in MQTT Discovery stile

        :return: auto discover tuple with the discovery topic on index 0
        """

        auto_config = {**self._config, **{name: channel.topic for (name, channel) in self._operation_topics.items()}}
        topic = auto_config.pop("discovery_topic")

        return topic, auto_config

    def get_device_topics(self) -> dict:
        """
        Return all mqtt topics this device will listen on or publish to,
        dict with the mqtt topic as key and the callback function (if set) as value

        :return: dict in form of {topic:callback_function}
        """
        return dict([channel for name, channel in self._operation_topics.items()])

    @classmethod
    def get_config_req(cls) -> dict:
        """Returns a dict with the required keys and the expected data types as values
        :return: dict
        """
        config_req = cls._CONFIG_REQ.copy()
        config_req.update(cls._BASE_CONFIG_REQ)
        return config_req


def supported_device_classes() -> dict:
    """
    generates a dictionary with all supported devices,
    and the class name as key, the object as value

    :return: dict with the supported devices
    """

    import sys
    import inspect

    # all classes in this module
    cls_members = inspect.getmembers(sys.modules[__name__], inspect.isclass)

    # only classes with base class Remote Device
    supported_devices = {}
    for class_name, class_obj in cls_members:
        if RemoteDevice in inspect.getmro(class_obj) and class_obj != RemoteDevice:
            supported_devices[class_name] = class_obj

    return supported_devices


class ArbitrarySensor(RemoteDevice):
    """
    Arbitrary Sensor to publish any data to hassio
    """

    _CONFIG_REQ = {
        "device_class": str,  # Sensor Type (https://www.home-assistant.io/integrations/sensor#device-class)
        "unit_of_measurement": str  # ,  # Unit of measurement (W,C,V,A...)
    }

    def __init__(self, device_settings: dict, mqtt_settings: dict):
        # mqtt discovery channel must be start with sensor, but
        # but the final device class will be correct
        # -> Discovery channel will be created in constructor of parent class
        org_device_class = device_settings["device_class"]
        device_settings["device_class"] = "sensor"
        super(ArbitrarySensor, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)
        device_settings["device_class"] = org_device_class
        self._config["device_class"] = device_settings.get("device_class", "None")
        self._config["unit_of_measurement"] = device_settings.get("unit_of_measurement", "")
        self._config["value_template"] = "{{ value_json.value}}"
        self._last_value = None

    def set_value(self, value, force_update=True) -> None:
        """The set function for this sensor,
        will update the value in hassio.

        :param value: new arbitrary value
        :param force_update: if true, write the state even if no value changes occured

        :return:
        """
        if self._last_value == value and not force_update:
            return

        self._update(channel_name="state_topic",
                     message=json.dumps({"value": value}))
        self._last_value = value


class RpiGpio(RemoteDevice):
    """
    Raspberry PI Remote Gpio device
    Remote device to configure and control GPIOs of an Raspberry Pi via MQTT and
    especially in hassio via auto configuration, supporting switch and binary sensor format
    """

    _CONFIG_REQ = {
        "device_class": str,  # binary_sensor or switch
        "pin": int,  # Pin Nr according to gpiozero
        "inverted": bool  # Device side inverter on/off (both directions)
    }

    def __init__(self, device_settings, mqtt_settings):
        super(RpiGpio, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)

        if gpiozero is None:
            err_msg = "Could not import gpiozero. Unable to create this remote device!"
            self._log_remote(err_msg)
            raise ImportError(err_msg)

        self._gpiozero_device = None
        self._inverted = device_settings["inverted"]
        if device_settings["device_class"] == "binary_sensor":
            self._gpiozero_device = gpiozero.DigitalInputDevice(pin=device_settings["pin"])

            self._gpiozero_device.when_activated = lambda msg="ON": self._handle_pinchange(msg)
            self._gpiozero_device.when_deactivated = lambda msg="OFF": self._handle_pinchange(msg)

        elif device_settings["device_class"] == "switch":
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


class RpiRgb(RemoteDevice):
    _CONFIG_REQ = {
        "device_class": str,  # binary_sensor or switch
        "pin_r": int,  # Red Pin Nr according to gpiozero
        "pin_g": int,  # Green Pin Nr according to gpiozero
        "pin_b": int,  # Blue Pin Nr according to gpiozero
        "active_high": bool,  # Determine if logical 1 leads to active light
        "pwm_led": bool  # Determine if the pins support PWM
    }

    def __init__(self, device_settings, mqtt_settings):

        super(RpiRgb, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)

        if gpiozero is None:
            err_msg = "Could not import gpiozero. Unable to create this remote device!"
            self._log_remote(err_msg)
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
            self._log_remote(f"Unsupported command structure: {message}")

    def _publish_state(self, rgb):

        if isinstance(rgb[0], float):
            rgb = [int(value * 255) for value in rgb]

        message = f"{rgb[0]}, {rgb[1]}, {rgb[2]}"
        self._update(channel_name="rgb_state_topic",
                     message=message)


class ESpeakTTS(RemoteDevice):
    _CONFIG_REQ = {
        "device_class": str,  # Should always be tts
        "voice": str,  # ESpeak voice set (like 'mb-de6')
        "rate": int,  # Voice Speed
        "pitch": int,  # Voice Pitch
    }

    def __init__(self, device_settings, mqtt_settings):
        super(ESpeakTTS, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)

        if espeak is None:
            err_msg = "Could not import espeak. Unable to create this remote device!"
            self._log_remote(err_msg)
            raise ImportError(err_msg)

        self._config["schema"] = "json"

        self._add_channel(channel_name="command_topic",
                          sub_topic="say",
                          on_message=self._on_say)

        parameter = espeak.espeak.Parameter
        espeak.espeak.set_voice(device_settings["voice"])
        espeak.espeak.set_parameter(parameter.Rate, device_settings["rate"])
        espeak.espeak.set_parameter(parameter.Pitch, device_settings["pitch"])

        espeak.espeak.synth("Sprachsyntheese ist activ!")

    def _on_say(self, msg):

        try:
            if isinstance(msg, str):
                text = msg
            else:
                text = str(msg["text"])
            espeak.espeak.synth(text)
        except (KeyError, TypeError):
            self._log_remote("No text key provided in message!")


class SubprocessCall(RemoteDevice):
    """
    Remote Subprocess call via MQTT
    the call is defined in the config

    Will be treated as a switch.
    "on" will start, and "off" killing a ongoing subprocess.
    The state channel will publish "on" during active process
    """

    _CONFIG_REQ = {
        "device_class": str,  # should be 'switch'
        "exec_path": str,  # Path app or file to execute (i.E. python.exe)
        "arguments": str,  # space separated list of arguments ("--version -E")
        "looptime": int  # polling time in seconds to check if the call is done
    }

    def __init__(self, device_settings, mqtt_settings):
        super(SubprocessCall, self).__init__(device_settings=device_settings, mqtt_settings=mqtt_settings)

        try:
            self._threading_module = __import__("threading", fromlist=["threading"])
            self._subprocess_module = __import__("subprocess", fromlist=["subprocess"])
        except ImportError:
            err_msg = "Could not import threading and/or subprocess. Unable to create this remote device!"
            self._log_remote(err_msg)
            raise ImportError(err_msg)

        self._call = [device_settings["exec_path"]]
        try:
            args = device_settings["arguments"]
            if isinstance(args, dict):
                self._call.extend([param + " " + args[param] for param in args])
            if isinstance(args, list):
                self._call.extend(args)
            if isinstance(args, str):
                self._call.extend(args.split(" "))

        except KeyError:
            pass

        self._log_remote("Device created: SubprocessCall is: ", self._call)

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
                self._log_remote("Error: Subprocess is still running, multirun not supported")
                return

            try:
                self._running_process = self._subprocess_module.Popen(self._call)
            except Exception as error:
                self._log_remote("{}".format(error))
            else:
                thread_args = {"pOpen": self._running_process, "looptime": self._looptime}
                self._observation_thread = self._threading_module.Thread(target=self._observation_function,
                                                                         kwargs=thread_args)
                self._observation_thread.start()
            return

        if target_state == "OFF":
            if self._running_process is None:
                self._log_remote("Process already stopped")
                return

            self._running_process.kill()
