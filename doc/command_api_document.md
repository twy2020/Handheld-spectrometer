# AS7341 Spectral Sensor Device Communication Protocol Documentation

## 1. Device Basic Information

- **Device Name**: AS7341_Sensor_Device
- **Device Type**: Spectral_Sensor
- **Firmware Version**: 2.0.0
- **Communication Protocol**: TCP + UDP

## 2. Communication Port Configuration

| Port | Protocol | Purpose                                       | Direction     |
| ---- | -------- | --------------------------------------------- | ------------- |
| 6677 | TCP      | Target server connection, data stream control | Bidirectional |
| 6688 | TCP      | Command server, device control                | Bidirectional |
| 6699 | UDP      | Data stream transmission                      | Device → Host |

## 3. Command Format

All commands are in JSON format and sent via TCP port 6688.

### 3.1 Basic Command Structure

```json
{
  "command": "value",
  "parameter": value
}
```

## 4. Device Control Commands

### 4.1 Data Stream Mode Control

#### Enter Data Stream Mode

```json
{"dataStream": true}
```

#### Exit Data Stream Mode

```json
{"dataStream": false}
```

### 4.2 Data Stream Transmission Control

#### Set Continuous Transmission Mode

```json
{"streamMode": "continuous"}
```

#### Set Fixed Count Transmission Mode

```json
{
  "streamMode": "fixed",
  "streamCount": 100
}
```

#### Set Transmission Count Separately

```json
{"streamCount": 50}
```

#### Pause Data Stream Transmission

```json
{"streamPause": true}
```

#### Resume Data Stream Transmission

```json
{"streamPause": false}
```

#### Reset Transmission Count

```json
{"streamReset": true}
```

#### Set Transmission Interval

```json
{"streamInterval": 200}
```

- Minimum interval: 400ms
- Unit: milliseconds

### 4.3 Device Hardware Control

#### AS7341 LED Control

```json
{"as7341Led": true}
```

```json
{"as7341Led": false}
```

#### AS7341 LED Brightness Setting

```json
{"as7341Brightness": 15}
```

- Range: 1-20

#### UV LED Control

```json
{"uvLed": true}
```

```json
{"uvLed": false}
```

#### UV LED Brightness Setting

```json
{"uvBrightness": 10}
```

- Range: 1-20

#### Buzzer Control

```json
{"buzzer": true}
```

```json
{"buzzer": false}
```

### 4.4 System Commands

#### Get Device Status

```json
{"getDeviceStatus": true}
```

#### Device Reboot

```json
{"reboot": true}
```

## 5. Response Mechanism

### 5.1 Command Response Format

All commands receive JSON format responses:

```json
{"response": "OK"}
```

Or error responses:

```json
{"response": "ERROR: error_message"}
```

### 5.2 Response Timing

- Responses are returned immediately after command processing
- Responses are returned via the original TCP connection
- Non-blocking queue mechanism is used to avoid affecting UDP data streams

## 6. Data Stream Format

### 6.1 UDP Data Stream Format

Sent via UDP port 6699, JSON format:

```json
{
  "t": 1234567890,
  "d": [415, 230, 180, 320, 280, 195, 165, 210],
  "c": 1502,
  "sc": 10
}
```

**Field Description**:

- `t`: Timestamp (milliseconds)
- `d`: Spectral data array [F1, F2, F3, F4, F5, F6, F7, F8]
- `c`: Total packet count
- `sc`: Current stream count (fixed count mode only)

### 6.2 Data Stream Statistics

Statistics output via serial port every 500 packets:

```
UDP Packet Count: 500 (10/10)
```

## 7. Device Status Information

### 7.1 Automatic Transmission Triggers

Device status is automatically sent in the following situations:

1. When target server (6677) connection is established
2. When receiving `{"getDeviceStatus": true}` command
3. When device parameters change (LED, brightness, etc.)

### 7.2 Device Status Format

```json
{
  "type": "deviceStatus",
  "device": "AS7341_Sensor_Device",
  "timestamp": 178162,
  "status": {
    "as7341_led": true,
    "as7341_bright": 1,
    "uv_led": false,
    "uv_bright": 20,
    "buzzer": false,
    "sensor": true,
    "stream_mode": "fixed",
    "stream_paused": true,
    "packet_count": 33,
    "interval": 100,
    "current_count": 10,
    "target_count": 10,
    "remaining": 0
  }
}
```

