# Spectrometer PC Software User Manual

## Software Overview

The Spectrometer PC Software is a professional application for controlling and monitoring AS7341 spectrometer devices, supporting real-time data acquisition, multi-mode measurement, data recording, and analysis functions. Developed with PyQt5, the software features a user-friendly graphical interface.

---

## System Requirements

### Hardware Requirements

- Recommended RAM: 4GB or above
- Storage Space: At least 100MB available space
- Network Interface: Supports TCP/UDP communication

### Software Requirements

- Operating System: Windows 7/10/11, Linux, macOS
- Python Environment: Python 3.12
- Dependencies: PyQt5, pyqtgraph, pandas, etc.

---

## Installation Steps

### 1. Install Python Environment

Download and install Python 3.7 or higher from the official Python website.

### 2. Install Dependencies

```bash
pip install PyQt5 pyqtgraph pandas
```

### 3. Run the Software

```bash
python Spectrometer_v2_PC.py
```

---

## Interface Functions Detailed Explanation

### 1. Top Status Bar

- **Local IP Setting**: Set the local IP address for software operation
- **Service Status**: Display TCP/UDP server running status
- **Heartbeat Status**: Display heartbeat communication status with device
- **Data Transmission**: Display spectral data reception status
- **Device Status**: Display device connection status
- **Data Stream Status**: Display data stream operation status

### 2. Device Information Panel

Display basic information of connected devices:

- Device name, firmware version, device IP
- MAC address, signal strength (RSSI)
- LED status (AS7341 LED, UV LED)
- Buzzer status
- Data stream mode, status, and count information

### 3. Data Stream Control

- **Start/Stop Data Stream**: Control device data stream start and stop
- **Data Stream Modes**:
  - Continuous transmission mode: Device continuously sends data
  - Specified count mode: Device stops after sending specified count
- **Target Transmission Count**: Set target value for specified count mode
- **Pause/Resume**: Temporarily pause or resume data stream
- **Reset Count**: Reset data stream counter
- **Data Stream Interval**: Set data transmission interval (minimum 400ms)

### 4. Timed Measurement Control (New Feature)

- **Enable Timed Measurement**: Turn on/off timed measurement function
- **Total Measurement Duration**: Set total duration for entire measurement session (1-1440 minutes)
- **Measurement Interval**: Set interval time between each measurement (1-1440 minutes)
- **Immediate Measurement**: Manually trigger single measurement
- **Measurement Status**: Display current measurement progress and status

### 5. Device Parameter Control

- **AS7341 LED Control**: Turn on/off AS7341 LED, adjust brightness (1-20)
- **UV LED Control**: Turn on/off UV LED, adjust brightness (1-20)
- **Buzzer Control**: Turn on/off buzzer
- **Get Device Status**: Manually request device status information
- **Device Reboot**: Restart connected spectrometer device

### 6. Data Recording Control

- **Start Recording**: Begin recording received spectral data
- **Stop Recording**: Stop data recording
- **Save Recording**: Save recorded data as CSV file
- **Clear Data**: Clear all cached and recorded data
- **Data Statistics**: Display current cached and recorded data points count

### 7. Spectral Channel Selection

- 8 spectral channels (F1-F8), corresponding to different wavelength ranges
- Support select all/deselect all functions
- Individual channel display selection available

### 8. X-axis Mode Selection

- **Data Sequence**: Use data packet count as X-axis
- **Timestamp**: Use timestamp as X-axis

---

## Tab Functions

### 1. Real-time Data Tab

Display real-time spectral data curves, supporting multi-channel simultaneous display.

### 2. LED Only Data Tab

Display average measurement data when only LED is turned on.

### 3. UV Only Data Tab

Display average measurement data when only UV light is turned on.

### 4. LED+UV Data Tab

Display average measurement data when both LED and UV light are turned on.

---

## Usage Workflow

### 1. Initial Setup

1. Confirm local IP address is correctly set
2. Ensure device and computer are on the same network
3. Start software and wait for service initialization to complete

### 2. Device Connection

1. Device automatically connects to software after power on
2. Observe device status shows "Online"
3. Confirm data transmission status is normal

### 3. Basic Data Acquisition

1. Enable data stream in "Data Stream Control"
2. Select appropriate data stream mode and interval
3. Observe spectral curves in "Real-time Data" tab

### 4. Timed Measurement

1. Enable function in "Timed Measurement Control"
2. Set total measurement duration and interval
3. Click "Immediate Measurement" or wait for automatic measurement
4. View measurement results in respective tabs

### 5. Data Recording and Saving

1. Click "Start Recording" to begin data collection
2. Click "Stop Recording" after collection completes
3. Use "Save Recording" to export data as CSV file

---

## Advanced Features

### Measurement Sequence Description

Each measurement includes three phases:

1. **LED Only**: Only AS7341 LED turned on, collect 5 data points
2. **UV Only**: Only UV LED turned on, collect 5 data points
3. **LED+UV**: Both LEDs turned on simultaneously, collect 5 data points

### Data File Format

Saved CSV files contain the following fields:

- measurement_index: Measurement sequence number
- measurement_time: Measurement time
- measurement_type: Measurement type (LED Only/UV Only/LED+UV)
- data_index: Data point sequence number
- F1-F8: Spectral intensity values for 8 channels

---

## Troubleshooting

### Common Issues

1. **Device Cannot Connect**
   
   - Check if IP address settings are correct
   - Confirm device and computer are on the same network
   - Check firewall settings

2. **Data Reception Interruption**
   
   - Check network connection stability
   - Confirm UDP port 6699 is not occupied
   - Restart software and device

3. **Command Transmission Failure**
   
   - Check TCP client connection status
   - Confirm device command server is running normally
   - View command response prompts

4. **Abnormal Measurement Data**
   
   - Check LED status settings
   - Confirm device sensor is working properly
   - Check ambient lighting conditions

---

## Important Notes

1. Ensure device firmware version (v2.0.0) is compatible with software
2. Do not set data stream interval too small to avoid data loss
3. Maintain device stability during timed measurements
4. Regularly save important data to prevent accidental loss
5. Stop all data streams and measurements before closing software

---

## Technical Support

If encountering problems, please provide the following information:

1. Software version number
2. Device model and firmware version
3. Error message information
4. Network environment description
5. Problem reproduction steps

---

**Note**: This software is for professional use only. Please comply with relevant safety regulations when using. Commercial use is prohibited without author's permission (Author Teng email: tenwonyun@gmail.com).
