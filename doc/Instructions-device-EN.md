# AS7341 Spectrometer Device User Manual

## 1. Product Overview

The AS7341 Spectrometer Device is a multi-functional spectral measurement instrument based on ESP32, integrating AS7341 spectral sensor, OLED display, UV LED, buzzer and other components. It supports two operation modes: local operation and remote data stream transmission.

### Key Features

- **Spectral Measurement**: 8-channel spectral data acquisition (F1-F8)
- **Dual Operation Modes**: Local display mode + Data stream transmission mode
- **Wireless Communication**: WiFi connectivity, supporting TCP command control and UDP data stream transmission
- **Local Control**: OLED menu + Three-button operation
- **Programmable Light Sources**: AS7341 built-in LED and external UV LED with adjustable brightness
- **Status Indication**: Buzzer audio feedback

## 2. Hardware Specifications

### 2.1 Hardware Interfaces

- **OLED Display**: 128×64 resolution, displaying menu and spectral data
- **Control Buttons**:
  - UP Button: Navigate up/Increase value
  - SEL Button: Confirm/Enter menu
  - DOWN Button: Navigate down/Decrease value
- **Sensor**: AS7341 11-channel spectral sensor
- **Light Sources**:
  - AS7341 built-in LED (adjustable brightness)
  - External UV LED (adjustable brightness)
- **Audio**: Piezo buzzer (adjustable volume)

### 2.2 Communication Interfaces

- **WiFi**: 2.4GHz IEEE 802.11 b/g/n
- **Command Port**: TCP 6688 (JSON format commands)
- **Data Stream Port**: UDP 6699 (Spectral data stream)
- **Target Server Port**: TCP 6677 (Status notifications)
- **USB Serial**: Baud rate 115200 (Development debugging)

## 3. Quick Start

### 3.1 Device Startup

1. Connect power supply (Micro-USB)
2. Device automatically boots up, showing initialization screen
3. Enters default spectral display mode

### 3.2 Basic Operations

- **Short press SEL button**: Enter main menu
- **UP/DOWN buttons**: Navigate through menu
- **Long press SEL button**: Return to previous menu level

## 4. Menu System Details

### 4.1 Spectral Display Mode (Default)

Device automatically enters this mode upon startup, displaying three pages:

**Page 1 - Spectral Data**

- Real-time display of 8 spectral channel values
- F1-F4 shown on left side, F5-F8 shown on right side

**Page 2 - System Status**

- AS7341 sensor status
- AS7341 LED status
- UV LED status
- Buzzer status

**Page 3 - WiFi Status**

- WiFi enable status
- Connection status (Connected/Connecting/Not connected)
- SSID information
- IP address information
- Reconnection status

### 4.2 Main Menu Options

#### 1. AS7341 Control

- **LED Brightness**: 1-20 levels adjustable, UP increases, DOWN decreases
- **LED Switch**: UP turns on, DOWN turns off

#### 2. UV LED Control

- **UV Brightness**: 1-20 levels adjustable
- **UV Switch**: UP turns on, DOWN turns off

#### 3. Buzzer Control

- **Volume Adjustment**: 1-10 levels adjustable
- **Buzzer Switch**: UP turns on, DOWN turns off

#### 4. WiFi Settings

**WiFi SSID**: Set wireless network name
**WiFi Password**: Set wireless network password
**Static IP**: Set device static IP (Optional, leave blank for DHCP)
**Target IP**: Set data receiving server IP address
**WiFi Switch**: Enable/disable WiFi function
**Manual Reconnect**: Immediately reconnect to WiFi

#### 5. Exit

Return to spectral display mode

## 5. WiFi Settings Detailed Instructions

### 5.1 Edit Mode Operations

Enter any editing item (SSID, password, IP address):

**Character Selection Mode**:

- UP/DOWN: Switch characters
- SEL: Confirm selection of current character
- Long press SEL: Save and exit

**Edit Mode** (Enter by long pressing UP):

- UP: Move cursor right
- DOWN: Move cursor left
- SEL: Delete character before cursor
- Long press DOWN: Exit edit mode

### 5.2 Connection Status Indication

- **Connecting**: Shows "Connecting"
- **Connected**: Shows IP address and signal strength
- **Connection Failed**: Shows retry count and maximum reconnection attempts
- **Exceeded Retry Limit**: Shows "Max retries reached"

## 6. Data Stream Mode

### 6.1 Entering Data Stream Mode

**Prerequisites**:

- WiFi connected
- Target IP correctly set
- Sensor initialized successfully

**Entry Method**:
Send via TCP command: `{"dataStream": true}`

### 6.2 Data Stream Mode Display

