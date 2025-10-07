import sys
import time
import json
import csv
import socket
import threading
from datetime import datetime
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QCheckBox, QSpinBox, QGroupBox,
                             QMessageBox, QFileDialog, QComboBox, QLineEdit, QTabWidget)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QMetaObject, Q_ARG, pyqtSlot
import pyqtgraph as pg
import pandas as pd

# ========================== 宏定义 ==========================
TCP_SERVER_PORT = 6677       # 接收设备连接/状态通知
UDP_SERVER_PORT = 6699       # 接收光谱数据
DEVICE_CMD_PORT = 6688       # 设备指令服务器
HEARTBEAT_INTERVAL = 20      # 心跳间隔（秒）
MAX_DATA_CACHE = 1000        # 最大绘图缓存
RECV_BUFFER_SIZE = 4096      # 接收缓冲区
CONNECTION_CHECK_INTERVAL = 10# 连接检查间隔
MIN_STREAM_INTERVAL = 400    # 最小数据流间隔（ms，匹配设备协议）

# 光谱通道配置
CHANNEL_CONFIG = [
    {"name": "F1", "wave": "405-425nm", "color": "#FF0000"},
    {"name": "F2", "wave": "435-455nm", "color": "#FF7F00"},
    {"name": "F3", "wave": "470-490nm", "color": "#FFFF00"},
    {"name": "F4", "wave": "505-525nm", "color": "#00FF00"},
    {"name": "F5", "wave": "545-565nm", "color": "#00FFFF"},
    {"name": "F6", "wave": "580-600nm", "color": "#0000FF"},
    {"name": "F7", "wave": "620-640nm", "color": "#4B0082"},
    {"name": "F8", "wave": "670-690nm", "color": "#9400D3"}
]

# ========================== 工具函数 ==========================
def is_valid_ipv4(ip):
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit():
            return False
        num = int(part)
        if num < 0 or num > 255:
            return False
    return True

def get_local_ip_auto():
    return "192.168.137.1"

# ========================== 网络通信模块 ==========================
class TcpServerThread(QThread):
    device_connected_signal = pyqtSignal(dict)    # 设备连接通知
    device_disconnected_signal = pyqtSignal(str) # 设备断开通知
    device_status_signal = pyqtSignal(dict)      # 设备状态更新
    stream_complete_signal = pyqtSignal(dict)    # 数据流完成通知
    server_status_signal = pyqtSignal(bool, str) # 服务状态
    json_parse_error_signal = pyqtSignal(str)    # JSON解析错误

    def __init__(self, local_ip):
        super().__init__()
        self.local_ip = local_ip
        self.server_socket = None
        self.client_socket = None
        self.client_addr = None
        self.running = False
        self.buffer = b""

    def run(self):
        self.running = True
        try:
            # 创建TCP服务器套接字
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.local_ip, TCP_SERVER_PORT))
            self.server_socket.listen(1)
            self.server_socket.settimeout(1)
            
            status_msg = f"TCP Server启动成功: {self.local_ip}:{TCP_SERVER_PORT}"
            print(f"[TCP Server] {status_msg}")
            self.server_status_signal.emit(True, status_msg)

            while self.running:
                try:
                    # 接受客户端连接
                    client_socket, client_addr = self.server_socket.accept()
                    self.client_socket = client_socket
                    self.client_addr = client_addr
                    client_ip = client_addr[0]
                    
                    print(f"[TCP Server] 设备连接: {client_ip}")
                    self.client_socket.settimeout(1.0)  # 设置读取超时，避免阻塞
                    
                    # 处理客户端数据
                    self.handle_client()
                    
                except socket.timeout:
                    continue  # 超时是正常情况，继续等待新连接
                except OSError as e:
                    # 检查是否是因为服务器停止运行导致的错误
                    if not self.running:
                        break
                    if e.errno == 9:  # Bad file descriptor
                        print(f"[TCP Server] 套接字已关闭，停止接受连接")
                        break
                    else:
                        err_msg = f"套接字错误: {e}"
                        print(f"[TCP Server] {err_msg}")
                        self.server_status_signal.emit(False, err_msg)
                        continue  # 继续运行，不退出线程
                except Exception as e:
                    if self.running:
                        err_msg = f"连接错误: {e}"
                        print(f"[TCP Server] {err_msg}")
                        self.server_status_signal.emit(False, err_msg)
                    # 发生异常时继续运行，不退出线程
                    continue

        except Exception as e:
            if self.running:
                err_msg = f"启动失败: {e}（IP: {self.local_ip}，端口: {TCP_SERVER_PORT}）"
                print(f"[TCP Server] {err_msg}")
                self.server_status_signal.emit(False, err_msg)

        finally:
            # 确保资源被清理
            self.client_disconnect()
            if self.server_socket:
                try:
                    self.server_socket.close()
                except Exception as e:
                    print(f"[TCP Server] 关闭服务器套接字错误: {e}")
                self.server_socket = None
            
            print(f"[TCP Server] 线程已退出")

    def handle_client(self):
        """处理客户端连接和数据接收 - 修复版本"""
        if not self.client_socket or not self.client_addr:
            return
            
        client_ip = self.client_addr[0]
        print(f"[TCP Server] 开始处理客户端: {client_ip}")
        
        try:
            while self.running:
                try:
                    data = self.client_socket.recv(RECV_BUFFER_SIZE)
                    if not data:
                        print(f"[TCP Server] 设备主动断开: {client_ip}")
                        # 注意：不发送断开信号，因为6677端口断开是正常行为
                        break
                        
                    # 处理接收到的数据
                    self.buffer += data
                    while b'\n' in self.buffer:
                        line_end = self.buffer.find(b'\n')
                        line = self.buffer[:line_end]
                        self.buffer = self.buffer[line_end + 1:]
                        
                        if line:
                            try:
                                json_str = line.decode("utf-8", errors="ignore").strip()
                                print(f"[TCP Server] 收到数据: {json_str}")
                                json_data = json.loads(json_str)
                                
                                # 判断数据类型并发送相应信号
                                if json_data.get('type') == 'connection':
                                    print(f"[TCP Server] 发送设备连接信号")
                                    self.device_connected_signal.emit(json_data)
                                elif json_data.get('type') == 'status':
                                    self.device_status_signal.emit(json_data)
                                elif json_data.get('type') == 'stream_complete':
                                    self.stream_complete_signal.emit(json_data)
                                    
                            except json.JSONDecodeError as e:
                                err_msg = f"JSON解析失败: {e}，原始数据: {line}"
                                print(f"[TCP Server] {err_msg}")
                                self.json_parse_error_signal.emit(err_msg)
                
                except socket.timeout:
                    continue  # 超时是正常情况，继续循环
                except ConnectionResetError:
                    print(f"[TCP Server] 连接被重置: {client_ip}")
                    break
                except OSError as e:
                    if e.errno == 9:  # Bad file descriptor
                        print(f"[TCP Server] 套接字已关闭: {client_ip}")
                        break
                    else:
                        print(f"[TCP Server] 套接字错误: {e}")
                        break
                except Exception as e:
                    if self.running:
                        print(f"[TCP Server] 客户端数据接收错误: {e}")
                    break
        
        except Exception as e:
            print(f"[TCP Server] 客户端处理异常: {e}")
        finally:
            print(f"[TCP Server] 客户端处理结束: {client_ip}")
            self.client_disconnect()

    def client_disconnect(self):
        """断开客户端连接"""
        if self.client_socket:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
                self.client_socket.close()
            except Exception as e:
                print(f"[TCP Server] 断开客户端错误: {e}")
            self.client_socket = None
            self.client_addr = None
            self.buffer = b""

    def update_ip(self, new_ip):
        self.local_ip = new_ip

    def stop(self):
        print(f"[TCP Server] 正在停止...")
        self.running = False
        self.client_disconnect()
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception as e:
                print(f"[TCP Server] 关闭服务器错误: {e}")
            self.server_socket = None
        if self.isRunning():
            self.wait(5000)
        print(f"[TCP Server] 已停止")

class UdpServerThread(QThread):
    spectral_data_signal = pyqtSignal(dict)    # 光谱数据信号
    data_status_signal = pyqtSignal(bool)      # 数据传输状态
    server_status_signal = pyqtSignal(bool, str) # 服务状态
    json_parse_error_signal = pyqtSignal(str)  # JSON解析错误

    def __init__(self, local_ip):
        super().__init__()
        self.local_ip = local_ip
        self.server_socket = None
        self.running = False
        self.last_data_time = time.time()  # 添加最后收到数据的时间戳
        self.status_check_timer = None

    def run(self):
        self.running = True
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.local_ip, UDP_SERVER_PORT))
            self.server_socket.settimeout(1)
            status_msg = f"UDP Server启动成功: {self.local_ip}:{UDP_SERVER_PORT}"
            print(f"[UDP Server] {status_msg}")
            self.server_status_signal.emit(True, status_msg)

            self.start_status_check_timer()
            while self.running:
                try:
                    if not self.running:
                        break
                    # 接收UDP数据
                    data, addr = self.server_socket.recvfrom(RECV_BUFFER_SIZE)
                    if not data:
                        continue
                    json_str = data.decode("utf-8", errors="ignore").strip()
                    print(f"[UDP Server] 收到光谱数据: {addr[0]} -> {json_str}")

                    try:
                        json_data = json.loads(json_str)
                        # 验证是否为设备光谱数据
                        if all(key in json_data for key in ["t", "d", "c"]):
                            self.last_data_time = time.time()
                            normalized_data = {
                                "timestamp": json_data["t"],
                                "packetCount": json_data["c"],
                                "data": json_data["d"],
                                "streamCount": json_data.get("sc", 0),
                                "device_ip": addr[0]
                            }
                            self.spectral_data_signal.emit(normalized_data)
                            self.data_status_signal.emit(True)
                        else:
                            print(f"[UDP Server] 忽略无效数据（缺少必要字段）: {json_str}")

                    except json.JSONDecodeError as e:
                        err_msg = f"JSON解析失败: {e}，原始数据: {json_str}"
                        print(f"[UDP Server] {err_msg}")
                        self.json_parse_error_signal.emit(err_msg)

                except socket.timeout:
                    # 超时时检查数据流状态
                    if hasattr(self, 'last_data_time') and time.time() - self.last_data_time > 10:
                        self.data_status_signal.emit(False)
                    continue

                except Exception as e:
                    if self.running:
                        err_msg = f"运行错误: {e}"
                        print(f"[UDP Server] {err_msg}")
                        self.server_status_signal.emit(False, err_msg)
                    break

        except Exception as e:
            if self.running:
                err_msg = f"启动失败: {e}（IP: {self.local_ip}，端口: {UDP_SERVER_PORT}）"
                print(f"[UDP Server] {err_msg}")
                self.server_status_signal.emit(False, err_msg)

        print(f"[UDP Server] 线程已退出")

    def start_status_check_timer(self):
        self.stop_status_check_timer()
        if self.running:
            self.status_check_timer = threading.Timer(3, self.check_data_status)
            self.status_check_timer.start()

    def stop_status_check_timer(self):
        if self.status_check_timer:
            self.status_check_timer.cancel()
            self.status_check_timer = None

    def check_data_status(self):
        if not self.running:
            return
        # 5秒无数据则判定为中断
        if time.time() - self.last_data_time > 5:
            self.data_status_signal.emit(False)
        self.start_status_check_timer()

    def update_ip(self, new_ip):
        self.local_ip = new_ip

    def stop(self):
        print(f"[UDP Server] 正在停止...")
        self.running = False
        self.stop_status_check_timer()
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception as e:
                print(f"[UDP Server] 关闭套接字错误: {e}")
            self.server_socket = None
        self.wait(5000)
        print(f"[UDP Server] 已停止")

