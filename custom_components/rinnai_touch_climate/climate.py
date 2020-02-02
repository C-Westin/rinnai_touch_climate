"""
custom_component to support for Rinnai Touch thermostats.

This is an proof of concept pre-alpha release which is not supported in any way
current functionality:
 - Monitor touch status in HA 
 - Switch HVAC function
 - Set target temperature 
 - Supports Heat and Cooling (air-con only)
 - supports reporting zone A & B status
 - No support for schedules, fan speed etc etc
 
When using this only use the touch phone application in Cloud connection mode - turn off wifi

Thanks to 
  christhhoff https://gist.github.com/christhehoff - for his work on the touch device
  cyberjunkie https://github.com/cyberjunky/ - base client custom component
  The HA team. The documentation is great. 
 
The following configuration.yaml entries are required:

climate:
  - platform: rinnai_touch_climate
    name: Rinnai Touch Thermostat
    host: <IP_ADDRESS>
    port: 27847
    scan_interval: 10
    current_temp: sensor.temperature

logger:
  logs:
    custom_components.rinnai_touch_climate: debug
"""
import logging
import json
import requests
import socket
import time
import select
import voluptuous as vol
from typing import Any, Dict, List, Optional

from homeassistant.components.climate import (ClimateDevice, PLATFORM_SCHEMA)
from homeassistant.components.climate.const import (
    HVAC_MODE_HEAT,
	HVAC_MODE_COOL,
    HVAC_MODE_OFF,
    SUPPORT_TARGET_TEMPERATURE,
    CURRENT_HVAC_HEAT,
	CURRENT_HVAC_COOL,
    CURRENT_HVAC_IDLE,
    CURRENT_HVAC_OFF,
)

from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    TEMP_CELSIUS,
    ATTR_TEMPERATURE,
)

from homeassistant.helpers.typing import HomeAssistantType
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE
SUPPORT_MODES = [HVAC_MODE_HEAT, HVAC_MODE_COOL, HVAC_MODE_OFF]