In data stream mode, OLED displays:

- Data packet count
- Real-time transmission frequency (FPS)
- Transmission mode (Continuous/Specified count)
- Current count/Target count (Specified count mode)
- Transmission status (Running/Paused)
- Transmission interval

### 6.3 Data Stream Control Commands

**Transmission Mode Settings**:

```json
{"streamMode": "continuous"}  // Continuous transmission mode
{"streamMode": "fixed", "streamCount": 1000}  // Specified count mode
```

**Set Transmission Count Separately**:

```json
{"streamCount": 500}
```

**Exit Data Stream Mode**:

```json
{"dataStream": false}
```

## 7. Remote Control Commands

### 7.1 Device Control Commands

**AS7341 LED Control**:

```json
{"as7341Led": true}  // Turn on
{"as7341Led": false} // Turn off
{"as7341Brightness": 15}  // Set brightness (1-20)
```

**UV LED Control**:

```json
{"uvLed": true}      // Turn on
{"uvLed": false}     // Turn off
{"uvBrightness": 10} // Set brightness (1-20)
```

**Buzzer Control**:

```json
{"buzzer": true}     // Turn on
{"buzzer": false}    // Turn off
```

**Device Status Query**:

```json
{"getDeviceStatus": true}
```

**Device Reboot**:

```json
{"reboot": true}
```

### 7.2 Command Responses

Device returns JSON format response for each command:

```json
{"response": "OK"}
{"response": "ERROR: Error message"}
```

## 8. Data Format Specifications

### 8.1 Spectral Data Format (UDP)

```json
{
  "t": 123456789,      // Timestamp (ms)
  "d": [123,456,789,...], // 8-channel spectral data
  "c": 1000,           // Data packet count
  "sc": 50             // Current transmission count (specified count mode)
}
```

### 8.2 Device Status Format

```json
{
  "type": "deviceStatus",
  "device": "AS7341_Sensor_Device",
  "timestamp": 123456789,
  "status": {
    "as7341_led": true,
    "as7341_bright": 10,
    "uv_led": false,
    "uv_bright": 15,
    "buzzer": true,
    "sensor": true,
    "stream_mode": "continuous",
    "stream_paused": false,
    "packet_count": 1000,
    "interval": 100,
    "current_count": 500,
    "target_count": 1000
  }
}
```

### 8.3 Connection Status Notification

```json
{
  "type": "connection",
  "status": "connected",
  "device": "AS7341_Sensor_Device",
  "timestamp": 123456789,
  "ip": "192.168.1.100",
  "rssi": -65
}
```

### 8.4 Data Stream Completion Notification

```json
{
  "type": "streamComplete",
  "device": "AS7341_Sensor_Device",
  "timestamp": 123456789,
  "total_packets": 5000,
  "stream_mode": "fixed",
  "target_count": 5000,
  "actual_count": 5000,
  "status": "completed"
}
```

## 9. Troubleshooting

### 9.1 Common Issues

**WiFi Connection Failure**:

- Check if SSID and password are correct
- Confirm router 2.4GHz band is available
- Check signal strength
- Try manual reconnect function

**Abnormal Sensor Readings**:

- Check sensor connection
- Confirm appropriate ambient lighting conditions
- Restart device

**Data Stream Transmission Failure**:

- Confirm target IP and port are correct
- Check network connectivity
- Confirm receiving end service is running properly

**Device Unresponsive**:

- Check power supply
- Try hardware restart
- Check USB cable connection

### 9.2 Status Indicator Sounds

- **Startup Sound**: Single beep indicates successful startup
- **Operation Sound**: Short beep indicates button operation
- **Error Sound**: Two short beeps indicate operation error
- **Connection Sound**: WiFi connection success prompt during startup

## 10. Technical Parameters

- **Operating Voltage**: 5V DC (USB power supply)
- **Operating Current**: Standby <100mA, Peak operation <300mA
- **Spectral Range**: 400-700nm (8 channels)
- **ADC Resolution**: 16-bit
- **Data Output Rate**: Up to 100Hz (configurable)
- **Operating Temperature**: 0-40℃
- **Storage Temperature**: -20-60℃
- **WiFi Standard**: IEEE 802.11 b/g/n

## 11. Maintenance and Care

- Keep sensor window clean
- Avoid direct strong light exposure to sensor
- Regularly check for firmware updates
- Avoid humid and high temperature environments
- Use original power adapter

---

**Technical Support**: If encountering problems, please record the abnormal information displayed by the device and contact technical support personnel (Teng email:tenwonyun@gmail.com).

**Version Information**: This manual corresponds to firmware version v2.0.0