class TcpClientThread(QThread):
    """修复版TCP客户端：优化重连逻辑+完整指令支持"""
    cmd_response_signal = pyqtSignal(str)          # 指令响应
    client_status_signal = pyqtSignal(bool, str)   # 客户端状态
    cmd_send_error_signal = pyqtSignal(str)        # 指令发送错误
    heartbeat_sent_signal = pyqtSignal(str)        # 心跳发送成功
    connection_established_signal = pyqtSignal(str)# 连接建立

    def __init__(self, device_ip):
        super().__init__()
        self.device_ip = device_ip  # 修复：使用正确的属性名
        self.client_socket = None
        self.running = False
        self.connected = False
        self.reconnect_count = 0
        self.last_heartbeat_time = 0
        self.heartbeat_timeout = 10  # 心跳超时时间（秒）

    def run(self):
        self.running = True
        self.reconnect_count = 0
        print(f"[TCP Client] 启动，目标设备: {self.device_ip}:{DEVICE_CMD_PORT}")

        while self.running:
            try:
                if not self.connected:
                    if not self.running:
                        break
                    
                    # 重连计数与间隔控制
                    self.reconnect_count += 1
                    print(f"[TCP Client] 第{self.reconnect_count}次尝试连接: {self.device_ip}")
                    
                    # 创建新套接字
                    self.close_socket()
                    self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    self.client_socket.settimeout(10)
                    
                    # 尝试连接
                    print(f"[TCP Client] 正在连接 {self.device_ip}:{DEVICE_CMD_PORT}...")
                    self.client_socket.connect((self.device_ip, DEVICE_CMD_PORT))
                    self.connected = True
                    self.reconnect_count = 0
                    self.last_heartbeat_time = time.time()
                    self.client_socket.settimeout(0.5)
                    
                    print(f"[TCP Client] 连接成功: {self.device_ip}:{DEVICE_CMD_PORT}")
                    self.connection_established_signal.emit(self.device_ip)
                    self.client_status_signal.emit(True, self.device_ip)

                # 连接后的核心逻辑
                if self.connected and self.running:
                    current_time = time.time()

                    # 1. 心跳检测（每HEARTBEAT_INTERVAL秒一次）- 简化心跳，不发送状态查询
                    if current_time - self.last_heartbeat_time >= HEARTBEAT_INTERVAL:
                        if self.send_heartbeat():
                            self.last_heartbeat_time = current_time
                            self.heartbeat_sent_signal.emit(f"心跳发送成功: {self.device_ip}")

                    # 2. 移除频繁的状态查询，由主窗口控制

                    # 3. 心跳超时检测
                    if current_time - self.last_heartbeat_time > self.heartbeat_timeout:
                        print(f"[TCP Client] 心跳超时，重新连接")
                        self.connected = False
                        continue

                    # 4. 非阻塞读取指令响应
                    try:
                        data = self.client_socket.recv(RECV_BUFFER_SIZE)
                        if data:
                            response = data.decode("utf-8", errors="ignore").strip()
                            if response:
                                print(f"[TCP Client] 收到响应: {response}")
                                self.cmd_response_signal.emit(response)
                    except socket.timeout:
                        pass
                    except Exception as e:
                        print(f"[TCP Client] 读取数据错误: {e}")
                        self.connected = False
                        continue

                # 控制循环频率
                time.sleep(0.1)

            except socket.timeout:
                print(f"[TCP Client] 连接超时: {self.device_ip}")
                self.connected = False
            except ConnectionRefusedError:
                print(f"[TCP Client] 连接被拒绝: {self.device_ip}:{DEVICE_CMD_PORT}")
                self.connected = False
                time.sleep(5)
            except Exception as e:
                print(f"[TCP Client] 连接错误: {e}")
                self.connected = False

            # 连接失败后的处理
            if not self.connected and self.running:
                old_connected = self.connected
                self.close_socket()

                if old_connected:
                    print(f"[TCP Client] 连接丢失，尝试重连")
                    self.client_status_signal.emit(False, self.device_ip)

                time.sleep(5)

        print(f"[TCP Client] 线程已退出")
        self.close_socket()

    def close_socket(self):
        """安全关闭套接字 - 修复版本"""
        if self.client_socket:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                self.client_socket.close()
            except:
                pass
            self.client_socket = None
        self.connected = False

    def send_heartbeat(self):
        """发送设备可识别的心跳指令"""
        if not self.connected or not self.client_socket:
            return False
        try:
            heartbeat_cmd = '{"type":"heartbeat"}\n'
            self.client_socket.sendall(heartbeat_cmd.encode("utf-8"))
            print(f"[TCP Client] 发送心跳: {heartbeat_cmd.strip()}")
            return True
        except Exception as e:
            print(f"[TCP Client] 心跳发送失败: {e}")
            self.connected = False
            return False

    def send_cmd(self, cmd_dict):
        """发送控制指令（支持所有设备协议指令）"""
        if not self.running or not self.connected:
            err_msg = "指令发送失败：未连接设备"
            self.cmd_send_error_signal.emit(err_msg)
            return False
        try:
            # 确保指令以\n结尾（设备要求）
            cmd_str = json.dumps(cmd_dict) + "\n"
            self.client_socket.sendall(cmd_str.encode("utf-8"))
            print(f"[TCP Client] 发送指令: {cmd_str.strip()}")
            return True
        except Exception as e:
            err_msg = f"指令发送错误: {e}"
            print(f"[TCP Client] {err_msg}")
            self.cmd_send_error_signal.emit(err_msg)
            self.connected = False
            return False

    def stop(self):
        print(f"[TCP Client] 正在停止...")
        self.running = False
        self.close_socket()
        self.wait(3000)
        print(f"[TCP Client] 已停止")

    def is_connected(self):
        """检查连接状态 - 修复版本"""
        return self.running and self.connected and self.client_socket is not None

