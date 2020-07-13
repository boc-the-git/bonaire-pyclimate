# bonaire-pyclimate
Reverse engineered python implementation of the Bonaire MyClimate app

## Quick notes
- This is in no way affiliated with Bonaire or their associates
- This comes as-is, use at your own risk
- This has been written and tested with AppDaemon 4.0.3
- This has only been tested within my own home
- This is local only control, avoids Bonaire cloud but your device must be on the same local LAN.
- Your network must support UDP broadcast.
- You must update '_remote_address' and '_local_address' with the IP address of your Bonaire WiFi module and the device initiating this connection
- Fan mode is experimental at this stage

## Home Assistant YAML Code for MQTT HVAC
```
climate:

  - platform: 'mqtt'
    send_if_off: false
    precision: 1.0
    min_temp: '16'
    max_temp: '28'
    current_temperature_topic: 'climate/state/roomTemp'
    temperature_state_topic: 'climate/state/setPoint'
    temperature_command_topic: 'climate/command/setPoint'
    mode_state_topic: 'climate/state/type'
    mode_command_topic: 'climate/command/type'
    modes:
      - 'off'
      - 'cool'
      - 'heat'
      - 'fan_only'
    hold_state_topic: 'climate/state/zoneList'
    hold_command_topic: 'climate/command/zoneList'
    hold_modes:
      - '1'
      - '1,2'
      - '2'
    fan_mode_state_topic: 'climate/state/fanSpeed'
    fan_mode_command_topic: 'climate/command/fanSpeed'
    fan_modes:
      - 'off'
      - '1'
      - '2'
      - '3'
      - '4'
      - '5'
      - '6'
      - '7'
      - '8'
    swing_mode_state_topic: 'climate/state/mode'
    swing_mode_command_topic: 'climate/command/mode'
    swing_modes:
      - 'off'
      - 'econ'
      - 'thermo'
      - 'boost'
```
