# 智能光谱仪系统 - 搭建与使用指南
[README-EN](https://github.com/twy2020/Handheld-spectrometer/blob/main/README.md)
## 1. 硬件组件清单

请按以下清单准备搭建所需的各个模块：

| 组件  | 型号/规格 | 功能描述 |
| --- | --- | --- |
| 光谱传感器 | RFRobot AS7341（内置LED） | 11通道可见光光谱传感器，含8个光学通道、1个清除通道和1个近红外通道 |
| 主控制器 | ESP32C3 Super Mini | 单核处理器，集成WiFi功能（必需） |
| 显示屏 | SSD1306 128×64 OLED | 实时显示光谱数据、系统状态与菜单界面 |
| 紫外照明系统 | UV LED 365nm x3 | 提供稳定的检测辅助光源 |
| UV LED驱动板 | CN5711 PWM LED驱动板 | 用于驱动和调节UV LED |
| 蜂鸣器 | 无源蜂鸣器（3.3V驱动） | 可选，用于设备操作提示音 |
| 移动电源 | 3.7V锂聚合物电池 | 为设备提供离线供电 |
| Type-C充电模块 | 支持Type-C接口及5V输出的任意模块 | 提供通用Type-C充电功能 |
| 电池充放电管理模块 | 支持锂聚合物电池充放电的任意模块 | 管理3.7V锂电池的充电及边充边用功能 |
| 连接线材 | 适用的绝缘线材 | 用于各模块间的电气连接 |
| 电路基板 | 洞洞板或定制PCB | 根据需求选择电路承载方式 |

## 2. 所需工具

**必需工具：**

- 电烙铁、焊锡丝、助焊剂
- 剥线钳、剪刀、测量工具
- 热熔胶枪
- 万用表

**可选工具：**

- 示波器（非必需）
- 3D打印机（非必须）

## 3. 硬件搭建

### 3.1 电路焊接

请参照模块连接图进行各组件焊接。
![hardware](https://gitlab.igem.org/2025/software-tools/yau-china/-/raw/main/Handheld%20spectrometer/pic/Hardware.png?ref_type=heads)

### 3.2 外壳制作

项目文件的“3D”目录中提供了两个模型文件，可用于制作设备外壳，提升产品化外观。
![3D](https://gitlab.igem.org/2025/software-tools/yau-china/-/raw/main/Handheld%20spectrometer/pic/3D.png?ref_type=heads)

## 4. 设备程序烧录

### 4.1 软件环境配置

**需要安装的软件：**

1. CH341串口驱动
2. Arduino IDE

**Arduino IDE安装步骤：**

- 访问官网下载最新版Arduino IDE：https://www.arduino.cc/en/software
- 安装并启动Arduino应用程序
- 添加ESP32开发板支持

**添加ESP32开发板方法：**

1. 进入 File → Preferences
2. 在“Additional Boards Manager URLs”中添加以下URL：
  
  ```
  https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
  ```
  
3. 进入 Tools → Board → ESP32 Arduino，选择“ESP32C3 Dev Module”
4. 进入 Tools → Port，选择ESP32C3 SuperMini对应的串口
5. **重要**：进入 Tools → USB CDC On Boot，设置为“Enable”（否则无法通过USB进行串口通信）

### 4.2 程序烧录步骤

1. 使用Arduino IDE打开项目中的`Spectrometer_v2.ino`文件
2. 通过USB线连接ESP32C3 Super Mini与电脑
3. 选择正确的端口和开发板类型（ESP32C3 Dev Module）
4. 点击“上传”按钮，等待程序烧录完成

## 5. 上位机软件安装

### 5.1 Python环境配置

**安装方式一：从Python官网安装**

- 下载并安装Python 3.12：https://www.python.org/downloads/release/python-3120/

**安装方式二：通过Anaconda安装**

- 下载Anaconda：https://www.anaconda.com/download

**注意**：请确保已将Python或Conda添加到系统环境变量中，以便在终端中直接使用。

### 5.2 安装依赖包

**使用Conda环境安装：**

```bash
conda create -n SpDevice-PC python=3.12
conda activate SpDevice-PC
pip install PyQT5 pyqtgraph pyqt5-tools pandas
```

**使用Python环境安装：**

```bash
pip install PyQT5 pyqtgraph pyqt5-tools pandas
```

### 5.3 启动软件

在配置好的Conda环境或系统Python环境下运行：

```bash
python Spectrometer_v2_PC.py
```

## 6. 设备使用说明

### 6.1 基础操作

设备可直接实时采集并显示光谱数据于OLED屏幕。
![device_data](https://gitlab.igem.org/2025/software-tools/yau-china/-/raw/main/Handheld%20spectrometer/pic/data.jpg?ref_type=heads)

### 6.2 高级功能

如需使用更多功能，请通过WiFi连接上位机程序。详细操作请参考软件使用手册。

---


**注意**：搭建与使用过程中如有疑问，请参考项目文档或联系作者邮箱：tenwonyun@gmail.com