# ========================== 数据处理模块 ==========================
class DataProcessor:
    def __init__(self):
        self.spectral_cache = []  # 绘图缓存
        self.recording = False    # 记录状态
        self.record_data = []     # 记录数据
        self.stream_complete = False  # 数据流完成标记

    def get_cache_count(self):
        """获取缓存数据点数"""
        return len(self.spectral_cache)
    
    def get_record_count(self):
        """获取记录数据点数"""
        return len(self.record_data)
    
    def clear_cache_data(self):
        """清空缓存数据"""
        self.spectral_cache = []
        return True
        
    def clear_record_data(self):
        """清空记录数据（仅在非记录状态下）"""
        if not self.recording:
            self.record_data = []
            return True
        return False

    def parse_spectral_data(self, json_data):
        """修复光谱数据解析：匹配设备UDP字段"""
        try:
            # 从标准化后的数据中提取字段（UDP模块已处理字段映射）
            timestamp = json_data.get("timestamp", 0)
            packet_count = json_data.get("packetCount", 0)
            data_list = json_data.get("data", [0]*8)
            stream_count = json_data.get("streamCount", 0)

            # 构建标准光谱数据结构
            spectral_data = {
                "timestamp": timestamp,
                "packetCount": packet_count,
                "streamCount": stream_count,
                "F1": data_list[0], "F2": data_list[1], "F3": data_list[2], "F4": data_list[3],
                "F5": data_list[4], "F6": data_list[5], "F7": data_list[6], "F8": data_list[7]
            }

            # 更新缓存（超出最大长度时删除最旧数据）
            self.spectral_cache.append(spectral_data)
            if len(self.spectral_cache) > MAX_DATA_CACHE:
                self.spectral_cache.pop(0)

            # 记录数据（如果处于记录状态）
            if self.recording:
                self.record_data.append(spectral_data.copy())

            return spectral_data, None

        except Exception as e:
            err_msg = f"解析光谱数据错误: {e}，数据: {json_data}"
            print(f"[DataProcessor] {err_msg}")
            return None, err_msg

    def start_record(self):
        """开始数据记录"""
        self.recording = True
        self.record_data = []
        self.stream_complete = False
        print("[DataProcessor] 开始记录数据")
        return True

    def stop_record(self):
        """停止数据记录"""
        self.recording = False
        record_count = len(self.record_data)
        print(f"[DataProcessor] 停止记录，共{record_count}个数据点")
        return self.record_data, record_count

    def save_to_csv(self, data_list, filename=None):
        """保存数据到CSV"""
        if not data_list:
            return False, "无数据可保存"

        # 生成默认文件名（包含日期时间）
        if not filename:
            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"spectral_data_{now}.csv"
        
        file_path, _ = QFileDialog.getSaveFileName(
            None, "保存光谱数据", filename, "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return False, "取消保存"

        try:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                # CSV字段包含新增的streamCount
                fieldnames = ["timestamp", "packetCount", "streamCount", 
                              "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for data in data_list:
                    writer.writerow(data)
            return True, f"保存成功: {file_path}"
        except Exception as e:
            return False, f"保存错误: {str(e)}"

    def mark_stream_complete(self):
        """标记数据流完成"""
        self.stream_complete = True

# ========================== 主窗口模块 ==========================
class SpectrometerUpperPC(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("光谱仪上位机软件 V1.3（定时测量优化版）")
        self.setGeometry(100, 100, 1300, 850)

        # 核心变量初始化
        self.auto_local_ip = get_local_ip_auto()
        self.current_local_ip = self.auto_local_ip
        self.device_info = None  # 设备基础信息
        self.device_status = None  # 设备实时状态
        self.tcp_server = None
        self.udp_server = None
        self.tcp_client = None
        self.data_processor = DataProcessor()
        self.plot_curves = []  # 绘图曲线
        self.selected_channels = [True]*8  # 通道选择状态
        self.x_axis_mode = "packetCount"  # 横轴模式
        self.connected_device_ip = ""  # 已连接设备IP
        self.data_stream_active = False  # 数据流是否开启

        # 数据流模式控制变量
        self.current_stream_mode = "continuous"  # 默认为持续模式
        self.target_stream_count = 100  # 默认目标计数
        self.stream_paused = False  # 数据流暂停状态

        # 连接状态跟踪
        self.tcp_server_connected = False
        self.tcp_client_connected = False
        self.running = True
        self.mode_transition_in_progress = False
        self.last_status_query_time = 0  # 添加状态查询时间记录

        # 测量相关变量
        self.measurement_data = {
            "led_only": [],
            "uv_only": [], 
            "led_uv": []
        }
        self.current_measurement_group = 0
        self.measurement_plots = {}  # 存储三个标签页的绘图对象
        self.measurement_session_data = {}  # 存储整个测量会话的数据

        # 定时测量变量
        self.timer_measurement_session_active = False
        self.timer_measurement_start_time = None
        self.timer_measurement_duration = 30  # 默认30分钟
        self.timer_measurement_elapsed = 0

        # 添加缺失的测量相关变量
        self.measurement_data_collected = 0
        self.led_only_data = []
        self.uv_only_data = []
        self.led_uv_data = []
        self.measurement_target = 5  # 明确设置每组测量5次

        # 初始化界面
        self.init_ui()

        # 启动网络服务
        self.start_network_services(self.current_local_ip)

        # 定时器：连接状态检查（3秒一次）
        self.connection_check_timer = QTimer(self)
        self.connection_check_timer.timeout.connect(self.check_device_connection)
        self.connection_check_timer.start(CONNECTION_CHECK_INTERVAL * 1000)

        # UI刷新定时器（5Hz，200ms一次）
        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.timeout.connect(self.update_ui)
        self.ui_update_timer.start(200)

        # 定时测量功能变量
        self.timer_measurement_enabled = False
        self.timer_measurement_interval = 300  # 默认5分钟
        self.timer_measurement_remaining = 0
        self.timer_measurement_timer = QTimer(self)
        self.timer_measurement_timer.timeout.connect(self.update_timer_measurement)
        
        # 测量状态机
        self.measurement_state = "idle"  # idle, led_only, uv_only, led_uv
        self.measurement_count = 0
        self.measurement_target = 5  # 每组测量5次
        
        # 修改设备状态查询间隔为10秒
        self.last_status_query_time = 0
        self.status_query_interval = 10  # 10秒一次

    def init_ui(self):
        """初始化UI：添加标签页和定时测量功能"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 1. 顶部状态栏
        status_layout = QHBoxLayout()

        # IP设置区域
        ip_label = QLabel("本机IP:")
        self.ip_input = QLineEdit()
        self.ip_input.setText(self.current_local_ip)
        self.ip_input.setFixedWidth(150)
        self.ip_confirm_btn = QPushButton("确认IP")
        self.ip_confirm_btn.clicked.connect(self.on_ip_confirm)

        # 服务状态
        self.server_status_label = QLabel("服务状态: 初始化中...")
        self.server_status_label.setStyleSheet("color: #666666; padding: 2px 8px;")

        # 心跳状态
        self.heartbeat_status_label = QLabel("心跳状态: 未启动")
        self.heartbeat_status_label.setStyleSheet("color: #FF4444; padding: 2px 8px;")

        # 数据传输状态
        self.data_status_label = QLabel("数据传输: 未连接")
        self.data_status_label.setStyleSheet("background-color: #FF4444; color: white; padding: 2px 8px; border-radius: 4px;")

        # 设备连接状态
        self.device_status_label = QLabel("设备状态: 未连接")
        self.device_status_label.setStyleSheet("background-color: #FF4444; color: white; padding: 2px 8px; border-radius: 4px;")

        # 数据流完成状态
        self.stream_complete_label = QLabel("数据流: 未开始")
        self.stream_complete_label.setStyleSheet("background-color: #FFA000; color: white; padding: 2px 8px; border-radius: 4px;")

        # 组装顶部布局
        status_layout.addWidget(ip_label)
        status_layout.addWidget(self.ip_input)
        status_layout.addWidget(self.ip_confirm_btn)
        status_layout.addSpacing(20)
        status_layout.addWidget(self.server_status_label)
        status_layout.addSpacing(20)
        status_layout.addWidget(self.heartbeat_status_label)
        status_layout.addSpacing(20)
        status_layout.addWidget(self.data_status_label)
        status_layout.addSpacing(10)
        status_layout.addWidget(self.device_status_label)
        status_layout.addSpacing(10)
        status_layout.addWidget(self.stream_complete_label)
        status_layout.addStretch(1)
        main_layout.addLayout(status_layout)

        # 2. 中间区域（左侧控制面板+右侧绘图区）
        middle_layout = QHBoxLayout()

        # 2.1 左侧控制面板 - 放入滚动区域
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(400)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(8, 8, 8, 8)
        
        # 初始化所有左侧面板控件
        self.init_left_panel_controls(left_layout)
        
        scroll_area.setWidget(left_container)
        middle_layout.addWidget(scroll_area)

        # 2.2 右侧绘图区 - 改为标签页
        plot_tabs_widget = QTabWidget()
        
        # 创建四个标签页
        self.real_time_tab = QWidget()
        self.led_only_tab = QWidget()
        self.uv_only_tab = QWidget()
        self.led_uv_tab = QWidget()
        
        # 初始化各个标签页的绘图
        self.init_plot_tab(self.real_time_tab, "实时数据")
        self.init_plot_tab(self.led_only_tab, "LED Only数据")
        self.init_plot_tab(self.uv_only_tab, "UV Only数据") 
        self.init_plot_tab(self.led_uv_tab, "LED+UV数据")
        
        # 添加到标签页
        plot_tabs_widget.addTab(self.real_time_tab, "实时数据")
        plot_tabs_widget.addTab(self.led_only_tab, "LED Only")
        plot_tabs_widget.addTab(self.uv_only_tab, "UV Only")
        plot_tabs_widget.addTab(self.led_uv_tab, "LED+UV")
        
        middle_layout.addWidget(plot_tabs_widget)
        main_layout.addLayout(middle_layout)

        # 3. 底部状态栏
        self.cmd_response_label = QLabel("指令响应: 等待设备连接...")
        self.cmd_response_label.setStyleSheet("color: #666666; padding: 4px; border-top: 1px solid #EEEEEE;")
        main_layout.addWidget(self.cmd_response_label)

    def init_plot_tab(self, tab_widget, title):
        """初始化绘图标签页"""
        layout = QVBoxLayout(tab_widget)
        
        # 标题
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title_label)
        
        # 绘图区域
        plot_widget = pg.PlotWidget()
        plot_widget.setLabel("left", "光谱强度", fontsize=12)
        plot_widget.setLabel("bottom", "测量次数", fontsize=12)
        plot_widget.showGrid(x=True, y=True)
        plot_widget.setDownsampling(mode='peak')
        
        # 初始化绘图曲线
        curves = []
        for config in CHANNEL_CONFIG:
            curve = plot_widget.plot(
                pen=pg.mkPen(color=config["color"], width=2),
                name=f"{config['name']} ({config['wave']})"
            )
            curves.append(curve)
        
        plot_widget.addLegend()
        layout.addWidget(plot_widget)
        
        # 存储绘图对象
        if "实时" in title:
            self.plot_curves = curves
            self.plot_view = plot_widget
        elif "LED Only" in title:
            self.measurement_plots["led_only"] = {
                "plot": plot_widget,
                "curves": curves
            }
        elif "UV Only" in title:
            self.measurement_plots["uv_only"] = {
                "plot": plot_widget, 
                "curves": curves
            }
        elif "LED+UV" in title:
            self.measurement_plots["led_uv"] = {
                "plot": plot_widget,
                "curves": curves
            }

    def init_left_panel_controls(self, left_layout):
        """初始化左侧面板的所有控件组"""
        # 1. 设备信息组
        device_info_group = QGroupBox("设备信息")
        device_info_layout = QVBoxLayout(device_info_group)

        # 基础信息标签
        self.device_name_label = QLabel("设备名称: -")
        self.firmware_label = QLabel("固件版本: -")
        self.device_ip_label = QLabel("设备IP: -")
        self.mac_label = QLabel("MAC地址: -")
        self.rssi_label = QLabel("信号强度: -")
        self.as7341_led_label = QLabel("AS7341 LED: -")
        self.uv_led_label = QLabel("UV LED: -")
        self.buzzer_label = QLabel("蜂鸣器: -")

        # 数据流状态标签
        self.stream_mode_label = QLabel("数据流模式: -")
        self.stream_pause_label = QLabel("数据流状态: -")
        self.current_count_label = QLabel("当前计数: -")
        self.target_count_label = QLabel("目标计数: -")
        self.remaining_count_label = QLabel("剩余计数: -")

        # 添加所有标签到布局
        for label in [self.device_name_label, self.firmware_label, self.device_ip_label,
                    self.mac_label, self.rssi_label, self.as7341_led_label,
                    self.uv_led_label, self.buzzer_label, self.stream_mode_label,
                    self.stream_pause_label, self.current_count_label,
                    self.target_count_label, self.remaining_count_label]:
            device_info_layout.addWidget(label)

        left_layout.addWidget(device_info_group)

        # 2. JSON解析错误显示
        self.json_error_label = QLabel("JSON解析: 正常")
        self.json_error_label.setStyleSheet("color: #2E7D32; padding: 2px 8px;")
        left_layout.addWidget(self.json_error_label)

        # 3. 数据流控制组
        stream_control_group = QGroupBox("数据流控制")
        stream_control_layout = QVBoxLayout(stream_control_group)

        # 数据流开关
        self.stream_switch = QPushButton("开启数据流")
        self.stream_switch.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")
        self.stream_switch.clicked.connect(self.toggle_data_stream)

        # 数据流模式选择
        self.stream_mode_label_ui = QLabel("数据流模式:")
        self.stream_mode_combo = QComboBox()
        self.stream_mode_combo.addItems(["持续发送 (continuous)", "指定次数 (fixed)"])
        self.stream_mode_combo.currentIndexChanged.connect(self.set_stream_mode)
        self.stream_mode_combo.setDisabled(True)

        # 指定次数设置
        self.stream_count_label_ui = QLabel("目标发送次数:")
        self.stream_count_spin = QSpinBox()
        self.stream_count_spin.setRange(1, 10000)
        self.stream_count_spin.setValue(self.target_stream_count)
        self.stream_count_spin.setDisabled(True)
        self.set_count_btn = QPushButton("设置目标次数")
        self.set_count_btn.clicked.connect(self.set_stream_count)
        self.set_count_btn.setDisabled(True)

        # 暂停/继续按钮
        self.stream_pause_btn = QPushButton("暂停数据流")
        self.stream_pause_btn.setStyleSheet("background-color: #FFC107; color: black; padding: 8px;")
        self.stream_pause_btn.clicked.connect(self.toggle_stream_pause)
        self.stream_pause_btn.setDisabled(True)

        # 重置计数按钮
        self.stream_reset_btn = QPushButton("重置计数")
        self.stream_reset_btn.setStyleSheet("background-color: #FF9800; color: white; padding: 8px;")
        self.stream_reset_btn.clicked.connect(self.reset_stream_count)
        self.stream_reset_btn.setDisabled(True)

        # 数据流间隔设置
        self.stream_interval_label = QLabel(f"数据流间隔 (ms, ≥{MIN_STREAM_INTERVAL}):")
        self.stream_interval_spin = QSpinBox()
        self.stream_interval_spin.setRange(MIN_STREAM_INTERVAL, 5000)
        self.stream_interval_spin.setValue(1000)
        self.stream_interval_spin.setDisabled(True)
        self.set_interval_btn = QPushButton("设置间隔")
        self.set_interval_btn.clicked.connect(self.set_stream_interval)
        self.set_interval_btn.setDisabled(True)

        # 组装数据流控制布局
        stream_control_layout.addWidget(self.stream_switch)
        stream_control_layout.addWidget(self.stream_mode_label_ui)
        stream_control_layout.addWidget(self.stream_mode_combo)
        stream_control_layout.addWidget(self.stream_count_label_ui)
        stream_control_layout.addWidget(self.stream_count_spin)
        stream_control_layout.addWidget(self.set_count_btn)
        stream_control_layout.addWidget(self.stream_pause_btn)
        stream_control_layout.addWidget(self.stream_reset_btn)
        stream_control_layout.addWidget(self.stream_interval_label)
        stream_control_layout.addWidget(self.stream_interval_spin)
        stream_control_layout.addWidget(self.set_interval_btn)

        left_layout.addWidget(stream_control_group)

        # 4. 定时测量控制组（新增）
        timer_measure_group = QGroupBox("定时测量控制")
        timer_measure_layout = QVBoxLayout(timer_measure_group)

        # 启用定时测量
        self.timer_measure_enable = QCheckBox("启用定时测量")
        self.timer_measure_enable.stateChanged.connect(self.toggle_timer_measurement)
        timer_measure_layout.addWidget(self.timer_measure_enable)
        
        # 测量总时长设置
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("测量总时长(分钟):"))
        self.timer_duration_spin = QSpinBox()
        self.timer_duration_spin.setRange(1, 1440)  # 1分钟到24小时
        self.timer_duration_spin.setValue(30)  # 默认30分钟
        self.timer_duration_spin.valueChanged.connect(self.update_timer_duration)
        duration_layout.addWidget(self.timer_duration_spin)
        timer_measure_layout.addLayout(duration_layout)
        
        # 测量间隔设置
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("测量间隔(分钟):"))
        self.timer_interval_spin = QSpinBox()
        self.timer_interval_spin.setRange(1, 1440)
        self.timer_interval_spin.setValue(5)
        self.timer_interval_spin.valueChanged.connect(self.update_timer_interval)
        interval_layout.addWidget(self.timer_interval_spin)
        timer_measure_layout.addLayout(interval_layout)
        
        # 剩余时间显示
        self.timer_remaining_label = QLabel("下次测量: 未启用")
        self.timer_remaining_label.setStyleSheet("color: #666666; font-size: 11px;")
        timer_measure_layout.addWidget(self.timer_remaining_label)
        
        # 总时长进度
        self.timer_progress_label = QLabel("总进度: 0/30分钟")
        self.timer_progress_label.setStyleSheet("color: #666666; font-size: 11px;")
        timer_measure_layout.addWidget(self.timer_progress_label)
        
        # 立即测量按钮
        self.instant_measure_btn = QPushButton("立即测量")
        self.instant_measure_btn.setStyleSheet("background-color: #9C27B0; color: white; padding: 6px;")
        self.instant_measure_btn.clicked.connect(self.start_instant_measurement)
        self.instant_measure_btn.setDisabled(True)
        timer_measure_layout.addWidget(self.instant_measure_btn)
        
        # 测量状态显示
        self.measurement_status_label = QLabel("测量状态: 空闲")
        self.measurement_status_label.setStyleSheet("color: #666666; font-size: 11px;")
        timer_measure_layout.addWidget(self.measurement_status_label)
        
        # 测量统计
        self.measurement_stats_label = QLabel("已完成测量: 0次")
        self.measurement_stats_label.setStyleSheet("color: #666666; font-size: 11px;")
        timer_measure_layout.addWidget(self.measurement_stats_label)

        left_layout.addWidget(timer_measure_group)

        # 5. 设备参数控制组
        param_control_group = QGroupBox("设备参数控制")
        param_control_layout = QVBoxLayout(param_control_group)

        # AS7341 LED控制
        self.as7341_led_switch = QCheckBox("AS7341 LED 开启")
        self.as7341_led_switch.setDisabled(True)
        self.as7341_led_switch.stateChanged.connect(self.set_as7341_led)

        # AS7341 LED亮度
        self.as7341_bright_label = QLabel("AS7341 LED亮度 (1-20):")
        self.as7341_bright_spin = QSpinBox()
        self.as7341_bright_spin.setRange(1, 20)
        self.as7341_bright_spin.setValue(10)
        self.as7341_bright_spin.setDisabled(True)
        self.as7341_bright_spin.valueChanged.connect(self.set_as7341_bright)

        # UV LED控制
        self.uv_led_switch = QCheckBox("UV LED 开启")
        self.uv_led_switch.setDisabled(True)
        self.uv_led_switch.stateChanged.connect(self.set_uv_led)

        # UV LED亮度
        self.uv_bright_label = QLabel("UV LED亮度 (1-20):")
        self.uv_bright_spin = QSpinBox()
        self.uv_bright_spin.setRange(1, 20)
        self.uv_bright_spin.setValue(10)
        self.uv_bright_spin.setDisabled(True)
        self.uv_bright_spin.valueChanged.connect(self.set_uv_bright)

        # 蜂鸣器控制
        self.buzzer_switch = QCheckBox("蜂鸣器 开启")
        self.buzzer_switch.setDisabled(True)
        self.buzzer_switch.stateChanged.connect(self.set_buzzer)

        # 设备控制按钮
        self.get_status_btn = QPushButton("获取设备状态")
        self.get_status_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px;")
        self.get_status_btn.clicked.connect(self.get_device_status)
        self.get_status_btn.setDisabled(True)

        self.reboot_btn = QPushButton("设备重启")
        self.reboot_btn.setStyleSheet("background-color: #F44336; color: white; padding: 8px;")
        self.reboot_btn.clicked.connect(self.reboot_device)
        self.reboot_btn.setDisabled(True)

        # 组装参数控制布局
        for widget in [self.as7341_led_switch, self.as7341_bright_label, self.as7341_bright_spin,
                    self.uv_led_switch, self.uv_bright_label, self.uv_bright_spin,
                    self.buzzer_switch, self.get_status_btn, self.reboot_btn]:
            param_control_layout.addWidget(widget)

        left_layout.addWidget(param_control_group)

        # 6. 增强版数据记录控制组
        self.init_enhanced_record_controls(left_layout)

        # 7. 通道选择组
        channel_select_group = QGroupBox("光谱通道选择")
        channel_select_layout = QVBoxLayout(channel_select_group)

        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.select_all_channels)
        self.select_none_btn = QPushButton("全不选")
        self.select_none_btn.clicked.connect(self.select_no_channels)

        channel_select_layout.addWidget(self.select_all_btn)
        channel_select_layout.addWidget(self.select_none_btn)

        # 通道复选框
        for i, config in enumerate(CHANNEL_CONFIG):
            checkbox = QCheckBox(f"{config['name']} ({config['wave']})")
            checkbox.setChecked(True)
            checkbox.setObjectName(f"channel_checkbox_{i}")
            checkbox.stateChanged.connect(lambda state, idx=i: self.update_selected_channels(idx, state))
            channel_select_layout.addWidget(checkbox)
            self.selected_channels[i] = True

        left_layout.addWidget(channel_select_group)

        # 8. 横轴模式选择
        x_axis_group = QGroupBox("横轴模式")
        x_axis_layout = QVBoxLayout(x_axis_group)

        self.x_axis_combo = QComboBox()
        self.x_axis_combo.addItems(["数据序号 (packetCount)", "时间戳 (timestamp)"])
        self.x_axis_combo.currentIndexChanged.connect(self.change_x_axis_mode)
        x_axis_layout.addWidget(self.x_axis_combo)

        left_layout.addWidget(x_axis_group)
        
        # 添加弹性空间
        left_layout.addStretch(1)

    # ========================== 定时测量功能 ==========================
    def toggle_timer_measurement(self, state):
        """启用/禁用定时测量"""
        if state == Qt.Checked:
            if not self.tcp_client or not self.tcp_client.is_connected():
                QMessageBox.warning(self, "警告", "未连接设备，无法启用定时测量！")
                self.timer_measure_enable.setChecked(False)
                return
                
            # 初始化测量会话
            self.timer_measurement_session_active = True
            self.timer_measurement_start_time = time.time()
            self.timer_measurement_elapsed = 0
            self.current_measurement_group = 0
            
            # 初始化会话数据存储
            self.measurement_session_data = {
                "session_start": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "measurements": []
            }
            
            self.timer_measurement_enabled = True
            self.timer_measurement_interval = self.timer_interval_spin.value() * 60  # 转换为秒
            self.timer_measurement_duration = self.timer_duration_spin.value() * 60  # 转换为秒
            self.timer_measurement_remaining = 0  # 立即开始第一次测量
            
            self.timer_measurement_timer.start(1000)  # 1秒一次
            
            self.timer_remaining_label.setText(f"下次测量: 立即开始")
            self.instant_measure_btn.setEnabled(True)
            self.measurement_stats_label.setText("已完成测量: 0次")
            
            self.cmd_response_label.setText(f"指令响应: 定时测量已启用，总时长{self.timer_duration_spin.value()}分钟，间隔{self.timer_interval_spin.value()}分钟")
            
        else:
            self.timer_measurement_enabled = False
            self.timer_measurement_session_active = False
            self.timer_measurement_timer.stop()
            self.timer_remaining_label.setText("下次测量: 未启用")
            self.timer_progress_label.setText("总进度: 0/30分钟")
            self.instant_measure_btn.setDisabled(True)
            self.measurement_status_label.setText("测量状态: 空闲")
            
            # 保存完整的测量会话数据
            if self.measurement_session_data["measurements"]:
                self.save_measurement_session()
            
            self.cmd_response_label.setText("指令响应: 定时测量已禁用")

    def update_timer_duration(self, value):
        """更新测量总时长"""
        if self.timer_measurement_enabled:
            self.timer_measurement_duration = value * 60
            self.timer_progress_label.setText(f"总进度: {self.timer_measurement_elapsed//60}/{value}分钟")

    def update_timer_interval(self, value):
        """更新测量间隔"""
        if self.timer_measurement_enabled:
            self.timer_measurement_interval = value * 60

    def update_timer_measurement(self):
        """定时测量计时器更新 - 修复进度计算"""
        if not self.timer_measurement_enabled:
            return
            
        # 更新总进度
        if self.timer_measurement_session_active:
            current_time = time.time()
            elapsed_seconds = current_time - self.timer_measurement_start_time
            self.timer_measurement_elapsed = elapsed_seconds
            
            progress_minutes = int(elapsed_seconds // 60)
            total_minutes = self.timer_duration_spin.value()
            progress_percent = (elapsed_seconds / self.timer_measurement_duration) * 100
            
            self.timer_progress_label.setText(f"总进度: {progress_minutes}/{total_minutes}分钟 ({progress_percent:.1f}%)")
            
            # 检查是否达到总时长
            if elapsed_seconds >= self.timer_measurement_duration:
                self.timer_measure_enable.setChecked(False)
                QMessageBox.information(self, "测量完成", f"定时测量已完成！共完成{self.current_measurement_group}次测量")
                return
        
        self.timer_measurement_remaining -= 1
        
        if self.timer_measurement_remaining <= 0:
            # 时间到，开始测量序列
            self.start_single_measurement()
            self.timer_measurement_remaining = self.timer_measurement_interval
            minutes = self.timer_measurement_remaining // 60
            seconds = self.timer_measurement_remaining % 60
            self.timer_remaining_label.setText(f"下次测量: {minutes:02d}:{seconds:02d}")
        else:
            minutes = self.timer_measurement_remaining // 60
            seconds = self.timer_measurement_remaining % 60
            self.timer_remaining_label.setText(f"下次测量: {minutes:02d}:{seconds:02d}")

    def start_instant_measurement(self):
        """立即开始测量 - 修复版本"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接设备，无法开始测量！")
            return
        
        # 检查UDP数据流
        if not self.check_udp_stream_before_measurement():
            return
            
        self.start_measurement_sequence()

    def start_single_measurement(self):
        """开始单次测量 - 修复：确保数据流处于正确状态"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接设备，无法开始测量！")
            return
            
        print("[Measurement] 开始单次测量")
        
        # 确保数据流处于运行状态
        if not self.data_stream_active:
            QMessageBox.warning(self, "警告", "请先开启数据流！")
            return
            
        if self.stream_paused:
            QMessageBox.warning(self, "警告", "数据流处于暂停状态，请先继续数据流！")
            return
        
        self.measurement_state = "led_only"
        self.measurement_count = 0
        
        # 重置当前测量数据
        self.led_only_data = []
        self.uv_only_data = []
        self.led_uv_data = []
        
        # 确保所有灯关闭
        self.tcp_client.send_cmd({"as7341Led": False})
        self.tcp_client.send_cmd({"uvLed": False})
        
        # 开始LED only测量
        QTimer.singleShot(1000, self.start_led_only_measurement)

    def start_led_only_measurement(self):
        """开始LED only测量 - 修复：使用QTimer进行可靠的定时收集"""
        print("[Measurement] 开始LED only测量")
        self.measurement_status_label.setText("测量状态: LED Only测量中...")
        self.measurement_count = 0
        self.led_only_data = []  # 清空之前的数据
        
        # 开启LED，关闭UV
        self.tcp_client.send_cmd({"as7341Led": True})
        self.tcp_client.send_cmd({"uvLed": False})
        
        # 等待LED稳定，然后开始收集
        QTimer.singleShot(1000, self.start_led_only_collection)

    def start_led_only_collection(self):
        """开始LED only数据收集 - 使用定时器确保收集5次"""
        self.measurement_count = 0
        self.collect_led_only_data()

    def collect_led_only_data(self):
        """收集LED only数据 - 修复：确保收集5次"""
        if self.measurement_count < 5:  # 明确收集5次
            # 获取当前光谱数据
            if self.data_processor.spectral_cache:
                latest_data = self.data_processor.spectral_cache[-1].copy()
                latest_data["measurement_type"] = "led_only"
                latest_data["measurement_index"] = self.measurement_count
                latest_data["measurement_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.led_only_data.append(latest_data)
                print(f"[Measurement] LED Only 第{self.measurement_count + 1}次数据收集完成")
            
            self.measurement_count += 1
            
            if self.measurement_count < 5:
                # 继续收集，间隔500ms
                QTimer.singleShot(500, self.collect_led_only_data)
            else:
                # LED only测量完成
                print(f"[Measurement] LED only测量完成，收集{len(self.led_only_data)}个数据点")
                self.tcp_client.send_cmd({"as7341Led": False})  # 关闭LED
                QTimer.singleShot(1000, self.start_uv_only_measurement)  # 等待1秒后开始UV测量
        else:
            # 安全退出
            print(f"[Measurement] LED only测量完成")
            self.tcp_client.send_cmd({"as7341Led": False})

    # 同样修复 UV Only 和 LED+UV 的测量函数
    def start_uv_only_measurement(self):
        """开始UV only测量"""
        print("[Measurement] 开始UV only测量")
        self.measurement_status_label.setText("测量状态: UV Only测量中...")
        self.measurement_count = 0
        self.uv_only_data = []  # 清空之前的数据
        
        # 开启UV，关闭LED
        self.tcp_client.send_cmd({"uvLed": True})
        self.tcp_client.send_cmd({"as7341Led": False})
        
        # 等待UV稳定
        QTimer.singleShot(1000, self.start_uv_only_collection)

    def start_uv_only_collection(self):
        """开始UV only数据收集"""
        self.measurement_count = 0
        self.collect_uv_only_data()

    def collect_uv_only_data(self):
        """收集UV only数据 - 确保收集5次"""
        if self.measurement_count < 5:
            # 获取当前光谱数据
            if self.data_processor.spectral_cache:
                latest_data = self.data_processor.spectral_cache[-1].copy()
                latest_data["measurement_type"] = "uv_only"
                latest_data["measurement_index"] = self.measurement_count
                latest_data["measurement_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.uv_only_data.append(latest_data)
                print(f"[Measurement] UV Only 第{self.measurement_count + 1}次数据收集完成")
            
            self.measurement_count += 1
            
            if self.measurement_count < 5:
                # 继续收集，间隔500ms
                QTimer.singleShot(500, self.collect_uv_only_data)
            else:
                # UV only测量完成
                print(f"[Measurement] UV only测量完成，收集{len(self.uv_only_data)}个数据点")
                self.tcp_client.send_cmd({"uvLed": False})  # 关闭UV
                QTimer.singleShot(1000, self.start_led_uv_measurement)  # 等待1秒后开始LED+UV测量
        else:
            # 安全退出
            print(f"[Measurement] UV only测量完成")
            self.tcp_client.send_cmd({"uvLed": False})

    def start_led_uv_measurement(self):
        """开始LED+UV测量"""
        print("[Measurement] 开始LED+UV测量")
        self.measurement_status_label.setText("测量状态: LED+UV测量中...")
        self.measurement_count = 0
        self.led_uv_data = []  # 清空之前的数据
        
        # 同时开启LED和UV
        self.tcp_client.send_cmd({"as7341Led": True})
        self.tcp_client.send_cmd({"uvLed": True})
        
        # 等待稳定
        QTimer.singleShot(1000, self.start_led_uv_collection)

    def start_led_uv_collection(self):
        """开始LED+UV数据收集"""
        self.measurement_count = 0
        self.collect_led_uv_data()

    def collect_led_uv_data(self):
        """收集LED+UV数据 - 确保收集5次"""
        if self.measurement_count < 5:
            # 获取当前光谱数据
            if self.data_processor.spectral_cache:
                latest_data = self.data_processor.spectral_cache[-1].copy()
                latest_data["measurement_type"] = "led_uv"
                latest_data["measurement_index"] = self.measurement_count
                latest_data["measurement_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.led_uv_data.append(latest_data)
                print(f"[Measurement] LED+UV 第{self.measurement_count + 1}次数据收集完成")
            
            self.measurement_count += 1
            
            if self.measurement_count < 5:
                # 继续收集，间隔500ms
                QTimer.singleShot(500, self.collect_led_uv_data)
            else:
                # LED+UV测量完成
                print(f"[Measurement] LED+UV测量完成，收集{len(self.led_uv_data)}个数据点")
                # 关闭所有灯
                self.tcp_client.send_cmd({"as7341Led": False})
                self.tcp_client.send_cmd({"uvLed": False})
                
                # 保存本次测量数据到会话
                self.save_single_measurement()
                
                # 更新测量绘图
                self.update_measurement_plots()
                
                # 重置测量状态
                self.measurement_state = "idle"
                self.measurement_status_label.setText("测量状态: 完成")
                
                # 更新统计信息
                self.current_measurement_group += 1
                self.measurement_stats_label.setText(f"已完成测量: {self.current_measurement_group}次")
                
                # 显示完成消息
                total_points = len(self.led_only_data) + len(self.uv_only_data) + len(self.led_uv_data)
                success_msg = f"第{self.current_measurement_group}次测量完成！共收集{total_points}个数据点"
                self.cmd_response_label.setText(f"指令响应: {success_msg}")
                print(f"[Measurement] {success_msg}")
        else:
            # 安全退出
            print(f"[Measurement] LED+UV测量完成")
            self.tcp_client.send_cmd({"as7341Led": False})
            self.tcp_client.send_cmd({"uvLed": False})

    def save_single_measurement(self):
        """保存单次测量数据到会话"""
        measurement_data = {
            "measurement_index": self.current_measurement_group,
            "measurement_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "led_only": self.led_only_data.copy(),
            "uv_only": self.uv_only_data.copy(),
            "led_uv": self.led_uv_data.copy()
        }
        
        self.measurement_session_data["measurements"].append(measurement_data)
        
        # 实时保存到CSV文件
        self.save_measurement_to_csv()

    def save_measurement_to_csv(self):
        """将测量数据保存到CSV文件"""
        if not self.measurement_session_data["measurements"]:
            return False
            
        try:
            # 生成文件名（包含会话开始时间）
            base_filename = f"measurement_session_{self.measurement_session_data['session_start']}.csv"
            
            with open(base_filename, "w", newline="", encoding="utf-8") as f:
                fieldnames = [
                    "measurement_index", "measurement_time", "measurement_type", "data_index",
                    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for measurement in self.measurement_session_data["measurements"]:
                    # 写入LED Only数据
                    for i, data in enumerate(measurement["led_only"]):
                        row_data = {
                            "measurement_index": measurement["measurement_index"],
                            "measurement_time": measurement["measurement_time"],
                            "measurement_type": "LED Only",
                            "data_index": i,
                            "F1": data["F1"], "F2": data["F2"], "F3": data["F3"], "F4": data["F4"],
                            "F5": data["F5"], "F6": data["F6"], "F7": data["F7"], "F8": data["F8"]
                        }
                        writer.writerow(row_data)
                    
                    # 写入UV Only数据
                    for i, data in enumerate(measurement["uv_only"]):
                        row_data = {
                            "measurement_index": measurement["measurement_index"],
                            "measurement_time": measurement["measurement_time"],
                            "measurement_type": "UV Only", 
                            "data_index": i,
                            "F1": data["F1"], "F2": data["F2"], "F3": data["F3"], "F4": data["F4"],
                            "F5": data["F5"], "F6": data["F6"], "F7": data["F7"], "F8": data["F8"]
                        }
                        writer.writerow(row_data)
                    
                    # 写入LED+UV数据
                    for i, data in enumerate(measurement["led_uv"]):
                        row_data = {
                            "measurement_index": measurement["measurement_index"],
                            "measurement_time": measurement["measurement_time"],
                            "measurement_type": "LED+UV",
                            "data_index": i,
                            "F1": data["F1"], "F2": data["F2"], "F3": data["F3"], "F4": data["F4"],
                            "F5": data["F5"], "F6": data["F6"], "F7": data["F7"], "F8": data["F8"]
                        }
                        writer.writerow(row_data)
            
            print(f"[Measurement] 测量数据已保存: {base_filename}")
            return True
        except Exception as e:
            print(f"[Measurement] 保存测量数据失败: {e}")
            return False

    def save_measurement_session(self):
        """保存完整的测量会话数据"""
        if not self.measurement_session_data["measurements"]:
            return
            
        success = self.save_measurement_to_csv()
        if success:
            QMessageBox.information(self, "测量完成", 
                                f"测量会话数据已保存！\n"
                                f"总测量次数: {len(self.measurement_session_data['measurements'])}\n"
                                f"文件名: measurement_session_{self.measurement_session_data['session_start']}.csv")

    def update_measurement_plots(self):
        """更新所有测量绘图"""
        if not self.measurement_session_data["measurements"]:
            return
            
        # 为每个测量类型准备数据
        led_only_avg_data = []
        uv_only_avg_data = []
        led_uv_avg_data = []
        
        for measurement in self.measurement_session_data["measurements"]:
            # 计算每个测量类型的平均值
            if measurement["led_only"]:
                avg_led = self.calculate_average_measurement(measurement["led_only"])
                led_only_avg_data.append(avg_led)
            
            if measurement["uv_only"]:
                avg_uv = self.calculate_average_measurement(measurement["uv_only"])
                uv_only_avg_data.append(avg_uv)
                
            if measurement["led_uv"]:
                avg_led_uv = self.calculate_average_measurement(measurement["led_uv"])
                led_uv_avg_data.append(avg_led_uv)
        
        # 更新绘图
        self.update_single_measurement_plot("led_only", led_only_avg_data)
        self.update_single_measurement_plot("uv_only", uv_only_avg_data)
        self.update_single_measurement_plot("led_uv", led_uv_avg_data)

    def calculate_average_measurement(self, data_list):
        """计算测量数据的平均值"""
        if not data_list:
            return None
            
        avg_data = {"F1": 0, "F2": 0, "F3": 0, "F4": 0, "F5": 0, "F6": 0, "F7": 0, "F8": 0}
        
        for data in data_list:
            for channel in ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]:
                avg_data[channel] += data[channel]
        
        for channel in avg_data:
            avg_data[channel] /= len(data_list)
            
        return avg_data

    def update_single_measurement_plot(self, measurement_type, data_list):
        """更新单个测量类型的绘图"""
        if measurement_type not in self.measurement_plots:
            return

        plot_data = self.measurement_plots[measurement_type]
        curves = plot_data["curves"]
        
        if not data_list:
            return

        # 更新绘图数据
        x_data = list(range(1, len(data_list) + 1))  # 测量次数从1开始
        for i, (curve, config) in enumerate(zip(curves, CHANNEL_CONFIG)):
            if self.selected_channels[i]:
                y_data = [data[config["name"]] for data in data_list]
                curve.setData(x_data, y_data)
            else:
                curve.clear()

    # ========================== 其他必要方法 ==========================
    # 由于代码长度限制，以下只列出关键修改，其他方法保持原样
    def reconnect_client(self):
        """重新连接TCP客户端（自动连接模式）"""
        if self.manual_connection_enabled:
            print(f"[Reconnect] 手动连接模式，跳过自动重连")
            return
            
        if not self.connected_device_ip:
            print(f"[Reconnect] 无连接设备IP，跳过重连")
            return
            
        print(f"[Reconnect] 尝试重新连接设备: {self.connected_device_ip}")
        self.ensure_tcp_client_connected(self.connected_device_ip)

    def init_enhanced_record_controls(self, parent_layout):
        """初始化增强版数据记录控制组"""
        record_control_group = QGroupBox("数据记录控制")
        record_control_layout = QVBoxLayout(record_control_group)
        
        # 数据统计信息
        stats_layout = QHBoxLayout()
        
        # 缓存数据统计
        cache_stats_layout = QVBoxLayout()
        self.cache_data_label = QLabel("绘图缓存: 0 点")
        self.cache_data_label.setStyleSheet("color: #666666; font-size: 11px;")
        cache_stats_layout.addWidget(self.cache_data_label)
        
        # 记录数据统计
        record_stats_layout = QVBoxLayout()
        self.record_data_label = QLabel("已记录: 0 点")
        self.record_data_label.setStyleSheet("color: #666666; font-size: 11px;")
        record_stats_layout.addWidget(self.record_data_label)
        
        stats_layout.addLayout(cache_stats_layout)
        stats_layout.addLayout(record_stats_layout)
        record_control_layout.addLayout(stats_layout)
        
        # 控制按钮
        buttons_layout = QHBoxLayout()
        
        self.start_record_btn = QPushButton("开始记录")
        self.start_record_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 6px;")
        self.start_record_btn.clicked.connect(self.start_data_record)
        
        self.stop_record_btn = QPushButton("停止记录")
        self.stop_record_btn.setStyleSheet("background-color: #FF9800; color: white; padding: 6px;")
        self.stop_record_btn.clicked.connect(self.stop_data_record)
        self.stop_record_btn.setDisabled(True)
        
        buttons_layout.addWidget(self.start_record_btn)
        buttons_layout.addWidget(self.stop_record_btn)
        record_control_layout.addLayout(buttons_layout)
        
        # 数据管理按钮
        manage_layout = QHBoxLayout()
        
        self.save_record_btn = QPushButton("保存记录")
        self.save_record_btn.setStyleSheet("background-color: #9C27B0; color: white; padding: 6px;")
        self.save_record_btn.clicked.connect(self.save_data_record)
        self.save_record_btn.setDisabled(True)
        
        self.clear_data_btn = QPushButton("清空数据")
        self.clear_data_btn.setStyleSheet("background-color: #F44336; color: white; padding: 6px;")
        self.clear_data_btn.clicked.connect(self.clear_all_data)
        
        manage_layout.addWidget(self.save_record_btn)
        manage_layout.addWidget(self.clear_data_btn)
        record_control_layout.addLayout(manage_layout)
        
        parent_layout.addWidget(record_control_group)

    @pyqtSlot(bool, str)
    def on_cmd_client_status_change(self, connected, device_ip):
        """指令服务器状态变化：更新UI+触发重连"""
        print(f"[MainWindow] 指令服务器状态变化: 连接={connected}, IP={device_ip}")
        self.tcp_client_connected = connected

        if connected:
            # 连接恢复：启用控件
            if not self.device_status_label.text().startswith("设备状态: 在线"):
                self.device_status_label.setText(f"设备状态: 在线（指令服务器已连接）")
                self.device_status_label.setStyleSheet("background-color: #4CAF50; color: white; padding: 2px 8px; border-radius: 4px;")
            self.enable_all_controls(True)
        else:
            # 连接断开：禁用控件+提示
            self.device_status_label.setText(f"设备状态: 离线（指令服务器断开）")
            self.device_status_label.setStyleSheet("background-color: #FFA000; color: white; padding: 2px 8px; border-radius: 4px;")
            self.heartbeat_status_label.setText("心跳状态: 中断")
            self.heartbeat_status_label.setStyleSheet("color: #FF4444; padding: 2px 8px;")
            self.enable_all_controls(False)

            # 自动重连（如果TCP Server仍连接）
            if self.tcp_server_connected and self.running:
                QTimer.singleShot(3000, self.reconnect_client)

    @pyqtSlot(dict)
    def on_stream_complete(self, stream_data):
        """处理数据流完成通知（设备发送fixed模式完成时触发）"""
        print(f"[MainWindow] 收到数据流完成通知: {stream_data}")
        self.data_processor.mark_stream_complete()
        self.stream_paused = True

        # 更新UI状态
        self.stream_complete_label.setText("数据流: 已完成")
        self.stream_complete_label.setStyleSheet("background-color: #4CAF50; color: white; padding: 2px 8px; border-radius: 4px;")
        self.stream_pause_btn.setText("继续数据流")
        self.stream_pause_label.setText(f"数据流状态: 已完成")

        # 提取完成信息并显示
        total_packets = stream_data.get("total_packets", 0)
        target_count = stream_data.get("target_count", 0)
        actual_count = stream_data.get("actual_count", 0)
        status_msg = f"数据流完成！总数据包: {total_packets}, 目标计数: {target_count}, 实际计数: {actual_count}"
        self.cmd_response_label.setText(f"指令响应: {status_msg}")
        QMessageBox.information(self, "数据流完成", status_msg)

        # 如果处于记录状态，自动停止记录
        if self.data_processor.recording:
            self.stop_data_record()


    @pyqtSlot(dict)
    def on_device_status_updated(self, device_status_data):
        """处理设备状态更新（新增：设备参数变更时触发）"""
        print(f"[MainWindow] 收到设备状态更新: {device_status_data}")
        self.device_status = device_status_data
        # 更新UI
        QMetaObject.invokeMethod(self, "update_device_info_ui", Qt.QueuedConnection,
                               Q_ARG(dict, device_status_data))
        
    @pyqtSlot(dict)
    def update_device_info_ui(self, device_data):
        """修复设备信息UI更新：正确处理所有状态字段"""
        print(f"[UI Update] 更新设备信息: {device_data}")
        
        # 提取基础信息
        device_ip = device_data.get("ip", "") or device_data.get("device_ip", "") or self.connected_device_ip
        device_status = device_data.get("status", {})
        device_name = device_data.get("device", "AS7341_Sensor_Device")
        firmware_ver = device_data.get("firmware", "2.0.0")

        # 更新基础信息标签
        self.device_name_label.setText(f"设备名称: {device_name}")
        self.firmware_label.setText(f"固件版本: {firmware_ver}")
        self.device_ip_label.setText(f"设备IP: {device_ip}")

        # 解析硬件状态
        as7341_led = device_status.get("as7341_led", False)
        as7341_bright = device_status.get("as7341_bright", 10)
        uv_led = device_status.get("uv_led", False)
        uv_bright = device_status.get("uv_bright", 10)
        buzzer = device_status.get("buzzer", False)
        sensor_ready = device_status.get("sensor", False)

        # 更新硬件状态标签
        self.as7341_led_label.setText(f"AS7341 LED: {'开启' if as7341_led else '关闭'}")
        self.uv_led_label.setText(f"UV LED: {'开启' if uv_led else '关闭'}")
        self.buzzer_label.setText(f"蜂鸣器: {'开启' if buzzer else '关闭'}")

        # 同步控件状态（避免UI与设备状态不一致）
        self.as7341_led_switch.setChecked(bool(as7341_led))
        self.as7341_bright_spin.setValue(as7341_bright)
        self.uv_led_switch.setChecked(bool(uv_led))
        self.uv_bright_spin.setValue(uv_bright)
        self.buzzer_switch.setChecked(bool(buzzer))

        # 解析数据流状态
        stream_mode = device_status.get("stream_mode", "continuous")
        stream_paused = device_status.get("stream_paused", False)
        current_count = device_status.get("current_count", 0)
        target_count = device_status.get("target_count", 0)
        remaining_count = device_status.get("remaining", 0)

        # 更新数据流状态标签
        self.stream_mode_label.setText(f"数据流模式: {stream_mode}")
        self.stream_pause_label.setText(f"数据流状态: {'暂停' if stream_paused else '运行中'}")
        self.current_count_label.setText(f"当前计数: {current_count}")
        self.target_count_label.setText(f"目标计数: {target_count}")
        self.remaining_count_label.setText(f"剩余计数: {remaining_count}")

        # 同步本地数据流状态
        self.current_stream_mode = stream_mode
        self.stream_paused = stream_paused
        self.target_stream_count = target_count
        
        # 更新UI控件
        self.stream_mode_combo.setCurrentIndex(0 if stream_mode == "continuous" else 1)
        self.stream_count_spin.setValue(target_count)
        self.stream_pause_btn.setText("继续数据流" if stream_paused else "暂停数据流")

        # 强制UI刷新
        self.update()
        QtWidgets.QApplication.processEvents()

    def enable_all_controls(self, enable):
        """统一启用/禁用所有控制控件"""
        print(f"[UI] 启用控制控件: {enable}")
        
        # 数据流控制
        self.stream_switch.setEnabled(enable)
        self.stream_mode_combo.setEnabled(enable)
        self.stream_count_spin.setEnabled(enable and self.current_stream_mode == "fixed")
        self.set_count_btn.setEnabled(enable)
        self.stream_pause_btn.setEnabled(enable and self.data_stream_active)
        self.stream_reset_btn.setEnabled(enable and self.current_stream_mode == "fixed")
        self.stream_interval_spin.setEnabled(enable)
        self.set_interval_btn.setEnabled(enable)
        
        # 定时测量控制
        self.timer_measure_enable.setEnabled(enable)
        self.timer_duration_spin.setEnabled(enable)
        self.timer_interval_spin.setEnabled(enable)
        self.instant_measure_btn.setEnabled(enable and self.timer_measurement_enabled)
        
        # 设备参数控制
        self.as7341_led_switch.setEnabled(enable)
        self.as7341_bright_spin.setEnabled(enable)
        self.uv_led_switch.setEnabled(enable)
        self.uv_bright_spin.setEnabled(enable)
        self.buzzer_switch.setEnabled(enable)
        self.get_status_btn.setEnabled(enable)
        self.reboot_btn.setEnabled(enable)
        
        # 强制UI刷新
        self.update()
        QtWidgets.QApplication.processEvents()

    def update_data_status(self, is_normal):
        """更新数据传输状态UI（优化颜色提示）"""
        if is_normal:
            self.data_status_label.setText("数据传输: 正常")
            self.data_status_label.setStyleSheet("background-color: #4CAF50; color: white; padding: 2px 8px; border-radius: 4px;")
        else:
            self.data_status_label.setText("数据传输: 中断")
            self.data_status_label.setStyleSheet("background-color: #FF4444; color: white; padding: 2px 8px; border-radius: 4px;")
            # 数据中断时提示
            if self.data_stream_active:
                self.cmd_response_label.setText("指令响应: 警告 - 光谱数据传输中断")
        
    @pyqtSlot(str)
    def on_json_parse_error(self, err_msg):
        """JSON解析错误UI提示（优化显示）"""
        self.json_error_label.setText(f"JSON解析: 错误")
        self.json_error_label.setStyleSheet("color: #C62828; padding: 2px 8px;")
        self.cmd_response_label.setText(f"指令响应: JSON解析错误: {err_msg[:50]}...")  # 截断长错误信息
        QMessageBox.warning(self, "JSON解析错误", err_msg)

    # 由于代码长度限制，以下方法保持原有实现，只列出方法签名
    def on_ip_confirm(self):
        new_ip = self.ip_input.text().strip()

        if not is_valid_ipv4(new_ip):
            QMessageBox.warning(self, "IP格式错误", f"请输入有效的IPv4地址（如：192.168.1.100），当前输入：{new_ip}")
            self.ip_input.setText(self.current_local_ip)
            return

        if new_ip == self.current_local_ip:
            QMessageBox.information(self, "IP未变化", f"当前IP已为：{new_ip}，无需修改")
            return

        # 停止现有服务
        self.stop_network_services()
        self.server_status_label.setText(f"服务状态: 正在切换IP至 {new_ip}...")
        QtWidgets.QApplication.processEvents()

        # 更新IP并重启服务
        self.current_local_ip = new_ip
        self.start_network_services(new_ip)

        # 重置设备连接状态
        self.on_device_disconnected("")

    def start_network_services(self, local_ip):
        """启动TCP/UDP服务"""
        # 启动TCP Server
        self.tcp_server = TcpServerThread(local_ip)
        self.tcp_server.device_connected_signal.connect(self.on_device_connected)
        self.tcp_server.device_disconnected_signal.connect(self.on_device_disconnected)
        self.tcp_server.device_status_signal.connect(self.on_device_status_updated)
        self.tcp_server.stream_complete_signal.connect(self.on_stream_complete)
        self.tcp_server.server_status_signal.connect(self.on_server_status_change)
        self.tcp_server.json_parse_error_signal.connect(self.on_json_parse_error)
        self.tcp_server.start()

        # 启动UDP Server
        self.udp_server = UdpServerThread(local_ip)
        self.udp_server.spectral_data_signal.connect(self.on_spectral_data_received)
        self.udp_server.data_status_signal.connect(self.update_data_status)
        self.udp_server.server_status_signal.connect(self.on_server_status_change)
        self.udp_server.json_parse_error_signal.connect(self.on_json_parse_error)
        self.udp_server.start()

    def stop_network_services(self):
        """停止所有网络服务"""
        if self.tcp_server:
            self.tcp_server.stop()
            self.tcp_server = None

        if self.udp_server:
            self.udp_server.stop()
            self.udp_server = None

        if self.tcp_client:
            self.tcp_client.stop()
            self.tcp_client = None

    def on_device_connected(self, device_info):
        """设备连接：修复竞争条件"""
        print(f"[MainWindow] 收到设备连接信息: {device_info}")
        
        # 立即更新设备信息，不等待TCP Client连接
        self.device_info = device_info
        device_ip = device_info.get("ip", "") or device_info.get("device_ip", "")

        if not device_ip or not is_valid_ipv4(device_ip):
            return

        # 更新连接状态
        self.connected_device_ip = device_ip
        self.tcp_server_connected = True  # 确保标记为已连接
        
        print(f"[MainWindow] 设备发现: {device_ip}")

        # 立即更新UI状态为连接中
        self.device_status_label.setText(f"设备状态: 连接指令服务器...")
        self.device_status_label.setStyleSheet("background-color: #FFC107; color: black; padding: 2px 8px; border-radius: 4px;")
        
        # 更新设备信息UI
        QMetaObject.invokeMethod(self, "update_device_info_ui", Qt.QueuedConnection,
                            Q_ARG(dict, device_info))

        # 启动TCP Client
        self.ensure_tcp_client_connected(device_ip)

    @pyqtSlot(str)
    def on_cmd_response(self, response):
        """指令响应UI更新（解析设备响应JSON）"""
        try:
            # 尝试解析设备响应（可能为JSON格式）
            response_json = json.loads(response)
            if "response" in response_json:
                self.cmd_response_label.setText(f"指令响应: {response_json['response']}")
            else:
                self.cmd_response_label.setText(f"指令响应: 收到设备数据: {response[:50]}...")
        except json.JSONDecodeError:
            # 非JSON响应直接显示
            self.cmd_response_label.setText(f"指令响应: {response}")
    
    @pyqtSlot(str)
    def on_heartbeat_sent(self, msg):
        """心跳状态更新（优化显示）"""
        print(f"[Heartbeat] {msg}")
        self.heartbeat_status_label.setText(f"心跳状态: 正常（{HEARTBEAT_INTERVAL}秒/次）")
        self.heartbeat_status_label.setStyleSheet("color: #2E7D32; padding: 2px 8px;")

    @pyqtSlot(str)
    def on_cmd_send_error(self, err_msg):
        """指令发送错误提示（优化弹窗）"""
        self.cmd_response_label.setText(f"指令响应: {err_msg}")
        QMessageBox.warning(self, "指令发送错误", err_msg + "\n可能是设备连接已断开，请检查设备状态")

    def send_measurement_commands(self):
        """发送测量相关指令 - 优化版本"""
        # 批量发送指令，避免频繁发送
        commands = [
            {"as7341Led": False},
            {"uvLed": False}
        ]
        
        # 延迟发送指令，避免冲突
        for i, cmd in enumerate(commands):
            QTimer.singleShot(i * 200, lambda c=cmd: self.tcp_client.send_cmd(c))

    def check_udp_stream_before_measurement(self):
        """测量前检查UDP数据流状态"""
        if not hasattr(self.udp_server, 'last_data_time') or time.time() - self.udp_server.last_data_time > 5:
            reply = QMessageBox.question(self, "UDP数据流中断", 
                                    "UDP数据流已中断，测量可能无法获取数据。\n是否继续测量？",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return False
        return True

    def on_server_status_change(self, is_success, status_msg):
        """更新服务状态UI"""
        if is_success:
            self.server_status_label.setText(f"服务状态: {status_msg}")
            self.server_status_label.setStyleSheet("color: #2E7D32; padding: 2px 8px;")
        else:
            self.server_status_label.setText(f"服务状态: {status_msg}")
            self.server_status_label.setStyleSheet("color: #C62828; padding: 2px 8px;")
            QMessageBox.warning(self, "服务启动失败", status_msg + "\n请检查IP或端口是否被占用")

    def update_ui(self):
        """定期刷新UI（同步控件与设备状态）"""
        if self.device_info and self.connected_device_ip and self.tcp_client:
            # 同步LED、蜂鸣器开关状态（避免UI与设备不一致）
            if self.device_status:
                device_status = self.device_status.get("status", {})
                self.as7341_led_switch.setChecked(device_status.get("as7341_led", False))
                self.uv_led_switch.setChecked(device_status.get("uv_led", False))
                self.buzzer_switch.setChecked(device_status.get("buzzer", False))

            # 同步数据流状态按钮文本
            if self.data_stream_active:
                self.stream_pause_btn.setText("继续数据流" if self.stream_paused else "暂停数据流")

    def ensure_tcp_client_connected(self, device_ip):
        """确保TCP Client连接到设备的6688端口"""
        # 如果已有连接且是同一设备，忽略
        if (self.tcp_client and self.tcp_client.is_connected() and 
            self.connected_device_ip == device_ip):
            print(f"[MainWindow] TCP Client已连接: {device_ip}")
            return
            
        # 停止旧Client
        if self.tcp_client:
            print(f"[MainWindow] 停止旧TCP Client")
            self.tcp_client.stop()
            self.tcp_client = None
            QThread.msleep(300)  # 增加等待时间确保线程完全停止

        # 创建新TCP Client
        print(f"[MainWindow] 启动TCP Client连接: {device_ip}:6688")
        self.tcp_client = TcpClientThread(device_ip)
        self.tcp_client.cmd_response_signal.connect(self.on_cmd_response)
        self.tcp_client.client_status_signal.connect(self.on_cmd_client_status_change)
        self.tcp_client.cmd_send_error_signal.connect(self.on_cmd_send_error)
        self.tcp_client.heartbeat_sent_signal.connect(self.on_heartbeat_sent)
        self.tcp_client.connection_established_signal.connect(self.on_client_connection_established)
        self.tcp_client.start()

        print(f"[MainWindow] 指令服务器Client启动完成")

        # 初始化UI状态
        self.json_error_label.setText("JSON解析: 正常")
        self.json_error_label.setStyleSheet("color: #2E7D32; padding: 2px 8px;")
        self.device_status_label.setText(f"设备状态: TCP连接成功，等待指令服务器响应...")
        self.device_status_label.setStyleSheet("background-color: #FFC107; color: black; padding: 2px 8px; border-radius: 4px;")

    @pyqtSlot(str)
    def on_client_connection_established(self, device_ip):
        """指令服务器连接成功：立即更新UI状态"""
        print(f"[MainWindow] 指令服务器连接成功: {device_ip}")
        self.tcp_client_connected = True

        # 立即更新设备状态UI
        self.device_status_label.setText(f"设备状态: 在线（指令服务器已连接）")
        self.device_status_label.setStyleSheet("background-color: #4CAF50; color: white; padding: 2px 8px; border-radius: 4px;")
        
        # 立即启用所有控制控件
        self.enable_all_controls(True)
        
        # 立即更新心跳状态
        self.heartbeat_status_label.setText("心跳状态: 正常")
        self.heartbeat_status_label.setStyleSheet("color: #2E7D32; padding: 2px 8px;")

        # 发送测试指令确认连接
        if self.tcp_client and self.tcp_client.is_connected():
            print(f"[MainWindow] 发送连接测试指令")
            self.tcp_client.send_cmd({"getDeviceStatus": True})

    def on_device_disconnected(self, device_ip):
        """设备断开：修复错误判断逻辑"""
        print(f"[MainWindow] 收到设备断开信号: {device_ip}")
        
        # 只有当断开的是当前连接的设备，并且TCP Client也断开时才处理
        if device_ip != self.connected_device_ip:
            print(f"[MainWindow] 忽略非当前设备断开: {device_ip}")
            return
            
        # 检查TCP Client是否还连接着
        tcp_client_still_connected = (self.tcp_client and 
                                    self.tcp_client.is_connected())
        
        if tcp_client_still_connected:
            print(f"[MainWindow] TCP Client仍连接，忽略6677端口断开: {device_ip}")
            return
            
        device_ip = device_ip or self.connected_device_ip or "未知IP"
        print(f"[MainWindow] 确认设备完全断开: {device_ip}")
        
        self.handle_real_device_disconnect(device_ip)

    def check_device_connection(self):
        """设备连接状态检查 - 修复频繁查询问题"""
        if not self.connected_device_ip:
            return

        # 主要依靠TCP Client（6688）连接状态判断设备在线
        if self.tcp_client:
            client_connected = self.tcp_client.is_connected()
            if client_connected != self.tcp_client_connected:
                print(f"[Connection Check] TCP Client状态变化: {self.tcp_client_connected} -> {client_connected}")
                self.on_cmd_client_status_change(client_connected, self.connected_device_ip)
        
        # 减少状态查询频率：只在需要时查询
        current_time = time.time()
        should_query_status = (
            current_time - self.last_status_query_time > self.status_query_interval and
            self.tcp_client and 
            self.tcp_client.is_connected() and
            not self.measurement_state != "idle"  # 测量期间不查询
        )
        
        if should_query_status:
            self.tcp_client.send_cmd({"getDeviceStatus": True})
            self.last_status_query_time = current_time
            print(f"[Status Query] 发送状态查询")
    
    def sync_connection_states(self):
        """同步连接状态，避免状态不一致"""
        if not self.connected_device_ip:
            # 没有连接设备，确保所有状态为断开
            if self.tcp_client_connected:
                self.tcp_client_connected = False
            return
            
        # 检查TCP Client状态
        if self.tcp_client:
            actual_client_connected = self.tcp_client.is_connected()
            if actual_client_connected != self.tcp_client_connected:
                print(f"[Sync] TCP Client状态不一致: UI={self.tcp_client_connected}, Actual={actual_client_connected}")
                self.tcp_client_connected = actual_client_connected

    def on_spectral_data_received(self, json_data):
        """处理UDP光谱数据 - 增强版，自动更新统计"""
        spectral_data, err_msg = self.data_processor.parse_spectral_data(json_data)
        if not spectral_data:
            self.cmd_response_label.setText(f"指令响应: 光谱数据解析错误: {err_msg}")
            return

        # 更新绘图数据
        x_data = [d[self.x_axis_mode] for d in self.data_processor.spectral_cache]
        for i, (curve, config) in enumerate(zip(self.plot_curves, CHANNEL_CONFIG)):
            if self.selected_channels[i]:
                y_data = [d[config["name"]] for d in self.data_processor.spectral_cache]
                curve.setData(x_data, y_data)
            else:
                curve.clear()

        # 同步数据流计数UI
        if "streamCount" in spectral_data:
            current_count = spectral_data["streamCount"]
            remaining_count = self.target_stream_count - current_count if self.current_stream_mode == "fixed" else 0
            self.current_count_label.setText(f"当前计数: {current_count}")
            self.remaining_count_label.setText(f"剩余计数: {remaining_count}")
        
        # 自动更新数据统计（每次收到新数据时）
        self.update_data_stats()

    def toggle_data_stream(self):
        """开启/关闭数据流 - 修复：开启时同时发送暂停指令"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法控制数据流！")
            return

        if not self.data_stream_active:
            # 开启数据流但立即暂停 - 使用组合指令
            cmd = {
                "dataStream": True,
                "streamPause": True,  # 同时发送暂停指令
                "streamMode": self.current_stream_mode,
                "streamInterval": self.stream_interval_spin.value()
            }
            
            if self.current_stream_mode == "fixed":
                cmd["streamCount"] = self.target_stream_count
            
            success = self.tcp_client.send_cmd(cmd)
            if success:
                self.data_stream_active = True
                self.stream_paused = True  # 设置为暂停状态
                self.stream_switch.setText("关闭数据流")
                self.stream_switch.setStyleSheet("background-color: #FF4444; color: white; padding: 8px;")
                self.stream_pause_btn.setEnabled(True)
                self.stream_pause_btn.setText("继续数据流")
                self.stream_reset_btn.setEnabled(self.current_stream_mode == "fixed")
                self.stream_complete_label.setText("数据流: 已暂停")
                self.stream_complete_label.setStyleSheet("background-color: #FFA000; color: white; padding: 2px 8px; border-radius: 4px;")
                
                # 更新数据流状态显示
                if hasattr(self, 'stream_pause_label'):
                    self.stream_pause_label.setText("数据流状态: 暂停")
                
                self.cmd_response_label.setText("指令响应: 数据流已开启（暂停状态）")
        else:
            # 关闭数据流
            success = self.tcp_client.send_cmd({"dataStream": False})
            if success:
                self.data_stream_active = False
                self.stream_paused = False
                self.stream_switch.setText("开启数据流")
                self.stream_switch.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")
                self.stream_pause_btn.setDisabled(True)
                self.stream_reset_btn.setDisabled(True)
                self.stream_complete_label.setText("数据流: 已停止")
                self.stream_complete_label.setStyleSheet("background-color: #FF4444; color: white; padding: 2px 8px; border-radius: 4px;")
                
                self.cmd_response_label.setText("指令响应: 数据流已关闭")
        
        # 强制刷新UI
        self.update()
        QtWidgets.QApplication.processEvents()

    def set_stream_mode(self, index):
        """设置数据流模式（continuous/fixed）"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法设置数据流模式！")
            return

        # 更新本地模式
        self.current_stream_mode = "continuous" if index == 0 else "fixed"
        # 启用/禁用目标计数控件
        self.stream_count_spin.setEnabled(True if self.current_stream_mode == "fixed" else False)

        # 发送模式指令
        cmd = {"streamMode": self.current_stream_mode}
        # 如果是fixed模式，附加当前目标计数
        if self.current_stream_mode == "fixed":
            self.target_stream_count = self.stream_count_spin.value()
            cmd["streamCount"] = self.target_stream_count
        
        success = self.tcp_client.send_cmd(cmd)
        if success:
            self.cmd_response_label.setText(f"指令响应: 数据流模式已设置为 {self.current_stream_mode}")
            self.stream_pause_label.setText(f"数据流状态: {'运行中' if not self.stream_paused else '暂停'}")
        
    def set_stream_count(self):
        """设置fixed模式的目标发送次数"""
        if self.current_stream_mode != "fixed":
            QMessageBox.warning(self, "警告", "仅在「指定次数模式」下可设置目标次数！")
            return
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法设置目标次数！")
            return

        self.target_stream_count = self.stream_count_spin.value()
        success = self.tcp_client.send_cmd({"streamCount": self.target_stream_count, "streamReset": True})  # 重置计数
        if success:
            self.cmd_response_label.setText(f"指令响应: 目标发送次数已设置为 {self.target_stream_count}（已重置计数）")
            self.current_count_label.setText(f"当前计数: 0")
            self.remaining_count_label.setText(f"剩余计数: {self.target_stream_count}")

    def toggle_stream_pause(self):
        """暂停/继续数据流 - 修复状态同步"""
        if not self.data_stream_active:
            QMessageBox.warning(self, "警告", "数据流未开启，无法暂停/继续！")
            return
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法控制数据流！")
            return

        # 切换暂停状态
        new_pause_state = not self.stream_paused
        cmd = {"streamPause": new_pause_state}
        success = self.tcp_client.send_cmd(cmd)
        
        if success:
            self.stream_paused = new_pause_state
            pause_status = "暂停" if self.stream_paused else "继续"
            self.stream_pause_btn.setText("继续数据流" if self.stream_paused else "暂停数据流")
            
            # 更新状态标签
            if hasattr(self, 'stream_pause_label'):
                self.stream_pause_label.setText(f"数据流状态: {'暂停' if self.stream_paused else '运行中'}")
            
            # 更新完成状态标签
            if self.stream_paused:
                self.stream_complete_label.setText("数据流: 已暂停")
                self.stream_complete_label.setStyleSheet("background-color: #FFA000; color: white; padding: 2px 8px; border-radius: 4px;")
            else:
                self.stream_complete_label.setText("数据流: 运行中")
                self.stream_complete_label.setStyleSheet("background-color: #4CAF50; color: white; padding: 2px 8px; border-radius: 4px;")
            
            self.cmd_response_label.setText(f"指令响应: 数据流已{pause_status}")

    def reset_stream_count(self):
        """重置数据流计数（fixed模式）"""
        if self.current_stream_mode != "fixed":
            QMessageBox.warning(self, "警告", "仅在「指定次数模式」下可重置计数！")
            return
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法重置计数！")
            return

        success = self.tcp_client.send_cmd({"streamReset": True})
        if success:
            self.cmd_response_label.setText(f"指令响应: 数据流计数已重置")
            self.current_count_label.setText(f"当前计数: 0")
            self.remaining_count_label.setText(f"剩余计数: {self.target_stream_count}")

    def set_stream_interval(self):
        """设置数据流间隔（修复最小间隔验证）"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法设置间隔！")
            return

        interval = self.stream_interval_spin.value()
        if interval < MIN_STREAM_INTERVAL:
            QMessageBox.warning(self, "间隔过小", f"数据流最小间隔为 {MIN_STREAM_INTERVAL} ms，请重新设置！")
            self.stream_interval_spin.setValue(MIN_STREAM_INTERVAL)
            return

        success = self.tcp_client.send_cmd({"streamInterval": interval})
        if success:
            self.cmd_response_label.setText(f"指令响应: 数据流间隔已设置为 {interval} ms")

    def set_as7341_led(self, state):
        """控制AS7341 LED（修复指令字段，匹配设备协议）"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法控制设备！")
            return

        led_state = (state == Qt.Checked)
        success = self.tcp_client.send_cmd({"as7341Led": led_state})
        if success:
            self.as7341_led_label.setText(f"AS7341 LED: {'开启' if led_state else '关闭'}")
            self.cmd_response_label.setText(f"指令响应: AS7341 LED已{'开启' if led_state else '关闭'}")

    def set_as7341_bright(self, value):
        """设置AS7341 LED亮度（修复指令字段）"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法控制设备！")
            return

        success = self.tcp_client.send_cmd({"as7341Brightness": value})
        if success:
            self.cmd_response_label.setText(f"指令响应: AS7341 LED亮度已设置为 {value}")

    def set_uv_led(self, state):
        """控制UV LED（修复指令字段）"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法控制设备！")
            return

        led_state = (state == Qt.Checked)
        success = self.tcp_client.send_cmd({"uvLed": led_state})
        if success:
            self.uv_led_label.setText(f"UV LED: {'开启' if led_state else '关闭'}")
            self.cmd_response_label.setText(f"指令响应: UV LED已{'开启' if led_state else '关闭'}")

    def set_uv_bright(self, value):
        """设置UV LED亮度（修复指令字段）"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法控制设备！")
            return

        success = self.tcp_client.send_cmd({"uvBrightness": value})
        if success:
            self.cmd_response_label.setText(f"指令响应: UV LED亮度已设置为 {value}")

    def set_buzzer(self, state):
        """控制蜂鸣器（修复指令字段）"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法控制设备！")
            return

        buzzer_state = (state == Qt.Checked)
        success = self.tcp_client.send_cmd({"buzzer": buzzer_state})
        if success:
            self.buzzer_label.setText(f"蜂鸣器: {'开启' if buzzer_state else '关闭'}")
            self.cmd_response_label.setText(f"指令响应: 蜂鸣器已{'开启' if buzzer_state else '关闭'}")

    def get_device_status(self):
        """主动获取设备状态（新增，匹配设备协议）"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法获取设备状态！")
            return

        success = self.tcp_client.send_cmd({"getDeviceStatus": True})
        if success:
            self.cmd_response_label.setText(f"指令响应: 已发送设备状态请求")

    def reboot_device(self):
        """设备重启（新增，带确认提示）"""
        if not self.tcp_client or not self.tcp_client.is_connected():
            QMessageBox.warning(self, "警告", "未连接指令服务器，无法重启设备！")
            return

        # 确认重启
        reply = QMessageBox.question(self, "确认重启", "确定要重启设备吗？重启后将断开连接并重新初始化！",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            success = self.tcp_client.send_cmd({"reboot": True})
            if success:
                self.cmd_response_label.setText(f"指令响应: 已发送重启指令，设备将在3秒后重启")
                # 重启后自动断开，提前重置UI
                QTimer.singleShot(3000, lambda: self.on_device_disconnected(self.connected_device_ip))

    def start_data_record(self):
        """开始数据记录（修复状态同步）"""
        if not self.data_stream_active:
            reply = QMessageBox.question(self, "数据流未开启", "当前未开启数据流，记录可能无数据！是否继续？",
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return

        success = self.data_processor.start_record()
        if success:
            self.start_record_btn.setDisabled(True)
            self.stop_record_btn.setEnabled(True)
            self.save_record_btn.setDisabled(True)
            self.cmd_response_label.setText("指令响应: 数据记录已开始（等待数据流...）")

    def stop_data_record(self):
        """停止数据记录（修复计数显示）"""
        record_data, record_count = self.data_processor.stop_record()
        self.start_record_btn.setEnabled(True)
        self.stop_record_btn.setDisabled(True)
        self.save_record_btn.setEnabled(True if record_count > 0 else False)
        self.cmd_response_label.setText(f"指令响应: 数据记录已停止（共{record_count}个数据点）")

    def save_data_record(self):
        """保存记录数据（修复错误提示）"""
        success, msg = self.data_processor.save_to_csv(self.data_processor.record_data)
        if success:
            QMessageBox.information(self, "保存成功", msg)
        else:
            QMessageBox.warning(self, "保存失败", msg)

    def clear_all_data(self):
        """清空所有数据（缓存和记录数据）"""
        if self.data_processor.recording:
            QMessageBox.warning(self, "警告", "正在记录中，无法清空数据！")
            return
            
        reply = QMessageBox.question(self, "确认清空", "确定要清空所有数据吗？\n这将清除：\n- 绘图缓存数据\n- 已记录的数据\n此操作不可撤销！",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            # 清空缓存数据
            self.data_processor.clear_cache_data()
            # 清空记录数据
            self.data_processor.clear_record_data()
            # 清空绘图
            for curve in self.plot_curves:
                curve.clear()
            # 更新统计信息
            self.update_data_stats()
            # 更新UI状态
            self.save_record_btn.setDisabled(True)
            self.cmd_response_label.setText("指令响应: 已清空所有数据")
            print("[MainWindow] 已清空所有数据")
    
    def update_data_stats(self):
        """更新数据统计信息"""
        cache_count = self.data_processor.get_cache_count()
        record_count = self.data_processor.get_record_count()
        self.cache_data_label.setText(f"绘图缓存: {cache_count} 点")
        self.record_data_label.setText(f"已记录: {record_count} 点")

    def update_selected_channels(self, channel_idx, state):
        """更新通道选择状态"""
        self.selected_channels[channel_idx] = (state == Qt.Checked)
        # 立即刷新绘图
        if self.data_processor.spectral_cache:
            self.on_spectral_data_received(self.data_processor.spectral_cache[-1] if self.data_processor.spectral_cache else {})

    def select_all_channels(self):
        """全选通道"""
        self.selected_channels = [True]*8
        for i in range(8):
            checkbox = self.findChild(QCheckBox, f"channel_checkbox_{i}")
            if checkbox:
                checkbox.setChecked(True)
        # 刷新绘图
        if self.data_processor.spectral_cache:
            self.on_spectral_data_received(self.data_processor.spectral_cache[-1] if self.data_processor.spectral_cache else {})

    def select_no_channels(self):
        """全不选通道"""
        self.selected_channels = [False]*8
        for i in range(8):
            checkbox = self.findChild(QCheckBox, f"channel_checkbox_{i}")
            if checkbox:
                checkbox.setChecked(False)
        # 清空绘图
        for curve in self.plot_curves:
            curve.clear()

    def change_x_axis_mode(self, index):
        """切换横轴模式（packetCount/timestamp）"""
        self.x_axis_mode = "packetCount" if index == 0 else "timestamp"
        self.plot_view.setLabel("bottom", f"横轴: {self.x_axis_mode}")
        # 刷新绘图
        if self.data_processor.spectral_cache:
            self.on_spectral_data_received(self.data_processor.spectral_cache[-1] if self.data_processor.spectral_cache else {})
    
    def start_measurement_sequence(self):
        """开始测量序列 - 修复版本"""
        print("[Measurement] 开始测量序列")
        self.measurement_state = "led_only"
        self.measurement_count = 0
        self.led_only_data = []
        self.uv_only_data = []
        self.led_uv_data = []
        
        # 记录当前UDP数据包计数，用于检测新数据
        self.measurement_start_packet_count = 0
        if self.data_processor.spectral_cache:
            self.measurement_start_packet_count = self.data_processor.spectral_cache[-1].get("packetCount", 0)
        
        # 确保所有灯关闭
        self.tcp_client.send_cmd({"as7341Led": False})
        self.tcp_client.send_cmd({"uvLed": False})
        
        # 暂停数据流
        self.pause_data_stream_for_measurement()
        
        # 等待设备响应
        QTimer.singleShot(1000, self.start_led_only_measurement)

    def start_led_only_measurement(self):
        """开始LED only测量 - 修复版本"""
        print("[Measurement] 开始LED only测量")
        self.measurement_status_label.setText("测量状态: LED Only测量中...")
        self.measurement_count = 0
        
        # 开启LED，关闭UV
        self.tcp_client.send_cmd({"as7341Led": True})
        self.tcp_client.send_cmd({"uvLed": False})
        
        # 等待LED稳定并开始收集数据
        QTimer.singleShot(1000, self.begin_led_only_data_collection)

    def begin_led_only_data_collection(self):
        """开始LED only数据收集 - 修复版本"""
        print("[Measurement] 开始收集LED only数据")
        self.measurement_count = 0
        self.led_only_data = []
        
        # 记录开始时的数据包计数
        start_packet_count = 0
        if self.data_processor.spectral_cache:
            start_packet_count = self.data_processor.spectral_cache[-1].get("packetCount", 0)
        
        # 开始收集数据，等待UDP数据到来
        self.collect_measurement_data("led_only", start_packet_count)

    def collect_measurement_data(self, measurement_type, start_packet_count, retry_count=0):
        """收集测量数据 - 修复版本：等待UDP数据"""
        max_retries = 10  # 最大重试次数
        retry_delay = 500  # 重试延迟(ms)
        
        # 检查是否有新数据
        current_packet_count = 0
        if self.data_processor.spectral_cache:
            current_packet_count = self.data_processor.spectral_cache[-1].get("packetCount", 0)
        
        if current_packet_count > start_packet_count:
            # 有新数据，收集它
            latest_data = self.data_processor.spectral_cache[-1].copy()
            latest_data["measurement_type"] = measurement_type
            latest_data["measurement_index"] = self.measurement_count
            
            if measurement_type == "led_only":
                self.led_only_data.append(latest_data)
            elif measurement_type == "uv_only":
                self.uv_only_data.append(latest_data)
            elif measurement_type == "led_uv":
                self.led_uv_data.append(latest_data)
            
            self.measurement_count += 1
            print(f"[Measurement] {measurement_type} 收集到第 {self.measurement_count} 个数据点")
            
            if self.measurement_count < self.measurement_target:
                # 继续收集下一个点
                QTimer.singleShot(200, lambda: self.collect_measurement_data(
                    measurement_type, current_packet_count, 0))
            else:
                # 完成当前阶段测量
                self.finish_measurement_stage(measurement_type)
        else:
            # 没有新数据，重试或放弃
            if retry_count < max_retries:
                print(f"[Measurement] {measurement_type} 等待数据中... (重试 {retry_count + 1}/{max_retries})")
                QTimer.singleShot(retry_delay, lambda: self.collect_measurement_data(
                    measurement_type, start_packet_count, retry_count + 1))
            else:
                print(f"[Measurement] {measurement_type} 数据收集超时")
                self.finish_measurement_stage(measurement_type, timeout=True)

    def finish_measurement_stage(self, measurement_type, timeout=False):
        """完成测量阶段 - 修复版本"""
        if measurement_type == "led_only":
            print(f"[Measurement] LED only测量完成，收集{len(self.led_only_data)}个数据点")
            self.tcp_client.send_cmd({"as7341Led": False})  # 关闭LED
            
            if timeout and len(self.led_only_data) == 0:
                QMessageBox.warning(self, "测量失败", "LED Only测量超时，未收到任何数据！")
                self.cancel_measurement_sequence()
                return
                
            QTimer.singleShot(1000, self.start_uv_only_measurement)
            
        elif measurement_type == "uv_only":
            print(f"[Measurement] UV only测量完成，收集{len(self.uv_only_data)}个数据点")
            self.tcp_client.send_cmd({"uvLed": False})  # 关闭UV
            
            if timeout and len(self.uv_only_data) == 0:
                QMessageBox.warning(self, "测量失败", "UV Only测量超时，未收到任何数据！")
                self.cancel_measurement_sequence()
                return
                
            QTimer.singleShot(1000, self.start_led_uv_measurement)
            
        elif measurement_type == "led_uv":
            print(f"[Measurement] LED+UV测量完成，收集{len(self.led_uv_data)}个数据点")
            # 关闭所有灯
            self.tcp_client.send_cmd({"as7341Led": False})
            self.tcp_client.send_cmd({"uvLed": False})
            
            if timeout and len(self.led_uv_data) == 0:
                QMessageBox.warning(self, "测量失败", "LED+UV测量超时，未收到任何数据！")
                self.cancel_measurement_sequence()
                return
            
            # 保存测量数据
            self.save_measurement_data()
            
            # 恢复数据流状态
            if self.data_stream_active:
                self.resume_data_stream_after_measurement()
                
            # 重置测量状态
            self.measurement_state = "idle"
            self.measurement_status_label.setText("测量状态: 完成")
            
            # 显示完成消息
            total_points = len(self.led_only_data) + len(self.uv_only_data) + len(self.led_uv_data)
            status_msg = f"测量完成！共收集{total_points}个数据点"
            if timeout:
                status_msg += " (部分测量超时)"
            self.cmd_response_label.setText(f"指令响应: {status_msg}")
            QMessageBox.information(self, "测量完成", status_msg)

    def cancel_measurement_sequence(self):
        """取消测量序列"""
        print("[Measurement] 取消测量序列")
        # 关闭所有灯
        self.tcp_client.send_cmd({"as7341Led": False})
        self.tcp_client.send_cmd({"uvLed": False})
        
        # 恢复数据流状态
        if self.data_stream_active:
            self.resume_data_stream_after_measurement()
            
        # 重置测量状态
        self.measurement_state = "idle"
        self.measurement_status_label.setText("测量状态: 已取消")
        self.cmd_response_label.setText("指令响应: 测量已取消")
    
    def closeEvent(self, event):
        """窗口关闭处理"""
        self.running = False
        self.timer_measurement_enabled = False
        if self.timer_measurement_timer.isActive():
            self.timer_measurement_timer.stop()
        self.stop_network_services()
        self.connection_check_timer.stop()
        self.ui_update_timer.stop()
        event.accept()

# ========================== 程序入口 ==========================
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setFont(QtGui.QFont("Microsoft YaHei", 9))
    window = SpectrometerUpperPC()
    window.show()
    sys.exit(app.exec_())