DEFAULT_NAME = 'Rinnai Touch Thermostat'
DEFAULT_TIMEOUT = 5
DEFAULT_MAX_TEMP = 30.0
DEFAULT_MIN_TEMP = 6.0
BASE_URL = 'http://{0}:{1}'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_PORT, default=27847): cv.positive_int,
})

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the Rinnai touch thermostat."""
    add_devices([ThermostatDevice(config.get(CONF_NAME), config.get(CONF_HOST),
                            config.get(CONF_PORT))])

def connectToTouch(touchHost, touchPort):
    """Connect the client"""
    _LOGGER.debug("Trying to connect to touch...")
    time.sleep(1)  
    try: 
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except socket.error as err: 
        _LOGGER.debug("Failed to create socket: %s", str(err))
        client.close()
        return
    _LOGGER.debug("Socket created")

    try:
       client.connect((touchHost, touchPort))
    except socket.error as err:
        _LOGGER.debug("Error connecting to server: %s", str(err))
        client.close()
        return

    _LOGGER.debug("Connected")
    return client

def getTouchData(client):

    time.sleep(1)
    try:
        reply = client.recv(4096)
    except socket.error as err:
        _LOGGER.debug("Error receiving data: %s", str(err))
        client.close()
        return

    _LOGGER.debug("Call result...")
    _LOGGER.debug(reply)
    jStr = reply[14:]
        
    if len(jStr) > 0:
        j = json.loads(jStr)
        client.close()
        return j
    else:
        _LOGGER.debug("Empty response") 
    client.close()

def sendTouchData(client, cmd):

    try:
        client.send(cmd.encode())
    except socket.error as err:
        _LOGGER.debug("Error sending command: %s", str(err))
        client.close()

def heatMode(self, hgomData):
    """Set all the heat attributes."""
    _LOGGER.debug("Setting heater values")

# Operating Mode - HGOM.OOP.ST
    oop = hgomData.get("OOP")
    if len(oop) > 0:
        if (oop.get("ST")) == "N":
            _LOGGER.debug("Heater On")
            self._hvac_mode = HVAC_MODE_HEAT
        else:
            _LOGGER.debug("Heater Off")
            self._hvac_mode = HVAC_MODE_OFF

# Heater current activity - HGOM.GSS.HC
    gss = hgomData.get("GSS")
    if len(gss) > 0:
        if (gss.get("HC")) == "Y":
            _LOGGER.debug("Heater running")
            self._current_mode = CURRENT_HVAC_HEAT
        else:
            _LOGGER.debug("Heater Idle")
            self._current_mode = CURRENT_HVAC_OFF

# Heater target temp - HGOM.GSO.SP 
    gso = hgomData.get("GSO")
    if gso:
        _LOGGER.debug("Heater target temp: %s", str(gso.get("SP")))
        self._target_temperature = int(gso.get("SP"))

# Set active zones - HGOM.ZxO.UE
    zao = hgomData.get("ZAO")
    if zao:
        if (zao.get("UE")) == "Y":
            _LOGGER.debug("Zone A On")
            self._zone_a_status = True
        else:
            _LOGGER.debug("Zone A Off")
            self._zone_a_status = False
    zbo = hgomData.get("ZBO")
    if zbo:
        if (zbo.get("UE")) == "Y":
            _LOGGER.debug("Zone B On")
            self._zone_b_status = True
        else:
            _LOGGER.debug("Zone B Off")
            self._zone_b_status = False

    return self

def airconMode(self, cgomData):
    """Set all the aircon attributes."""
    _LOGGER.debug("Setting aircon values")
    
    oop = cgomData.get("OOP")
    if (oop.get("ST")) == "N":
        #Air con is on
        self._hvac_mode = HVAC_MODE_COOL
        _LOGGER.debug("Aircon On")
    else:
        #Air-con is off
        _LOGGER.debug("Aircon Off")
        self._hvac_mode = HVAC_MODE_OFF

# Aircon current activity - CGOM.GSS.HC
    gss = cgomData.get("GSS")
    if len(gss) > 0:
        if (gss.get("CC")) == "Y":
            _LOGGER.debug("Aircon running")
            self._current_mode = CURRENT_HVAC_COOL
        else:
            _LOGGER.debug("Aircon Idle")
            self._current_mode = CURRENT_HVAC_OFF

# Aircon target temp - CGOM.GSO.SP 
    gso = cgomData.get("GSO")
    if gso:
        _LOGGER.debug("Aircon target temp: %s", str(gso.get("SP")))
        self._target_temperature = int(gso.get("SP"))

# Set active zones - CGOM.ZxO.UE
    zao = cgomData.get("ZAO")
    if zao:
        if (zao.get("UE")) == "Y":
            _LOGGER.debug("Zone A On")
            self._zone_a_status = True
        else:
            _LOGGER.debug("Zone A Off")
            self._zone_a_status = False
    zbo = cgomData.get("ZBO")
    if zbo:
        if (zbo.get("UE")) == "Y":
            _LOGGER.debug("Zone B On")
            self._zone_b_status = True
        else:
            _LOGGER.debug("Zone B Off")
            self._zone_b_status = False

    return self

class ThermostatDevice(ClimateDevice):
    """Representation of a Rinnai touch climate device."""

    def __init__(self, name, host, port) -> None:
        """Initialize the Rinnai touch climate device."""
        self._data = None
        self._name = name
        self._host = host
        self._port = port

        self._current_temperature = None
        self._target_temperature = None
        self._program_state = None
        self._hvac_mode = HVAC_MODE_OFF
        self._current_mode = CURRENT_HVAC_OFF
        self._zone_a_status = False
        self._zone_b_status = False
        self.update()

    @property
    def should_poll(self):
        """Polling needed for thermostat."""
        return True

    def update(self) -> None:
        """Update local data with thermostat data."""
        _LOGGER.debug("*Performing an update")
        time.sleep(1)
        connection = connectToTouch(self._host,self._port)
        if connection:
            self._data = getTouchData(connection)

            if not self._data:
                _LOGGER.debug("No data")
                return

            if 'HGOM' in self._data[1]:
            #Heat Mode
                _LOGGER.debug("Heater Mode")
                hgom = self._data[1].get("HGOM")
                heatMode(self, hgom)
        
            elif 'CGOM' in self._data[1]:
            #Aircon mode
                _LOGGER.debug("Air Con Mode")
                hgom = self._data[1].get("CGOM")
                airconMode(self, hgom)

            else:
                self._hvac_mode = HVAC_MODE_OFF

            _LOGGER.debug("Update completed")

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return SUPPORT_FLAGS

    @property
    def name(self) -> str:
        """Return the name of the thermostat."""
        return self._name

    @property
    def device_state_attributes(self) -> Dict[str, Any]:
        """Return the state of the A & B Zones."""
        return {"zone_a": self._zone_a_status, "zone_b": self._zone_b_status}

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement."""
        return TEMP_CELSIUS

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature."""
        return self._current_temperature

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return DEFAULT_MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        return DEFAULT_MAX_TEMP

    def set_temperature(self, **kwargs) -> None:
        """Set target temperature."""

        target_temperature = kwargs.get(ATTR_TEMPERATURE)
        if target_temperature is None:
            return
            
        _LOGGER.debug("*Setting target temp: %s°C", str(target_temperature))      
        
        connection = connectToTouch(self._host,self._port)
        if connection:
            if self._hvac_mode == HVAC_MODE_HEAT:
                sendTouchData(connection, 'N000001{{"HGOM": {{"GSO": {{"SP": "{"str(target_temperature)"}" }} }} }}')
            elif self._hvac_mode == HVAC_MODE_COOL:
                sendTouchData(connection, 'N000001{{"CGOM": {{"GSO": {{"SP": "{"str(target_temperature)"}" }} }} }}')
            self._target_temperature = target_temperature
            connection.close    
            _LOGGER.debug("Update of target temp completed")
            time.sleep(2)
        else:
            _LOGGER.debug("Connection failed")        
        
        
    @property
    def hvac_mode(self) -> str:
        """Return the current operation mode."""
        return self._hvac_mode

    @property
    def hvac_modes(self) -> List[str]:
        """Return the list of available hvac operation modes."""
        return SUPPORT_MODES

    @property
    def hvac_action(self) -> Optional[str]:
        """Return the current running hvac operation."""
        return self._current_mode

    def set_hvac_mode(self, hvac_mode: str) -> None:
        """Set new target hvac mode."""
        _LOGGER.debug("*Updating hvac mode: %s", str(hvac_mode))

        connection = connectToTouch(self._host,self._port)
        if connection:
            if hvac_mode == "heat":
                sendTouchData(connection, 'N000001{"SYST": {"OSS": {"MD": "H" } } }')
                time.sleep(2)
                sendTouchData(connection, 'N000001{"HGOM": {"OOP": {"ST": "N" } } }')
                self._hvac_mode = HVAC_MODE_HEAT

            elif hvac_mode == "cool":
                sendTouchData(connection, 'N000001{"SYST": {"OSS": {"MD": "C" } } }')
                time.sleep(2)
                sendTouchData(connection, 'N000001{"CGOM": {"OOP": {"ST": "N" } } }')
                self._hvac_mode = HVAC_MODE_COOL

            else:
                if self._hvac_mode == HVAC_MODE_HEAT:
                    sendTouchData(connection, 'N000001{"HGOM": {"OOP": {"ST": "F" } } }')
                elif self._hvac_mode == HVAC_MODE_COOL:
                    sendTouchData(connection, 'N000001{"CGOM": {"OOP": {"ST": "F" } } }')
                self._hvac_mode = HVAC_MODE_OFF
        
            connection.close    
            _LOGGER.debug("Update of hvac mode completed")
            time.sleep(2)
        else:
            _LOGGER.debug("Connection failed")