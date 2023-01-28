# pydevice2mqtt

Python class library for generating and sending data to the Home Assistant via
MQTT (AutoDiscovery) of data from devices

## Build and Install
### build wheel: 

    # from top folder: 
    pip install -e .
    flit build

### install wheel:
       
    # inside dist folder:
    pip install pydevice2mqtt

## Usage
```Python
import os
import pathlib       
import pydevice2mqtt
    
# may create a dict with the device information
new_device: dict = {"ArbitrarySensor": [
    {"name": "Sensor 1",
     "device_class": "current",
     "unit_of_measurement": "A",
     "object_id": "special_ID1"},
    {"name": "Sensor 2",
     "device_class": "temperature",
     "unit_of_measurement": "C",
     "object_id": "special_ID2"}
]}

remote_config = "remote_config.yaml" # your config file with the mqtt settings

pydevice2mqtt.DeviceBridge.update_config(devices=new_device, config_file=remote_config)

my_bridge = pydevice2mqtt.DeviceBridge(config_file=remote_config)
my_bridge.configure_devices() # add new devices in Hassio

my_bridge.loop()
```

### Update Sensor Value
```Python   
from typing import Dict               
import pydevice2mqtt


devices: Dict[str,pydevice2mqtt.RemoteDevice]   = my_bridge.get_devices()
devices[<unique_sensor_id>].set_value(123)

```             



