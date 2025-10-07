# Smart Spectrometer System - Setup and Usage Guide
[README-中文](https://gitlab.igem.org/2025/software-tools/yau-china/-/blob/main/Handheld%20spectrometer/README-CN.md?ref_type=heads)
## 1. Hardware Components List

Please prepare the following modules required for setup according to this list:

| Component | Model/Specification | Description |
| :--- | :--- | :--- |
| Spectral Sensor | RFRobot AS7341 (with built-in LED) | 11-channel visible light spectral sensor, including 8 optical channels, 1 clear channel, and 1 near-infrared channel |
| Main Controller | ESP32C3 Super Mini | Single-core processor with integrated WiFi (Required) |
| Display | SSD1306 128×64 OLED | Displays real-time spectral data, system status, and menu interface |
| UV Illumination System | UV LED 365nm x3 | Provides stable auxiliary light source for detection |
| UV LED Driver Board | CN5711 PWM LED Driver Board | Used to drive and adjust UV LEDs |
| Buzzer | Passive Buzzer (3.3V drive) | Optional, for device operation prompts |
| Power Bank | 3.7V Lithium Polymer Battery | Provides offline power for the device |
| Type-C Charging Module | Any module supporting Type-C interface and 5V output | Provides universal Type-C charging functionality |
| Battery Charge/Discharge Management Module | Any module supporting LiPo battery charge/discharge | Manages charging and passthrough charging for the 3.7V battery |
| Connecting Wires | Suitable insulated wires | For electrical connections between modules |
| Circuit Substrate | Perfboard or Custom PCB | Choose the circuit carrier method based on needs |

## 2. Required Tools

**Essential Tools:**

- Soldering Iron, Solder Wire, Flux
- Wire Strippers, Scissors, Measuring Tools
- Hot Glue Gun
- Multimeter

**Optional Tools:**

- Oscilloscope (Non-essential)
- 3D Printer (Non-essential)

## 3. Hardware Assembly

### 3.1 Circuit Soldering

Please solder all components according to the module connection diagram.
![hardware](https://gitlab.igem.org/2025/software-tools/yau-china/-/raw/main/Handheld%20spectrometer/pic/Hardware.png?ref_type=heads)

### 3.2 Enclosure Fabrication

The "3D" directory in the project files contains two model files that can be used to create the device enclosure, enhancing the product-like appearance.
![3D](https://gitlab.igem.org/2025/software-tools/yau-china/-/raw/main/Handheld%20spectrometer/pic/3D.png?ref_type=heads)

## 4. Device Firmware Flashing

### 4.1 Software Environment Configuration

**Software to Install:**

1.  CH341 Serial Port Driver
2.  Arduino IDE

**Arduino IDE Installation Steps:**

-   Visit the official website to download the latest Arduino IDE: https://www.arduino.cc/en/software
-   Install and launch the Arduino application
-   Add ESP32 board support

**Method for Adding ESP32 Board:**

1.  Go to File → Preferences
2.  Add the following URL in "Additional Boards Manager URLs":
    ```
    https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
    ```
3.  Go to Tools → Board → ESP32 Arduino, select "ESP32C3 Dev Module"
4.  Go to Tools → Port, select the serial port corresponding to the ESP32C3 SuperMini
5.  **Important**: Go to Tools → USB CDC On Boot, set it to "Enable" (otherwise USB serial communication will not work)

### 4.2 Firmware Flashing Steps

1.  Open the `Spectrometer_v2.ino` file from the project using Arduino IDE
2.  Connect the ESP32C3 Super Mini to the computer via a USB cable
3.  Select the correct Port and Board type (ESP32C3 Dev Module)
4.  Click the "Upload" button and wait for the process to complete

## 5. PC Software Installation

### 5.1 Python Environment Configuration

**Installation Method 1: From Python Official Website**

-   Download and install Python 3.12: https://www.python.org/downloads/release/python-3120/

**Installation Method 2: Via Anaconda**

-   Download Anaconda: https://www.anaconda.com/download

**Note**: Please ensure that Python or Conda has been added to the system environment variables so they can be used directly in the terminal.

### 5.2 Installing Dependencies

**Installation using Conda environment:**

```bash
conda create -n SpDevice-PC python=3.12
conda activate SpDevice-PC
pip install PyQT5 pyqtgraph pyqt5-tools pandas
```

**Installation using Python environment:**

```bash
pip install PyQT5 pyqtgraph pyqt5-tools pandas
```

### 5.3 Starting the Software

Run the following command in the configured Conda environment or system Python environment:

```bash
python Spectrometer_v2_PC.py
```

## 6. Device Usage Instructions

### 6.1 Basic Operation

The device can directly collect and display real-time spectral data on the OLED screen.
![device_data](https://gitlab.igem.org/2025/software-tools/yau-china/-/raw/main/Handheld%20spectrometer/pic/data.jpg?ref_type=heads)

### 6.2 Advanced Features

To use more features, please connect to the PC software via WiFi. Please refer to the software manual for detailed operations.

---

**Note**: If you have any questions during the setup and usage process, please refer to the project documentation or contact the author via email: tenwonyun@gmail.com