**Status Field Description**:

- `as7341_led`: AS7341 LED on/off status
- `as7341_bright`: AS7341 LED brightness (1-20)
- `uv_led`: UV LED on/off status
- `uv_bright`: UV LED brightness (1-20)
- `buzzer`: Buzzer on/off status
- `sensor`: Sensor initialization status
- `stream_mode`: Data stream mode ("continuous" | "fixed")
- `stream_paused`: Data stream pause status
- `packet_count`: Total packet count
- `interval`: Data stream interval (ms)
- `current_count`: Current stream count
- `target_count`: Target stream count
- `remaining`: Remaining count

## 8. Connection Status Notifications

### 8.1 Connection Established Notification

```json
{
  "type": "connection",
  "status": "connected",
  "device": "AS7341_Sensor_Device",
  "timestamp": 1234567890,
  "ip": "192.168.1.100",
  "rssi": -65,
  "status": {
    "as7341_led": true,
    "as7341_bright": 12,
    "uv_led": true,
    "uv_bright": 8,
    "buzzer": true,
    "sensor": true
  }
}
```

### 8.2 Connection Disconnected Notification

```json
{
  "type": "connection",
  "status": "disconnected",
  "device": "AS7341_Sensor_Device",
  "timestamp": 1234567890,
  "status": {
    "as7341_led": true,
    "as7341_bright": 12,
    "uv_led": true,
    "uv_bright": 8,
    "buzzer": true,
    "sensor": true
  }
}
```

## 9. Completion Notifications

### 9.1 Data Stream Completion Notification

```json
{
  "type": "streamComplete",
  "device": "AS7341_Sensor_Device",
  "timestamp": 135964,
  "total_packets": 24,
  "stream_mode": "fixed",
  "target_count": 10,
  "actual_count": 10,
  "status": "completed"
}
```

## 10. Error Handling

### 10.1 Common Error Responses

```json
{"response": "ERROR: JSON parse failed"}
{"response": "ERROR: Cannot enter data stream mode"}
{"response": "ERROR: Invalid stream count"}
{"response": "ERROR: Interval too small"}
{"response": "ERROR: Sensor read failed"}
```

### 10.2 Error Handling Mechanism

- Invalid commands return error responses
- Sensor read failures trigger retries
- Network disconnections automatically reconnect (max retries: 3)

## 11. Usage Examples

### 11.1 Complete Workflow

```json
// 1. Get device status
{"getDeviceStatus": true}

// 2. Configure device parameters
{
  "as7341Led": true,
  "as7341Brightness": 15,
  "uvLed": false,
  "streamInterval": 200
}

// 3. Enter data stream mode
{"dataStream": true}

// 4. Set fixed count transmission
{
  "streamMode": "fixed",
  "streamCount": 100
}

// 5. Pause transmission
{"streamPause": true}

// 6. Modify parameters and resume
{
  "as7341Brightness": 10,
  "streamPause": false
}

// 7. Exit data stream mode
{"dataStream": false}
```

### 11.2 Quick Start Data Stream

```json
{
  "dataStream": true,
  "streamMode": "continuous",
  "as7341Led": true,
  "as7341Brightness": 10,
  "streamInterval": 300
}
```

## 12. Important Notes

1. **Connection Order**: Recommended to establish TCP connection first, then send control commands
2. **UDP Stability**: TCP responses use queue mechanism to avoid affecting UDP data streams
3. **Command Frequency**: Avoid sending commands at high frequency (minimum interval recommended: 100ms)
4. **Data Stream Interval**: Minimum interval 400ms, smaller intervals may cause data loss
5. **Network Requirements**: Ensure ports 6677, 6688, 6699 are accessible
6. **Timeout Handling**: Command connection timeout is 30 seconds, automatic disconnection after timeout
7. **Error Recovery**: Device automatically attempts reconnection, host should handle connection interruptions

## 13. Serial Debug Information

Device outputs debug information via serial port (baud rate 115200):

- Command reception and processing status
- Data stream statistics (every 500 packets)
- Connection status changes
- Error information

## 14. Version History

- v2.0.0: Support for data stream modes, device control, status queries
- Added continuous and fixed count transmission modes
- Optimized network communication stability
- Non-blocking response mechanism

---

**Document Version**: 1.0  
**Last Updated**: 2025-09-20  
**Corresponding Firmware Version**: 2.0.0
