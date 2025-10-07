#include <U8g2lib.h>
#include <Bounce2.h>
#include "DFRobot_AS7341.h"
#include <Ticker.h>
#include <EEPROM.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <IPAddress.h>
#include <ArduinoJson.h>
#include <WiFiServer.h>
#include <WiFiUdp.h>

// WiFi配置参数
#define WIFI_SSID_MAX_LEN 32
#define WIFI_PASS_MAX_LEN 64
#define IP_ADDR_MAX_LEN 16
#define TARGET_PORT 6677
#define WIFI_RECONNECT_DELAY 5000
#define TASK_WATCHDOG_TIMEOUT 3000
#define WIFI_CONNECT_TIMEOUT 5000

// WiFi重连相关变量
unsigned long last_reconnect_attempt = 0;
#define WIFI_RECONNECT_INTERVAL 30000  // 增加重连间隔到30秒
uint8_t reconnect_attempt_count = 0;
#define MAX_RECONNECT_ATTEMPTS 3       // 减少最大重连尝试次数

// 添加连接状态跟踪
bool manual_reconnect_triggered = false;
unsigned long last_stable_connection = 0;
#define STABLE_CONNECTION_THRESHOLD 10000  // 10秒稳定连接阈值

// JSON指令相关定义
#define COMMAND_PORT 6688
#define DATA_STREAM_PORT 6699
#define JSON_BUFFER_SIZE 512
#define MIN_DATA_STREAM_INTERVAL 400

// 数据流发送模式控制变量
typedef enum {
    STREAM_MODE_CONTINUOUS = 0,    // 持续发送
    STREAM_MODE_FIXED_COUNT        // 指定次数发送
} StreamMode_t;

StreamMode_t current_stream_mode = STREAM_MODE_CONTINUOUS;
uint32_t stream_count_target = 0;      // 目标发送次数
uint32_t stream_count_current = 0;     // 当前已发送次数
bool stream_paused = false;            // 发送暂停状态

// 添加响应队列机制
#define RESPONSE_QUEUE_SIZE 5
String responseQueue[RESPONSE_QUEUE_SIZE];
int responseQueueHead = 0;
int responseQueueTail = 0;
bool responseQueueFull = false;

// 设备状态更新队列
#define STATUS_QUEUE_SIZE 3
bool statusUpdatePending = false;
unsigned long lastStatusUpdateTime = 0;
#define STATUS_UPDATE_COOLDOWN 1000  // 状态更新冷却时间1秒

bool completionNotificationPending = false;

// EEPROM存储地址映射
#define EEPROM_SIZE 256
#define ADDR_INIT_FLAG    0
#define ADDR_AS7341_LED   1
#define ADDR_AS7341_BRIGHT 2
#define ADDR_UV_LED       3
#define ADDR_UV_BRIGHT    4
#define ADDR_BUZZER_EN    5
#define ADDR_BUZZER_VOL   6
#define ADDR_WIFI_ENABLE  7
#define ADDR_WIFI_SSID    8
#define ADDR_WIFI_PASS   40
#define ADDR_FIXED_IP    104
#define ADDR_TARGET_IP   120

// 硬件配置
#define OLED_SCL 6
#define OLED_SDA 7
#define KEY_UP 3        
#define KEY_SEL 2       
#define KEY_DOWN 4      
#define UV_LED_PIN 1    
#define BUZZER_PIN 5    

// 蜂鸣器参数
#define BUZZER_FREQ 2000
#define BUZZER_BEEP_DURATION 100
#define BUZZER_VOL_MAX 10
#define BUZZER_VOL_TO_PWM(vol) map(vol, 1, BUZZER_VOL_MAX, 25, 255)

// 按键长按时间阈值(ms)
#define LONG_PRESS_THRESHOLD 300

// 内存优化配置
#define MAX_STR_LEN 32
#define SPECTRAL_BUF_LEN 8
char str_buf[MAX_STR_LEN];
uint16_t temp_spectral[SPECTRAL_BUF_LEN];

// ========== 系统模式定义 ==========
typedef enum {
    SYSTEM_MODE_LOCAL = 0,    // 本地模式
    SYSTEM_MODE_DATA_STREAM   // 数据流模式
} SystemMode_t;

SystemMode_t current_system_mode = SYSTEM_MODE_LOCAL;
bool mode_transition_in_progress = false;

// 数据流模式状态变量
bool data_stream_mode_active = false;
bool target_server_connected = false;
unsigned long last_target_connect_attempt = 0;
#define TARGET_CONNECT_RETRY_INTERVAL 10000

// 定时器对象
Ticker keyScanTicker;
Ticker buzzerStopTicker;
Ticker wifiReconnectTicker;
Ticker taskWatchdogTicker;
Ticker dataStreamTicker;

// 按键扫描间隔
#define KEY_SCAN_INTERVAL 10

// 传感器读取控制
unsigned long last_sensor_read = 0;
#define SENSOR_READ_INTERVAL 200

// 全局对象
U8G2_SSD1306_128X64_NONAME_F_SW_I2C u8g2(
  U8G2_R0, OLED_SCL, OLED_SDA, U8X8_PIN_NONE
);
Bounce btn_up = Bounce();
Bounce btn_sel = Bounce();
Bounce btn_down = Bounce();
DFRobot_AS7341 as7341;
WiFiClient targetClient;  // 目标服务器TCP连接

// 状态变量
bool as7341_init_ok = false;
const char* main_menu[] = {
  "1. AS7341 Control", "2. UV LED Control", 
  "3. Buzzer Control", "4. WiFi Settings", "5. Exit"
};
const int MENU_COUNT = 5;
const int VISIBLE_ITEMS = 4;
const int TOTAL_PAGES = 3;
uint16_t spectral_data[SPECTRAL_BUF_LEN] = {0};
uint8_t current_page = 1;
bool in_spectral_mode = true;
int current_menu = 0;
int scroll_offset = 0;
bool in_submenu = false;
bool menu_updated = true;

// 按键相关变量
unsigned long sel_press_start = 0;
unsigned long up_press_start = 0;    
unsigned long down_press_start = 0;  
bool sel_is_pressing = false;
bool up_is_pressing = false;         
bool down_is_pressing = false;       
bool long_press_triggered = false;
bool up_long_triggered = false;      
bool down_long_triggered = false;    
bool sel_was_pressed = false;

// AS7341 LED控制变量
uint8_t as7341_led_bright = 10;
bool as7341_led_state = false;
uint8_t as7341_submenu_type = 0;

// UV灯控制变量
uint8_t uv_led_bright = 10;
bool uv_led_state = false;
uint8_t uv_submenu_type = 0;
#define UV_BRIGHT_TO_PWM(bright) map(bright, 1, 20, 0, 255)

// 蜂鸣器控制变量
bool buzzer_enable = true;
uint8_t buzzer_volume = 5;
uint8_t buzzer_submenu_type = 0;
bool buzzer_beeping = false;

// WiFi相关变量
char wifi_ssid[WIFI_SSID_MAX_LEN] = {0};
char wifi_pass[WIFI_PASS_MAX_LEN] = {0};
char fixed_ip[IP_ADDR_MAX_LEN] = {0};
char target_ip[IP_ADDR_MAX_LEN] = {0};
bool wifi_enable = false;
bool wifi_connected = false;
bool wifi_connecting = false;
uint8_t wifi_submenu_type = 0;
bool wifi_editing_switch = false;
bool wifi_task_running = false;
bool connection_notified = false;
unsigned long last_task_activity = 0;
unsigned long task_start_time = 0;
const char* current_task_name = "";

// WiFi编辑相关变量
bool editing_wifi_ssid = false;
bool editing_wifi_pass = false;
bool editing_fixed_ip = false;
bool editing_target_ip = false;
int wifi_edit_pos = 0;
char wifi_edit_buffer[WIFI_PASS_MAX_LEN] = {0};
bool shift_pressed = false;

// 字符码盘
const char normal_char_set[] = " abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_!@#$%";
const char ip_char_set[] = "0123456789.";
const int normal_char_set_size = sizeof(normal_char_set) - 1;
const int ip_char_set_size = sizeof(ip_char_set) - 1;
int current_char_index = 0;

// JSON指令和数据流相关变量
bool data_stream_enabled = false;
unsigned long last_data_stream_time = 0;
uint32_t data_stream_interval = 100;
WiFiServer commandServer(COMMAND_PORT);
WiFiUDP dataStreamUdp;
DynamicJsonDocument json_doc(JSON_BUFFER_SIZE);

// 数据流统计
uint32_t data_stream_packet_count = 0;
unsigned long data_stream_start_time = 0;

// 设备信息
const char* DEVICE_NAME = "AS7341_Sensor_Device";
const char* DEVICE_TYPE = "Spectral_Sensor";
const char* FIRMWARE_VERSION = "2.0.0";

WiFiClient currentCommandClient;
bool commandClientConnected = false;
unsigned long lastCommandActivity = 0;
#define COMMAND_TIMEOUT 30000


void init_local_mode() {
    Serial.println("初始化本地模式...");
    
    // 停止所有可能的定时器
    keyScanTicker.detach();
    taskWatchdogTicker.detach();
    dataStreamTicker.detach();
    delay(50);
    
    // 初始化按键扫描定时器
    keyScanTicker.attach_ms(KEY_SCAN_INTERVAL, []() {
        // 数据流模式下跳过所有按键处理
        if (data_stream_mode_active) {
            return;
        }

        // 正常模式下的按键处理
        btn_up.update();
        btn_sel.update();
        btn_down.update();

        // 优先处理WiFi编辑
        if (editing_wifi_ssid || editing_wifi_pass || editing_fixed_ip || editing_target_ip || wifi_editing_switch) {
            handle_wifi_editing();
            return;
        }

        // UP键处理
        if (btn_up.fell()) {
            Serial.println("UP pressed");
            buzzer_beep();
            
            if (in_spectral_mode) {
                current_page = (current_page == 1) ? TOTAL_PAGES : (current_page - 1);
                menu_updated = true;
            } else {
                if (in_submenu && current_menu == 0) {
                    if (as7341_submenu_type == 1) {
                        as7341_led_bright = min(20, as7341_led_bright + 1);
                        if (as7341_led_state && as7341_init_ok) {
                            as7341.controlLed(as7341_led_bright);
                        }
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (as7341_submenu_type == 2) {
                        if (!as7341_led_state && as7341_init_ok) {
                            as7341_led_state = true;
                            as7341.enableLed(true);
                            as7341.controlLed(as7341_led_bright);
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 1) {
                    if (uv_submenu_type == 1) {
                        uv_led_bright = min(20, uv_led_bright + 1);
                        if (uv_led_state) {
                            analogWrite(UV_LED_PIN, UV_BRIGHT_TO_PWM(uv_led_bright));
                        }
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (uv_submenu_type == 2) {
                        if (!uv_led_state) {
                            uv_led_state = true;
                            analogWrite(UV_LED_PIN, UV_BRIGHT_TO_PWM(uv_led_bright));
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 2) {
                    if (buzzer_submenu_type == 1) {
                        buzzer_volume = min(BUZZER_VOL_MAX, buzzer_volume + 1);
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (buzzer_submenu_type == 2) {
                        if (!buzzer_enable) {
                            buzzer_enable = true;
                            buzzer_beep();
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 3) {
                    wifi_submenu_type = (wifi_submenu_type == 1) ? 6 : wifi_submenu_type - 1;  // 从5改为6
                    menu_updated = true;
                } else if (!in_submenu) {
                    current_menu = (current_menu - 1 + MENU_COUNT) % MENU_COUNT;
                    handle_scroll_offset();
                    menu_updated = true;
                }
            }
        }

        // DOWN键处理
        if (btn_down.fell()) {
            Serial.println("DOWN pressed");
            buzzer_beep();
            
            if (in_spectral_mode) {
                current_page = (current_page % TOTAL_PAGES) + 1;
                menu_updated = true;
            } else {
                if (in_submenu && current_menu == 0) {
                    if (as7341_submenu_type == 1) {
                        as7341_led_bright = max(1, as7341_led_bright - 1);
                        if (as7341_led_state && as7341_init_ok) {
                            as7341.controlLed(as7341_led_bright);
                        }
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (as7341_submenu_type == 2) {
                        if (as7341_led_state && as7341_init_ok) {
                            as7341_led_state = false;
                            as7341.enableLed(false);
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 1) {
                    if (uv_submenu_type == 1) {
                        uv_led_bright = max(1, uv_led_bright - 1);
                        if (uv_led_state) {
                            analogWrite(UV_LED_PIN, UV_BRIGHT_TO_PWM(uv_led_bright));
                        }
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (uv_submenu_type == 2) {
                        if (uv_led_state) {
                            uv_led_state = false;
                            analogWrite(UV_LED_PIN, 0);
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 2) {
                    if (buzzer_submenu_type == 1) {
                        buzzer_volume = max(1, buzzer_volume - 1);
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (buzzer_submenu_type == 2) {
                        if (buzzer_enable) {
                            buzzer_enable = false;
                            if (buzzer_beeping) {
                                analogWrite(BUZZER_PIN, 0);
                                buzzer_beeping = false;
                                buzzerStopTicker.detach();
                            }
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 3) {
                    wifi_submenu_type = (wifi_submenu_type == 6) ? 1 : wifi_submenu_type + 1;  // 从5改为6
                    menu_updated = true;
                } else if (!in_submenu) {
                    current_menu = (current_menu + 1) % MENU_COUNT;
                    handle_scroll_offset();
                    menu_updated = true;
                }
            }
        }

        // SEL键处理
        if (btn_sel.fell()) {
            Serial.println("SEL pressed");
            buzzer_beep();
            
            sel_press_start = millis();
            sel_is_pressing = true;
            long_press_triggered = false;
            sel_was_pressed = true;
        }

        if (sel_is_pressing && !btn_sel.read()) {
            if (!long_press_triggered && (millis() - sel_press_start >= LONG_PRESS_THRESHOLD)) {
                long_press_triggered = true;
                
                if (!editing_wifi_ssid && !editing_wifi_pass && 
                    !editing_fixed_ip && !editing_target_ip && !wifi_editing_switch) {
                    if (in_submenu) {
                        if (current_menu == 0) as7341_submenu_type = 0;
                        if (current_menu == 1) uv_submenu_type = 0;
                        if (current_menu == 2) buzzer_submenu_type = 0;
                        if (current_menu == 3) {
                            wifi_submenu_type = 0;
                            wifi_editing_switch = false;
                        }
                        in_submenu = false;
                        menu_updated = true;
                    } else if (!in_spectral_mode) {
                        in_spectral_mode = true;
                        menu_updated = true;
                    }
                }
            }
        }

        if (btn_sel.rose() && sel_was_pressed) {
            sel_is_pressing = false;
            sel_was_pressed = false;
            
            if (!long_press_triggered) {
                if (!in_spectral_mode) {
                    if (current_menu == 0) {
                        if (!in_submenu) {
                            in_submenu = true;
                            as7341_submenu_type = 1;
                            menu_updated = true;
                        } else {
                            as7341_submenu_type = (as7341_submenu_type == 1) ? 2 : 1;
                            menu_updated = true;
                        }
                    } else if (current_menu == 1) {
                        if (!in_submenu) {
                            in_submenu = true;
                            uv_submenu_type = 1;
                            menu_updated = true;
                        } else {
                            uv_submenu_type = (uv_submenu_type == 1) ? 2 : 1;
                            menu_updated = true;
                        }
                    } else if (current_menu == 2) {
                        if (!in_submenu) {
                            in_submenu = true;
                            buzzer_submenu_type = 1;
                            menu_updated = true;
                        } else {
                            buzzer_submenu_type = (buzzer_submenu_type == 1) ? 2 : 1;
                            menu_updated = true;
                        }
                    } else if (current_menu == 3) {
                        if (!in_submenu) {
                            in_submenu = true;
                            wifi_submenu_type = 1;
                            menu_updated = true;
                        } else {
                            if (wifi_submenu_type >= 1 && wifi_submenu_type <= 5) {
                                enter_edit_mode(wifi_submenu_type);
                            } else if (wifi_submenu_type == 6) {  // 处理手动重连
                                // 手动重连，重置重连计数
                                reconnect_attempt_count = 0;
                                connect_to_wifi();
                                menu_updated = true;
                                Serial.println("手动重连WiFi...");
                            }
                        }
                    } else if (current_menu == 4) {
                        in_spectral_mode = true;
                        in_submenu = false;
                        as7341_submenu_type = 0;
                        uv_submenu_type = 0;
                        buzzer_submenu_type = 0;
                        wifi_submenu_type = 0;
                        wifi_editing_switch = false;
                        menu_updated = true;
                    } else if (current_menu < MENU_COUNT) {
                        in_submenu = !in_submenu;
                        menu_updated = true;
                    }
                } else {
                    in_spectral_mode = false;
                    in_submenu = false;
                    as7341_submenu_type = 0;
                    uv_submenu_type = 0;
                    buzzer_submenu_type = 0;
                    wifi_submenu_type = 0;
                    menu_updated = true;
                }
            }
        }
    });
    
    // 任务看门狗定时器
    taskWatchdogTicker.attach_ms(1000, task_watchdog);
    
    Serial.println("本地模式初始化完成");
}

// ========== 新增：数据流模式管理函数 ==========

// 修复2：完全重写进入数据流模式函数，不使用Ticker
void enter_data_stream_mode() {
    Serial.println("=== 进入数据流模式 ===");
    mode_transition_in_progress = true;
    
    // 停止所有本地模式定时器
    keyScanTicker.detach();
    taskWatchdogTicker.detach();
    wifiReconnectTicker.detach();
    delay(100); // 确保定时器完全停止
    
    // 重置数据流状态
    data_stream_packet_count = 0;
    stream_count_current = 0;  // 重置当前计数
    stream_paused = false;
    current_stream_mode = STREAM_MODE_CONTINUOUS; // 默认持续发送模式
    data_stream_start_time = millis();
    data_stream_mode_active = true;
    last_data_stream_time = 0;
    
    // 重置完成通知标志
    completionNotificationPending = false;
    
    // 连接目标服务器
    if (!connect_to_target_server()) {
        Serial.println("目标服务器连接失败，无法进入数据流模式");
        exit_data_stream_mode();
        return;
    }
    
    // 不再使用定时器，改为在主循环中控制发送频率
    Serial.println("数据流模式已启动 - 使用主循环控制发送频率");
    
    // 更新显示
    menu_updated = true;
    mode_transition_in_progress = false;
    
    buzzer_beep();
}

// 退出数据流模式
void exit_data_stream_mode() {
    Serial.println("=== 退出数据流模式 ===");
    mode_transition_in_progress = true;
    
    // 发送统计数据
    send_data_stream_stats();
    
    // 关闭目标服务器连接
    if (targetClient.connected()) {
        targetClient.stop();
        Serial.println("目标服务器连接已关闭");
    }
    target_server_connected = false;
    
    // 重置状态
    data_stream_mode_active = false;
    data_stream_enabled = false;
    
    // 重新初始化本地模式
    init_local_mode();
    
    // 重新启动WiFi重连定时器（如果需要）
    if (wifi_enable && !wifi_connected) {
        wifiReconnectTicker.attach_ms(WIFI_RECONNECT_DELAY, connect_to_wifi);
    }
    
    // 更新显示
    menu_updated = true;
    mode_transition_in_progress = false;
    
    buzzer_beep();
    Serial.println("已返回本地模式");
}

// 检查是否满足进入数据流模式的条件
bool can_enter_data_stream_mode() {
    if (!wifi_connected) {
        Serial.println("无法进入数据流模式：WiFi未连接");
        return false;
    }
    
    if (is_string_empty(target_ip) || !is_valid_ip_address(target_ip)) {
        Serial.println("无法进入数据流模式：目标IP未设置或无效");
        return false;
    }
    
    if (!as7341_init_ok) {
        Serial.println("无法进入数据流模式：传感器未初始化");
        return false;
    }
    
    return true;
}

// 连接目标服务器（用于数据流模式）
bool connect_to_target_server() {
    if (target_server_connected && targetClient.connected()) {
        return true;
    }
    
    if (millis() - last_target_connect_attempt < TARGET_CONNECT_RETRY_INTERVAL) {
        return false;
    }
    
    Serial.print("尝试连接目标服务器: ");
    Serial.print(target_ip);
    Serial.print(":");
    Serial.println(TARGET_PORT);
    
    last_target_connect_attempt = millis();
    
    if (targetClient.connect(target_ip, TARGET_PORT)) {
        target_server_connected = true;
        Serial.println("目标服务器连接成功");
        
        // 保持目标服务器连接成功时的设备信息发送
        send_device_status_update_non_blocking();
        return true;
    } else {
        target_server_connected = false;
        Serial.println("目标服务器连接失败");
        return false;
    }
}

// ========== 修改后的WiFi连接和通知函数 ==========

void send_connection_notification(bool connected) {
    Serial.println("\n===== 准备发送连接状态通知 =====");
    
    if (is_string_empty(target_ip) || !is_valid_ip_address(target_ip)) {
        Serial.println("错误：目标IP未设置或无效，无法发送通知");
        return;
    }
    
    if (!wifi_enable) {
        Serial.println("错误：发送条件不满足（WiFi功能未启用）");
        return;
    }
    
    wl_status_t actual_status = WiFi.status();
    if (actual_status != WL_CONNECTED) {
        Serial.print("错误：发送条件不满足（WiFi未实际连接，状态码：");
        Serial.print(actual_status);
        Serial.println("）");
        wifi_connected = false;
        return;
    }
    
    // 构建精简的连接通知
    DynamicJsonDocument doc(384);
    doc["type"] = "connection";
    doc["status"] = connected ? "connected" : "disconnected";
    doc["device"] = DEVICE_NAME;
    doc["timestamp"] = millis();
    
    if (connected) {
        doc["ip"] = WiFi.localIP().toString();
        doc["rssi"] = WiFi.RSSI();
    }
    
    // 精简设备状态信息
    JsonObject status = doc.createNestedObject("status");
    status["as7341_led"] = as7341_led_state;
    status["as7341_bright"] = as7341_led_bright;
    status["uv_led"] = uv_led_state;
    status["uv_bright"] = uv_led_bright;
    status["buzzer"] = buzzer_enable;
    status["sensor"] = as7341_init_ok;
    
    String json_output;
    serializeJson(doc, json_output);
    
    Serial.println("发送连接通知:");
    Serial.println(json_output);
    
    // 在数据流模式下使用已连接的TCP客户端
    if (data_stream_mode_active && target_server_connected && targetClient.connected()) {
        targetClient.println(json_output);
        targetClient.flush();
        Serial.println("连接通知已通过目标服务器TCP连接发送");
    } else {
        // 创建新连接发送通知
        WiFiClient tempClient;
        if (tempClient.connect(target_ip, TARGET_PORT)) {
            tempClient.println(json_output);
            tempClient.flush();
            tempClient.stop();
            Serial.println("连接通知已通过临时TCP连接发送");
        } else {
            Serial.println("错误：无法建立临时TCP连接发送连接通知");
        }
    }
    
    connection_notified = connected;
}

// 简化的WiFi连接函数
void connect_to_wifi() {
    // 检查是否已经在连接中
    if (wifi_connecting) {
        Serial.println("WiFi连接正在进行中，跳过重复连接");
        return;
    }
    
    // 检查WiFi是否已连接
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("WiFi已经连接，跳过连接请求");
        wifi_connected = true;
        wifi_connecting = false;
        return;
    }
    
    wifi_task_running = true;
    current_task_name = "WIFI_CONNECT";
    task_start_time = millis();
    last_task_activity = millis();
    
    Serial.print("开始连接WiFi: ");
    Serial.println(wifi_ssid);
    
    // 先确保断开现有连接
    if (WiFi.status() != WL_DISCONNECTED) {
        Serial.println("断开现有WiFi连接...");
        WiFi.disconnect(true);  // 使用true参数清除网络配置
        delay(1000);  // 增加断开等待时间
    }
    
    // 配置静态IP（如果设置了）
    if (!is_string_empty(fixed_ip)) {
        IPAddress local_IP, gateway, subnet(255, 255, 255, 0);
        IPAddress dns1(8, 8, 8, 8), dns2(8, 8, 4, 4);
        
        if (local_IP.fromString(fixed_ip)) {
            gateway = local_IP;
            gateway[3] = 1;
            
            if (!WiFi.config(local_IP, gateway, subnet, dns1, dns2)) {
                Serial.println("静态IP配置失败，将使用DHCP");
            } else {
                Serial.print("已配置静态IP: ");
                Serial.println(local_IP.toString());
            }
        }
    }
    
    // 开始连接
    WiFi.mode(WIFI_STA);
    WiFi.begin(wifi_ssid, wifi_pass);
    wifi_connecting = true;
    
    Serial.println("WiFi连接已启动（非阻塞模式）");
    menu_updated = true;
}

// ========== 修复后的WiFi状态检查函数 ==========

void check_wifi_connection_status() {
    if (!wifi_enable) return;
    
    unsigned long current_time = millis();
    wl_status_t status = WiFi.status();
    
    // 检查连接超时（20秒超时）
    if (wifi_connecting && (current_time - task_start_time > 20000)) {
        Serial.println("WiFi连接超时（20秒）");
        wifi_connecting = false;
        wifi_task_running = false;
        current_task_name = "";
        
        // 增加重连计数
        reconnect_attempt_count++;
        Serial.print("重连尝试次数: ");
        Serial.println(reconnect_attempt_count);
        
        // 检查是否超过最大重连次数
        if (reconnect_attempt_count >= MAX_RECONNECT_ATTEMPTS) {
            Serial.println("达到最大重连次数，停止自动重连");
            // 不自动禁用WiFi，让用户决定
        }
        
        // 设置下一次重连时间
        last_reconnect_attempt = current_time;
        menu_updated = true;
        return;
    }
    
    // 检查连接状态变化
    if (wifi_connecting) {
        if (status == WL_CONNECTED) {
            // 连接成功
            wifi_connected = true;
            wifi_connecting = false;
            wifi_task_running = false;
            current_task_name = "";
            reconnect_attempt_count = 0;  // 重置重连计数
            last_stable_connection = current_time;
            
            Serial.println("\nWiFi连接成功！");
            Serial.print("IP地址: ");
            Serial.println(WiFi.localIP().toString());
            Serial.print("信号强度: ");
            Serial.print(WiFi.RSSI());
            Serial.println(" dBm");
            
            buzzer_beep();
            
            // 连接成功后发送连接通知（仅在本地模式）
            if (!data_stream_mode_active) {
                Serial.println("发送连接成功通知...");
                send_connection_notification(true);
            }
            
            menu_updated = true;
            
        } else if (status == WL_CONNECT_FAILED || status == WL_NO_SSID_AVAIL) {
            // 连接失败
            wifi_connected = false;
            wifi_connecting = false;
            wifi_task_running = false;
            current_task_name = "";
            
            // 增加重连计数
            reconnect_attempt_count++;
            Serial.print("WiFi连接失败，重连尝试次数: ");
            Serial.println(reconnect_attempt_count);
            
            // 检查是否超过最大重连次数
            if (reconnect_attempt_count >= MAX_RECONNECT_ATTEMPTS) {
                Serial.println("达到最大重连次数，停止自动重连");
            }
            
            // 设置下一次重连时间
            last_reconnect_attempt = current_time;
            menu_updated = true;
        }
    }
    
    // 检查已连接状态的稳定性
    if (wifi_connected && status == WL_CONNECTED) {
        if (current_time - last_stable_connection > STABLE_CONNECTION_THRESHOLD) {
            // 连接稳定，更新稳定连接时间
            last_stable_connection = current_time;
        }
    } else if (wifi_connected && status != WL_CONNECTED) {
        // WiFi状态显示已连接，但实际已断开
        Serial.println("检测到WiFi连接已断开");
        wifi_connected = false;
        wifi_connecting = false;
        last_reconnect_attempt = current_time;
        menu_updated = true;
    }
}

void check_auto_reconnect() {
    if (!wifi_enable) return;
    
    unsigned long current_time = millis();
    
    // 如果已经连接，不需要重连
    if (wifi_connected || wifi_connecting) {
        return;
    }
    
    // 检查是否需要重连
    if (current_time - last_reconnect_attempt >= WIFI_RECONNECT_INTERVAL) {
        // 检查是否超过最大重连次数
        if (reconnect_attempt_count < MAX_RECONNECT_ATTEMPTS) {
            Serial.println("尝试自动重连WiFi...");
            connect_to_wifi();
            last_reconnect_attempt = current_time;
        } else {
            // 超过最大重连次数
            Serial.println("已超过最大重连次数，需要手动重新连接");
        }
    }
}

// 断开WiFi连接
void disconnect_wifi() {
    bool was_connected = wifi_connected;
    
    if (WiFi.status() == WL_CONNECTED || wifi_connecting) {
        if (was_connected && !data_stream_mode_active) {
            send_connection_notification(false);
        }
        
        WiFi.disconnect();
        wifi_connected = false;
        wifi_connecting = false;
        connection_notified = false;
        delay(100);
        Serial.println("WiFi已断开");
    }
}

// ========== 数据流发送函数 ==========

// ========== 进一步优化的UDP数据流发送函数 ==========

void send_data_stream_packet() {
    if (!data_stream_mode_active || !wifi_connected || stream_paused) {
        return;
    }
    
    // 检查指定次数模式是否已完成
    if (current_stream_mode == STREAM_MODE_FIXED_COUNT) {
        if (stream_count_current >= stream_count_target) {
            // 只在第一次检测到完成时发送通知
            if (!stream_paused) {
                stream_paused = true; // 自动暂停
                Serial.println("指定次数发送完成");
                
                // 发送完成通知（非阻塞）
                send_stream_completion_notification_non_blocking();
            }
            return;
        }
    }
    
    // 读取传感器数据
    if (!read_spectral_data()) {
        // 减少错误打印频率
        static unsigned long last_sensor_error = 0;
        if (millis() - last_sensor_error > 5000) {
            Serial.println("读取传感器数据失败");
            last_sensor_error = millis();
        }
        return;
    }
    
    unsigned long current_time = millis();
    
    // 构建极简的数据流JSON
    char json_buffer[96];
    snprintf(json_buffer, sizeof(json_buffer),
        "{\"t\":%lu,\"d\":[%d,%d,%d,%d,%d,%d,%d,%d],\"c\":%lu,\"sc\":%lu}",
        current_time,
        spectral_data[0], spectral_data[1], spectral_data[2], spectral_data[3],
        spectral_data[4], spectral_data[5], spectral_data[6], spectral_data[7],
        data_stream_packet_count,
        stream_count_current + 1  // 发送前计数+1，避免重复计数
    );
    
    // 通过UDP发送数据
    if (dataStreamUdp.beginPacket(target_ip, DATA_STREAM_PORT)) {
        dataStreamUdp.write((const uint8_t*)json_buffer, strlen(json_buffer));
        if (dataStreamUdp.endPacket()) {
            data_stream_packet_count++;
            stream_count_current++;
            
            // 检查是否达到目标次数
            if (current_stream_mode == STREAM_MODE_FIXED_COUNT) {
                if (stream_count_current >= stream_count_target) {
                    stream_paused = true; // 自动暂停
                    Serial.println("指定次数发送完成");
                    
                    // 发送完成通知（非阻塞）
                    send_stream_completion_notification_non_blocking();
                }
            }
            
            // 大幅减少打印频率，每500个包打印一次
            if (data_stream_packet_count % 500 == 0) {
                Serial.print("UDP包计数: ");
                Serial.print(data_stream_packet_count);
                if (current_stream_mode == STREAM_MODE_FIXED_COUNT) {
                    Serial.print(" (");
                    Serial.print(stream_count_current);
                    Serial.print("/");
                    Serial.print(stream_count_target);
                    Serial.print(")");
                }
                Serial.println();
            }
        } else {
            // 大幅减少错误打印频率
            static unsigned long last_udp_error = 0;
            if (current_time - last_udp_error > 10000) {
                Serial.println("UDP发送失败");
                last_udp_error = current_time;
            }
        }
    } else {
        // 大幅减少错误打印频率
        static unsigned long last_udp_error = 0;
        if (current_time - last_udp_error > 10000) {
            Serial.println("UDP开始包失败");
            last_udp_error = current_time;
        }
    }
    
    last_data_stream_time = current_time;
}

// ========== 新增：发送完成通知函数 ==========

void send_stream_completion_notification_non_blocking() {
    completionNotificationPending = true;
    Serial.println("完成通知已排队");
}

void process_completion_notification() {
    if (!completionNotificationPending) {
        return;
    }
    
    // 发送完成通知
    send_stream_completion_notification_direct();
    completionNotificationPending = false;
}

void send_stream_completion_notification_direct() {
    Serial.println("发送数据流完成通知...");
    
    if (is_string_empty(target_ip) || !is_valid_ip_address(target_ip)) {
        Serial.println("错误：目标IP未设置或无效，无法发送完成通知");
        return;
    }
    
    if (!wifi_enable || !wifi_connected) {
        Serial.println("错误：WiFi未连接，无法发送完成通知");
        return;
    }
    
    // 构建精简的完成通知
    DynamicJsonDocument doc(256);
    doc["type"] = "streamComplete";
    doc["device"] = DEVICE_NAME;
    doc["timestamp"] = millis();
    doc["total_packets"] = data_stream_packet_count;
    doc["stream_mode"] = (current_stream_mode == STREAM_MODE_CONTINUOUS) ? "continuous" : "fixed";
    
    if (current_stream_mode == STREAM_MODE_FIXED_COUNT) {
        doc["target_count"] = stream_count_target;
        doc["actual_count"] = stream_count_current;  // 使用正确的当前计数
        doc["status"] = "completed";
    } else {
        doc["status"] = "paused";
    }
    
    String json_output;
    serializeJson(doc, json_output);
    
    Serial.println("发送完成通知:");
    Serial.println(json_output);
    
    // 在数据流模式下使用已连接的TCP客户端
    if (data_stream_mode_active && target_server_connected && targetClient.connected()) {
        targetClient.println(json_output);
        targetClient.flush();
        Serial.println("完成通知已通过目标服务器TCP连接发送");
    } else {
        // 创建新的临时连接发送
        WiFiClient tempClient;
        if (tempClient.connect(target_ip, TARGET_PORT)) {
            tempClient.println(json_output);
            tempClient.flush();
            tempClient.stop();
            Serial.println("完成通知已通过临时TCP连接发送");
        } else {
            Serial.println("错误：无法建立临时TCP连接发送完成通知");
        }
    }
}

void send_stream_completion_notification() {
    Serial.println("发送数据流完成通知...");
    
    if (is_string_empty(target_ip) || !is_valid_ip_address(target_ip)) {
        Serial.println("错误：目标IP未设置或无效，无法发送完成通知");
        return;
    }
    
    if (!wifi_enable || !wifi_connected) {
        Serial.println("错误：WiFi未连接，无法发送完成通知");
        return;
    }
    
    // 构建精简的完成通知
    DynamicJsonDocument doc(256);
    doc["type"] = "streamComplete";
    doc["device"] = DEVICE_NAME;
    doc["timestamp"] = millis();
    doc["total_packets"] = data_stream_packet_count;
    doc["stream_mode"] = (current_stream_mode == STREAM_MODE_CONTINUOUS) ? "continuous" : "fixed";
    
    if (current_stream_mode == STREAM_MODE_FIXED_COUNT) {
        doc["target_count"] = stream_count_target;
        doc["actual_count"] = stream_count_current;
    }
    
    String json_output;
    serializeJson(doc, json_output);
    
    Serial.println("发送完成通知:");
    Serial.println(json_output);
    
    // 在数据流模式下使用已连接的TCP客户端
    if (data_stream_mode_active && target_server_connected && targetClient.connected()) {
        targetClient.println(json_output);
        targetClient.flush();
        Serial.println("完成通知已通过目标服务器TCP连接发送");
    } else {
        // 创建新的临时连接发送
        WiFiClient tempClient;
        if (tempClient.connect(target_ip, TARGET_PORT)) {
            tempClient.println(json_output);
            tempClient.flush();
            tempClient.stop();
            Serial.println("完成通知已通过临时TCP连接发送");
        } else {
            Serial.println("错误：无法建立临时TCP连接发送完成通知");
        }
    }
}

void send_data_stream_timer() {
  if (!data_stream_mode_active || !wifi_connected) {
    return;
  }
  
  // 确保目标服务器连接
  if (!target_server_connected) {
    if (!connect_to_target_server()) {
      return; // 连接失败，跳过本次发送
    }
  }
  
  // 检查目标服务器连接状态
  if (!targetClient.connected()) {
    target_server_connected = false;
    Serial.println("目标服务器连接断开");
    return;
  }
  
  // 读取传感器数据
  if (!read_spectral_data()) {
    Serial.println("读取传感器数据失败");
    return;
  }
  
  unsigned long current_time = millis();
  
  // 构建数据流JSON - 简化版本提高性能
  char json_buffer[200];
  snprintf(json_buffer, sizeof(json_buffer),
    "{\"t\":%lu,\"d\":[%d,%d,%d,%d,%d,%d,%d,%d],\"c\":%lu}",
    current_time,
    spectral_data[0], spectral_data[1], spectral_data[2], spectral_data[3],
    spectral_data[4], spectral_data[5], spectral_data[6], spectral_data[7],
    data_stream_packet_count
  );
  
  // 通过UDP发送数据
  if (dataStreamUdp.beginPacket(target_ip, DATA_STREAM_PORT)) {
    dataStreamUdp.write((const uint8_t*)json_buffer, strlen(json_buffer));
    if (dataStreamUdp.endPacket()) {
      data_stream_packet_count++;
      
      // 每100个包打印一次统计信息
      if (data_stream_packet_count % 100 == 0) {
        Serial.print("数据流包计数: ");
        Serial.println(data_stream_packet_count);
      }
    } else {
      Serial.println("UDP发送失败");
    }
  } else {
    Serial.println("UDP开始包失败");
  }
  
  last_data_stream_time = current_time;
  
  // 定期更新显示
  static unsigned long last_display_update = 0;
  if (current_time - last_display_update > 1000) {
    menu_updated = true;
    last_display_update = current_time;
  }
}

// ========== 修改JSON指令处理函数，使用非阻塞响应 ==========

void process_json_command(const char* json_str) {
    Serial.print("收到JSON指令: ");
    Serial.println(json_str);
    
    DeserializationError error = deserializeJson(json_doc, json_str);
    if (error) {
        Serial.print("JSON解析失败: ");
        Serial.println(error.c_str());
        send_command_response_non_blocking("ERROR: JSON parse failed");
        return;
    }
    
    // 处理数据流控制指令
    if (json_doc.containsKey("dataStream")) {
        bool new_state = json_doc["dataStream"];
        
        if (new_state && !data_stream_mode_active) {
            // 请求进入数据流模式
            if (can_enter_data_stream_mode()) {
                enter_data_stream_mode();
                send_command_response_non_blocking("OK");
            } else {
                send_command_response_non_blocking("ERROR: Cannot enter data stream mode");
            }
        } else if (!new_state && data_stream_mode_active) {
            // 请求退出数据流模式
            exit_data_stream_mode();
            send_command_response_non_blocking("OK");
        } else {
            send_command_response_non_blocking("OK");
        }
        return;
    }
    
    // 处理数据流发送模式设置
    if (json_doc.containsKey("streamMode")) {
        const char* mode = json_doc["streamMode"];
        if (strcmp(mode, "continuous") == 0) {
            current_stream_mode = STREAM_MODE_CONTINUOUS;
            stream_paused = false;
            Serial.println("数据流模式: 持续发送");
            send_command_response_non_blocking("OK");
        } else if (strcmp(mode, "fixed") == 0) {
            current_stream_mode = STREAM_MODE_FIXED_COUNT;
            stream_paused = false;
            // 检查是否同时指定了次数
            if (json_doc.containsKey("streamCount")) {
                stream_count_target = json_doc["streamCount"];
                stream_count_current = 0;
                if (stream_count_target > 0) {
                    Serial.print("数据流模式: 指定次数发送, 目标次数: ");
                    Serial.println(stream_count_target);
                    send_command_response_non_blocking("OK");
                } else {
                    send_command_response_non_blocking("ERROR: Invalid stream count");
                }
            } else {
                send_command_response_non_blocking("ERROR: Missing stream count for fixed mode");
            }
        } else {
            send_command_response_non_blocking("ERROR: Invalid stream mode");
        }
        return;
    }
    
    // 处理数据流次数设置（单独设置）
    if (json_doc.containsKey("streamCount")) {
        uint32_t count = json_doc["streamCount"];
        if (count > 0) {
            stream_count_target = count;
            stream_count_current = 0;  // 重置当前计数
            current_stream_mode = STREAM_MODE_FIXED_COUNT;
            stream_paused = false;
            Serial.print("设置发送次数: ");
            Serial.println(stream_count_target);
            send_command_response_non_blocking("OK");
        } else {
            send_command_response_non_blocking("ERROR: Invalid stream count");
        }
        return;
    }

    // 在streamMode处理中
    if (json_doc.containsKey("streamMode")) {
        const char* mode = json_doc["streamMode"];
        if (strcmp(mode, "continuous") == 0) {
            current_stream_mode = STREAM_MODE_CONTINUOUS;
            stream_paused = false;
            Serial.println("数据流模式: 持续发送");
            send_command_response_non_blocking("OK");
        } else if (strcmp(mode, "fixed") == 0) {
            current_stream_mode = STREAM_MODE_FIXED_COUNT;
            stream_paused = false;
            stream_count_current = 0;  // 重置当前计数
            // 检查是否同时指定了次数
            if (json_doc.containsKey("streamCount")) {
                stream_count_target = json_doc["streamCount"];
                if (stream_count_target > 0) {
                    Serial.print("数据流模式: 指定次数发送, 目标次数: ");
                    Serial.println(stream_count_target);
                    send_command_response_non_blocking("OK");
                } else {
                    send_command_response_non_blocking("ERROR: Invalid stream count");
                }
            } else {
                // 如果没有指定次数，保持当前目标次数，但重置当前计数
                send_command_response_non_blocking("OK");
            }
        } else {
            send_command_response_non_blocking("ERROR: Invalid stream mode");
        }
        return;
    }
    
    // 在数据流模式下，现在允许处理设备控制指令
    if (data_stream_mode_active) {
        // 数据流模式下只处理特定指令，不退出数据流模式
        bool instruction_processed = false;
        
        // AS7341 LED控制
        if (json_doc.containsKey("as7341Led")) {
            bool led_state = json_doc["as7341Led"];
            if (as7341_init_ok && led_state != as7341_led_state) {
                as7341_led_state = led_state;
                as7341.enableLed(as7341_led_state);
                if (as7341_led_state) {
                    as7341.controlLed(as7341_led_bright);
                }
                save_to_eeprom();
                Serial.print("AS7341 LED: ");
                Serial.println(as7341_led_state ? "ON" : "OFF");
                instruction_processed = true;
                
                // 发送状态更新（非阻塞）
                send_device_status_update_non_blocking();
            }
        }
        
        // AS7341亮度设置
        if (json_doc.containsKey("as7341Brightness")) {
            uint8_t brightness = json_doc["as7341Brightness"];
            if (brightness >= 1 && brightness <= 20 && brightness != as7341_led_bright) {
                as7341_led_bright = brightness;
                if (as7341_led_state && as7341_init_ok) {
                    as7341.controlLed(as7341_led_bright);
                }
                save_to_eeprom();
                Serial.print("AS7341亮度设置为: ");
                Serial.println(as7341_led_bright);
                instruction_processed = true;
                
                // 发送状态更新（非阻塞）
                send_device_status_update_non_blocking();
            }
        }
        
        // UV LED控制
        if (json_doc.containsKey("uvLed")) {
            bool uv_state = json_doc["uvLed"];
            if (uv_state != uv_led_state) {
                uv_led_state = uv_state;
                if (uv_led_state) {
                    analogWrite(UV_LED_PIN, UV_BRIGHT_TO_PWM(uv_led_bright));
                } else {
                    analogWrite(UV_LED_PIN, 0);
                }
                save_to_eeprom();
                Serial.print("UV LED: ");
                Serial.println(uv_led_state ? "ON" : "OFF");
                instruction_processed = true;
                
                // 发送状态更新（非阻塞）
                send_device_status_update_non_blocking();
            }
        }
        
        // UV亮度设置
        if (json_doc.containsKey("uvBrightness")) {
            uint8_t brightness = json_doc["uvBrightness"];
            if (brightness >= 1 && brightness <= 20 && brightness != uv_led_bright) {
                uv_led_bright = brightness;
                if (uv_led_state) {
                    analogWrite(UV_LED_PIN, UV_BRIGHT_TO_PWM(uv_led_bright));
                }
                save_to_eeprom();
                Serial.print("UV亮度设置为: ");
                Serial.println(uv_led_bright);
                instruction_processed = true;
                
                // 发送状态更新（非阻塞）
                send_device_status_update_non_blocking();
            }
        }
        
        // 蜂鸣器控制
        if (json_doc.containsKey("buzzer")) {
            bool buzzer_state = json_doc["buzzer"];
            if (buzzer_state != buzzer_enable) {
                buzzer_enable = buzzer_state;
                if (!buzzer_enable && buzzer_beeping) {
                    analogWrite(BUZZER_PIN, 0);
                    buzzer_beeping = false;
                    buzzerStopTicker.detach();
                }
                save_to_eeprom();
                Serial.print("蜂鸣器: ");
                Serial.println(buzzer_enable ? "ON" : "OFF");
                instruction_processed = true;
                
                // 发送状态更新（非阻塞）
                send_device_status_update_non_blocking();
            }
        }
        
        // 获取设备状态指令
        if (json_doc.containsKey("getDeviceStatus") && json_doc["getDeviceStatus"]) {
            send_device_status_update_non_blocking();
            instruction_processed = true;
        }
        
        if (instruction_processed) {
            send_command_response_non_blocking("OK");
            return;
        }
        
        // 如果没有处理任何指令，返回OK
        send_command_response_non_blocking("OK");
        return;
    }
    
    // 本地模式下的设备控制指令处理（使用非阻塞响应）
    // AS7341 LED控制
    if (json_doc.containsKey("as7341Led")) {
        bool led_state = json_doc["as7341Led"];
        if (as7341_init_ok && led_state != as7341_led_state) {
            as7341_led_state = led_state;
            as7341.enableLed(as7341_led_state);
            if (as7341_led_state) {
                as7341.controlLed(as7341_led_bright);
            }
            save_to_eeprom();
            Serial.print("AS7341 LED: ");
            Serial.println(as7341_led_state ? "ON" : "OFF");
            menu_updated = true;
            send_command_response_non_blocking("OK");
        } else {
            send_command_response_non_blocking("OK");
        }
        return;
    }
    
    // AS7341亮度设置
    if (json_doc.containsKey("as7341Brightness")) {
        uint8_t brightness = json_doc["as7341Brightness"];
        if (brightness >= 1 && brightness <= 20 && brightness != as7341_led_bright) {
            as7341_led_bright = brightness;
            if (as7341_led_state && as7341_init_ok) {
                as7341.controlLed(as7341_led_bright);
            }
            save_to_eeprom();
            Serial.print("AS7341亮度设置为: ");
            Serial.println(as7341_led_bright);
            menu_updated = true;
            send_command_response_non_blocking("OK");
        } else {
            send_command_response_non_blocking("OK");
        }
        return;
    }
    
    // UV LED控制
    if (json_doc.containsKey("uvLed")) {
        bool uv_state = json_doc["uvLed"];
        if (uv_state != uv_led_state) {
            uv_led_state = uv_state;
            if (uv_led_state) {
                analogWrite(UV_LED_PIN, UV_BRIGHT_TO_PWM(uv_led_bright));
            } else {
                analogWrite(UV_LED_PIN, 0);
            }
            save_to_eeprom();
            Serial.print("UV LED: ");
            Serial.println(uv_led_state ? "ON" : "OFF");
            menu_updated = true;
            send_command_response_non_blocking("OK");
        } else {
            send_command_response_non_blocking("OK");
        }
        return;
    }
    
    // UV亮度设置
    if (json_doc.containsKey("uvBrightness")) {
        uint8_t brightness = json_doc["uvBrightness"];
        if (brightness >= 1 && brightness <= 20 && brightness != uv_led_bright) {
            uv_led_bright = brightness;
            if (uv_led_state) {
                analogWrite(UV_LED_PIN, UV_BRIGHT_TO_PWM(uv_led_bright));
            }
            save_to_eeprom();
            Serial.print("UV亮度设置为: ");
            Serial.println(uv_led_bright);
            menu_updated = true;
            send_command_response_non_blocking("OK");
        } else {
            send_command_response_non_blocking("OK");
        }
        return;
    }
    
    // 蜂鸣器控制
    if (json_doc.containsKey("buzzer")) {
        bool buzzer_state = json_doc["buzzer"];
        if (buzzer_state != buzzer_enable) {
            buzzer_enable = buzzer_state;
            if (!buzzer_enable && buzzer_beeping) {
                analogWrite(BUZZER_PIN, 0);
                buzzer_beeping = false;
                buzzerStopTicker.detach();
            }
            save_to_eeprom();
            Serial.print("蜂鸣器: ");
            Serial.println(buzzer_enable ? "ON" : "OFF");
            menu_updated = true;
            send_command_response_non_blocking("OK");
        } else {
            send_command_response_non_blocking("OK");
        }
        return;
    }
    
    // 设备重启指令
    if (json_doc.containsKey("reboot")) {
        if (json_doc["reboot"]) {
            Serial.println("收到重启指令，3秒后重启...");
            send_command_response_non_blocking("OK");
            
            dataStreamTicker.detach();
            keyScanTicker.detach();
            wifiReconnectTicker.detach();
            taskWatchdogTicker.detach();
            
            buzzer_beep();
            delay(100);
            buzzer_beep();
            delay(3000);
            ESP.restart();
        }
        return;
    }
    
    // 获取设备状态指令（本地模式）
    if (json_doc.containsKey("getDeviceStatus") && json_doc["getDeviceStatus"]) {
        send_device_status_update_non_blocking();
        send_command_response_non_blocking("OK");
        return;
    }
    
    // 默认响应
    send_command_response_non_blocking("OK");
}

// 直接发送设备状态更新（原有的send_device_status_update函数）
void send_device_status_update_direct() {
    Serial.println("发送设备状态更新...");
    
    if (is_string_empty(target_ip) || !is_valid_ip_address(target_ip)) {
        Serial.println("错误：目标IP未设置或无效，无法发送状态更新");
        return;
    }
    
    if (!wifi_enable || !wifi_connected) {
        Serial.println("错误：WiFi未连接，无法发送状态更新");
        return;
    }
    
    // 构建精简的设备状态信息
    DynamicJsonDocument doc(384);
    
    // 根据连接类型设置不同的消息类型
    if (data_stream_mode_active && target_server_connected && targetClient.connected()) {
        // 数据流模式下的TCP连接
        doc["type"] = "deviceStatus";
    } else if (commandClientConnected && currentCommandClient.connected()) {
        // 指令服务器的连接
        doc["type"] = "deviceStatus";
    } else {
        // 其他情况使用通用类型
        doc["type"] = "status";
    }
    
    doc["device"] = DEVICE_NAME;
    doc["timestamp"] = millis();
    
    // 精简设备状态信息
    JsonObject status = doc.createNestedObject("status");
    status["as7341_led"] = as7341_led_state;
    status["as7341_bright"] = as7341_led_bright;
    status["uv_led"] = uv_led_state;
    status["uv_bright"] = uv_led_bright;
    status["buzzer"] = buzzer_enable;
    status["sensor"] = as7341_init_ok;
    
    // 数据流模式状态（仅在数据流模式下包含）
    if (data_stream_mode_active) {
        status["stream_mode"] = (current_stream_mode == STREAM_MODE_CONTINUOUS) ? "continuous" : "fixed";
        status["stream_paused"] = stream_paused;
        status["packet_count"] = data_stream_packet_count;
        status["interval"] = data_stream_interval;
        
        if (current_stream_mode == STREAM_MODE_FIXED_COUNT) {
            status["current_count"] = stream_count_current;
            status["target_count"] = stream_count_target;
            status["remaining"] = stream_count_target - stream_count_current; // 添加剩余计数
        }
    }
    
    String json_output;
    serializeJson(doc, json_output);
    
    Serial.println("发送精简设备状态:");
    Serial.println(json_output);
    
    // 根据连接类型选择发送方式
    if (data_stream_mode_active && target_server_connected && targetClient.connected()) {
        // 数据流模式下使用目标服务器TCP连接
        targetClient.println(json_output);
        targetClient.flush();
        Serial.println("设备状态已通过目标服务器TCP连接发送");
    } else if (commandClientConnected && currentCommandClient.connected()) {
        // 指令服务器连接
        currentCommandClient.println(json_output);
        currentCommandClient.flush();
        Serial.println("设备状态已通过指令服务器TCP连接发送");
    } else {
        // 创建新的临时连接发送
        WiFiClient tempClient;
        if (tempClient.connect(target_ip, TARGET_PORT)) {
            tempClient.println(json_output);
            tempClient.flush();
            tempClient.stop();
            Serial.println("设备状态已通过临时TCP连接发送");
        } else {
            Serial.println("错误：无法建立临时TCP连接发送设备状态");
        }
    }
}

void process_status_update_queue() {
    if (!statusUpdatePending) {
        return;
    }
    
    // 检查冷却时间
    if (millis() - lastStatusUpdateTime < STATUS_UPDATE_COOLDOWN) {
        return;
    }
    
    // 发送状态更新
    send_device_status_update_direct();
    statusUpdatePending = false;
}

void send_device_status_update_non_blocking() {
    // 设置状态更新标志，而不是立即发送
    statusUpdatePending = true;
    lastStatusUpdateTime = millis();
    Serial.println("设备状态更新已排队");
}

// 非阻塞的响应发送函数
void send_command_response_non_blocking(const char* message) {
    // 将响应加入队列，而不是立即发送
    if (!responseQueueFull) {
        String response = "{\"response\":\"";
        response += message;
        response += "\"}";
        
        responseQueue[responseQueueTail] = response;
        responseQueueTail = (responseQueueTail + 1) % RESPONSE_QUEUE_SIZE;
        
        if (responseQueueTail == responseQueueHead) {
            responseQueueFull = true;
        }
        
        Serial.print("响应已加入队列: ");
        Serial.println(response);
    } else {
        Serial.println("响应队列已满，丢弃响应");
    }
}

// 处理响应队列的函数
void process_response_queue() {
    if (responseQueueHead == responseQueueTail && !responseQueueFull) {
        return; // 队列为空
    }
    
    // 检查是否有可用的客户端连接
    bool hasConnection = false;
    
    if (data_stream_mode_active && target_server_connected && targetClient.connected()) {
        // 在数据流模式下使用目标服务器连接
        String response = responseQueue[responseQueueHead];
        targetClient.println(response);
        targetClient.flush();
        hasConnection = true;
        Serial.print("通过目标服务器发送响应: ");
        Serial.println(response);
    } else if (commandClientConnected && currentCommandClient.connected()) {
        // 使用指令服务器连接
        String response = responseQueue[responseQueueHead];
        currentCommandClient.println(response);
        currentCommandClient.flush();
        hasConnection = true;
        Serial.print("通过指令服务器发送响应: ");
        Serial.println(response);
    }
    
    if (hasConnection) {
        // 成功发送，从队列中移除
        responseQueueHead = (responseQueueHead + 1) % RESPONSE_QUEUE_SIZE;
        responseQueueFull = false;
    }
    
    // 同时处理完成通知
    process_completion_notification();
}

// ========== 优化后的设备状态更新函数 ==========

// void send_device_status_update() {
//     Serial.println("发送设备状态更新...");
    
//     if (is_string_empty(target_ip) || !is_valid_ip_address(target_ip)) {
//         Serial.println("错误：目标IP未设置或无效，无法发送状态更新");
//         return;
//     }
    
//     if (!wifi_enable || !wifi_connected) {
//         Serial.println("错误：WiFi未连接，无法发送状态更新");
//         return;
//     }
    
//     // 构建精简的设备状态信息
//     DynamicJsonDocument doc(384); // 减小缓冲区大小
    
//     // 根据连接类型设置不同的消息类型
//     if (data_stream_mode_active && target_server_connected && targetClient.connected()) {
//         // 数据流模式下的TCP连接
//         doc["type"] = "deviceStatus";
//     } else if (commandClientConnected && currentCommandClient.connected()) {
//         // 指令服务器的连接
//         doc["type"] = "deviceStatus";
//     } else {
//         // 其他情况使用通用类型
//         doc["type"] = "status";
//     }
    
//     doc["device"] = DEVICE_NAME;
//     doc["timestamp"] = millis();
    
//     // 精简设备状态信息
//     JsonObject status = doc.createNestedObject("status");
//     status["as7341_led"] = as7341_led_state;
//     status["as7341_bright"] = as7341_led_bright;
//     status["uv_led"] = uv_led_state;
//     status["uv_bright"] = uv_led_bright;
//     status["buzzer"] = buzzer_enable;
//     status["sensor"] = as7341_init_ok;
    
//     // 数据流模式状态（仅在数据流模式下包含）
//     if (data_stream_mode_active) {
//         status["stream_mode"] = (current_stream_mode == STREAM_MODE_CONTINUOUS) ? "continuous" : "fixed";
//         status["stream_paused"] = stream_paused;
//         status["packet_count"] = data_stream_packet_count;
//         status["interval"] = data_stream_interval;
        
//         if (current_stream_mode == STREAM_MODE_FIXED_COUNT) {
//             status["current_count"] = stream_count_current;
//             status["target_count"] = stream_count_target;
//         }
//     }
    
//     String json_output;
//     serializeJson(doc, json_output);
    
//     Serial.println("发送精简设备状态:");
//     Serial.println(json_output);
    
//     // 根据连接类型选择发送方式
//     if (data_stream_mode_active && target_server_connected && targetClient.connected()) {
//         // 数据流模式下使用目标服务器TCP连接
//         targetClient.println(json_output);
//         targetClient.flush();
//         Serial.println("设备状态已通过目标服务器TCP连接发送");
//     } else if (commandClientConnected && currentCommandClient.connected()) {
//         // 指令服务器连接
//         currentCommandClient.println(json_output);
//         currentCommandClient.flush();
//         Serial.println("设备状态已通过指令服务器TCP连接发送");
//     } else {
//         // 创建新的临时连接发送
//         WiFiClient tempClient;
//         if (tempClient.connect(target_ip, TARGET_PORT)) {
//             tempClient.println(json_output);
//             tempClient.flush();
//             tempClient.stop();
//             Serial.println("设备状态已通过临时TCP连接发送");
//         } else {
//             Serial.println("错误：无法建立临时TCP连接发送设备状态");
//         }
//     }
// }

void send_device_status_update() {
    send_device_status_update_non_blocking();
}

// ========== 数据流模式下的指令服务器处理 ==========

void handle_command_server_data_stream_mode() {
    if (!wifi_connected) return;
    
    // 检查是否有新连接
    if (!commandClientConnected) {
        currentCommandClient = commandServer.available();
        if (currentCommandClient) {
            commandClientConnected = true;
            lastCommandActivity = millis();
            Serial.println("数据流模式：新的指令连接");
            // 移除了连接时的设备信息发送
        }
    }
    
    // 处理当前连接
    if (commandClientConnected && currentCommandClient.connected()) {
        // 检查超时
        if (millis() - lastCommandActivity > COMMAND_TIMEOUT) {
            Serial.println("指令连接超时，断开连接");
            currentCommandClient.stop();
            commandClientConnected = false;
            return;
        }
        
        // 非阻塞读取数据
        while (currentCommandClient.available()) {
            String json_line = currentCommandClient.readStringUntil('\n');
            json_line.trim();
            
            if (json_line.length() > 0) {
                lastCommandActivity = millis();
                process_json_command(json_line.c_str());
            }
            break; // 每次只处理一条指令
        }
    } else if (commandClientConnected) {
        Serial.println("指令连接关闭");
        currentCommandClient.stop();
        commandClientConnected = false;
        // 移除了断开时的设备信息发送
    }
}

// ========== 本地模式下的指令服务器处理 ==========

void handle_command_server_local_mode() {
    if (!wifi_connected) return;
    
    if (!commandClientConnected) {
        currentCommandClient = commandServer.available();
        if (currentCommandClient) {
            commandClientConnected = true;
            lastCommandActivity = millis();
            Serial.println("本地模式：新的指令连接");
            // 移除了连接时的设备信息发送
        }
    }
    
    if (commandClientConnected && currentCommandClient.connected()) {
        if (millis() - lastCommandActivity > COMMAND_TIMEOUT) {
            Serial.println("指令连接超时，断开连接");
            currentCommandClient.stop();
            commandClientConnected = false;
            return;
        }
        
        while (currentCommandClient.available()) {
            String json_line = currentCommandClient.readStringUntil('\n');
            json_line.trim();
            
            if (json_line.length() > 0) {
                lastCommandActivity = millis();
                process_json_command(json_line.c_str());
            }
            break;
        }
    } else if (commandClientConnected) {
        Serial.println("指令连接关闭");
        currentCommandClient.stop();
        commandClientConnected = false;
        // 移除了断开时的设备信息发送
    }
}

// ========== 初始化本地模式定时器 ==========

void init_local_mode_tickers() {
    // 按键扫描定时器
    keyScanTicker.attach_ms(KEY_SCAN_INTERVAL, []() {
        btn_up.update();
        btn_sel.update();
        btn_down.update();

        // 优先处理WiFi编辑
        if (editing_wifi_ssid || editing_wifi_pass || editing_fixed_ip || editing_target_ip || wifi_editing_switch) {
            handle_wifi_editing();
            return;
        }

        // UP键处理
        if (btn_up.fell()) {
            Serial.println("UP pressed");
            buzzer_beep();
            
            if (in_spectral_mode) {
                current_page = (current_page == 1) ? TOTAL_PAGES : (current_page - 1);
                menu_updated = true;
            } else {
                if (in_submenu && current_menu == 0) {
                    if (as7341_submenu_type == 1) {
                        as7341_led_bright = min(20, as7341_led_bright + 1);
                        if (as7341_led_state && as7341_init_ok) {
                            as7341.controlLed(as7341_led_bright);
                        }
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (as7341_submenu_type == 2) {
                        if (!as7341_led_state && as7341_init_ok) {
                            as7341_led_state = true;
                            as7341.enableLed(true);
                            as7341.controlLed(as7341_led_bright);
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 1) {
                    if (uv_submenu_type == 1) {
                        uv_led_bright = min(20, uv_led_bright + 1);
                        if (uv_led_state) {
                            analogWrite(UV_LED_PIN, UV_BRIGHT_TO_PWM(uv_led_bright));
                        }
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (uv_submenu_type == 2) {
                        if (!uv_led_state) {
                            uv_led_state = true;
                            analogWrite(UV_LED_PIN, UV_BRIGHT_TO_PWM(uv_led_bright));
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 2) {
                    if (buzzer_submenu_type == 1) {
                        buzzer_volume = min(BUZZER_VOL_MAX, buzzer_volume + 1);
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (buzzer_submenu_type == 2) {
                        if (!buzzer_enable) {
                            buzzer_enable = true;
                            buzzer_beep();
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 3) {
                    wifi_submenu_type = (wifi_submenu_type == 6) ? 1 : wifi_submenu_type + 1;  // 从5改为6
                    menu_updated = true;
                } else if (!in_submenu) {
                    current_menu = (current_menu - 1 + MENU_COUNT) % MENU_COUNT;
                    handle_scroll_offset();
                    menu_updated = true;
                }
            }
        }

        // DOWN键处理
        if (btn_down.fell()) {
            Serial.println("DOWN pressed");
            buzzer_beep();
            
            if (in_spectral_mode) {
                current_page = (current_page % TOTAL_PAGES) + 1;
                menu_updated = true;
            } else {
                if (in_submenu && current_menu == 0) {
                    if (as7341_submenu_type == 1) {
                        as7341_led_bright = max(1, as7341_led_bright - 1);
                        if (as7341_led_state && as7341_init_ok) {
                            as7341.controlLed(as7341_led_bright);
                        }
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (as7341_submenu_type == 2) {
                        if (as7341_led_state && as7341_init_ok) {
                            as7341_led_state = false;
                            as7341.enableLed(false);
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 1) {
                    if (uv_submenu_type == 1) {
                        uv_led_bright = max(1, uv_led_bright - 1);
                        if (uv_led_state) {
                            analogWrite(UV_LED_PIN, UV_BRIGHT_TO_PWM(uv_led_bright));
                        }
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (uv_submenu_type == 2) {
                        if (uv_led_state) {
                            uv_led_state = false;
                            analogWrite(UV_LED_PIN, 0);
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 2) {
                    if (buzzer_submenu_type == 1) {
                        buzzer_volume = max(1, buzzer_volume - 1);
                        save_to_eeprom();
                        menu_updated = true;
                    } else if (buzzer_submenu_type == 2) {
                        if (buzzer_enable) {
                            buzzer_enable = false;
                            if (buzzer_beeping) {
                                analogWrite(BUZZER_PIN, 0);
                                buzzer_beeping = false;
                                buzzerStopTicker.detach();
                            }
                            save_to_eeprom();
                            menu_updated = true;
                        }
                    }
                } else if (in_submenu && current_menu == 3) {
                    wifi_submenu_type = (wifi_submenu_type == 6) ? 1 : wifi_submenu_type + 1;  // 从5改为6
                    menu_updated = true;
                } else if (!in_submenu) {
                    current_menu = (current_menu + 1) % MENU_COUNT;
                    handle_scroll_offset();
                    menu_updated = true;
                }
            }
        }

        // SEL键处理
        if (btn_sel.fell()) {
            Serial.println("SEL pressed");
            buzzer_beep();
            
            sel_press_start = millis();
            sel_is_pressing = true;
            long_press_triggered = false;
            sel_was_pressed = true;
        }

        if (sel_is_pressing && !btn_sel.read()) {
            if (!long_press_triggered && (millis() - sel_press_start >= LONG_PRESS_THRESHOLD)) {
                long_press_triggered = true;
                
                if (!editing_wifi_ssid && !editing_wifi_pass && 
                    !editing_fixed_ip && !editing_target_ip && !wifi_editing_switch) {
                    if (in_submenu) {
                        if (current_menu == 0) as7341_submenu_type = 0;
                        if (current_menu == 1) uv_submenu_type = 0;
                        if (current_menu == 2) buzzer_submenu_type = 0;
                        if (current_menu == 3) {
                            wifi_submenu_type = 0;
                            wifi_editing_switch = false;
                        }
                        in_submenu = false;
                        menu_updated = true;
                    } else if (!in_spectral_mode) {
                        in_spectral_mode = true;
                        menu_updated = true;
                    }
                }
            }
        }

        if (btn_sel.rose() && sel_was_pressed) {
            sel_is_pressing = false;
            sel_was_pressed = false;
            
            if (!long_press_triggered) {
                if (!in_spectral_mode) {
                    if (current_menu == 0) {
                        if (!in_submenu) {
                            in_submenu = true;
                            as7341_submenu_type = 1;
                            menu_updated = true;
                        } else {
                            as7341_submenu_type = (as7341_submenu_type == 1) ? 2 : 1;
                            menu_updated = true;
                        }
                    } else if (current_menu == 1) {
                        if (!in_submenu) {
                            in_submenu = true;
                            uv_submenu_type = 1;
                            menu_updated = true;
                        } else {
                            uv_submenu_type = (uv_submenu_type == 1) ? 2 : 1;
                            menu_updated = true;
                        }
                    } else if (current_menu == 2) {
                        if (!in_submenu) {
                            in_submenu = true;
                            buzzer_submenu_type = 1;
                            menu_updated = true;
                        } else {
                            buzzer_submenu_type = (buzzer_submenu_type == 1) ? 2 : 1;
                            menu_updated = true;
                        }
                    } else if (current_menu == 3) {
                        if (!in_submenu) {
                            in_submenu = true;
                            wifi_submenu_type = 1;
                            menu_updated = true;
                        } else {
                            if (wifi_submenu_type >= 1 && wifi_submenu_type <= 5) {
                                enter_edit_mode(wifi_submenu_type);
                            }
                        }
                    } else if (current_menu == 4) {
                        in_spectral_mode = true;
                        in_submenu = false;
                        as7341_submenu_type = 0;
                        uv_submenu_type = 0;
                        buzzer_submenu_type = 0;
                        wifi_submenu_type = 0;
                        wifi_editing_switch = false;
                        menu_updated = true;
                    } else if (current_menu < MENU_COUNT) {
                        in_submenu = !in_submenu;
                        menu_updated = true;
                    }
                } else {
                    in_spectral_mode = false;
                    in_submenu = false;
                    as7341_submenu_type = 0;
                    uv_submenu_type = 0;
                    buzzer_submenu_type = 0;
                    wifi_submenu_type = 0;
                    menu_updated = true;
                }
            }
        }
    });
    
    // 任务看门狗定时器
    taskWatchdogTicker.attach_ms(1000, task_watchdog);
}

// ========== 数据流模式显示 ==========

void draw_data_stream_mode() {
    u8g2.drawStr(0, 10, "DATA STREAM MODE");
    u8g2.drawHLine(0, 12, 128);
    
    sprintf(str_buf, "Packets: %lu", data_stream_packet_count);
    u8g2.drawStr(0, 26, str_buf);
    
    // 计算实时FPS
    unsigned long duration = millis() - data_stream_start_time;
    float fps = 0;
    if (duration > 0) {
        fps = (float)data_stream_packet_count / (duration / 1000.0);
    }
    sprintf(str_buf, "FPS: %.1f", fps);
    u8g2.drawStr(70, 26, str_buf);
    
    // 显示发送模式
    const char* mode_str = (current_stream_mode == STREAM_MODE_CONTINUOUS) ? "Continuous" : "Fixed";
    u8g2.drawStr(0, 38, mode_str);
    
    if (current_stream_mode == STREAM_MODE_FIXED_COUNT) {
        sprintf(str_buf, "Count: %lu/%lu", stream_count_current, stream_count_target);
        u8g2.drawStr(40, 38, str_buf);
    }
    
    if (stream_paused) {
        u8g2.drawStr(0, 50, "Status: PAUSED");
    } else {
        u8g2.drawStr(0, 50, "Status: RUNNING");
    }
    
    sprintf(str_buf, "Interval: %dms", data_stream_interval);
    u8g2.drawStr(0, 62, str_buf);
}

// ========== 主循环 ==========

void loop() {
    if (data_stream_mode_active) {
        // 数据流模式主循环
        loop_data_stream_mode();
    } else {
        // 本地模式主循环
        loop_local_mode();
    }
}

void loop_data_stream_mode() {
    unsigned long current_time = millis();
    static unsigned long last_command_check = 0;
    static unsigned long last_status_check = 0;
    static unsigned long last_connection_check = 0;
    static unsigned long last_data_send = 0;
    static unsigned long last_queue_process = 0;
    
    // 1. 首先检查并发送UDP数据（最高优先级）
    if (current_time - last_data_send >= data_stream_interval) {
        send_data_stream_packet();
        last_data_send = current_time;
    }
    
    // 2. 处理响应队列（中等优先级）
    if (current_time - last_queue_process > 50) { // 每50ms处理一次队列
        process_response_queue();
        process_status_update_queue();
        last_queue_process = current_time;
    }
    
    // 3. 定期检查目标服务器连接状态（每3秒）
    if (current_time - last_status_check > 3000) {
        if (!targetClient.connected()) {
            target_server_connected = false;
            Serial.println("目标服务器连接断开，尝试重连...");
            if (!connect_to_target_server()) {
                Serial.println("重连失败，继续尝试发送数据...");
            }
        }
        last_status_check = current_time;
    }
    
    // 4. 定期检查WiFi连接状态（每5秒）
    if (current_time - last_connection_check > 5000) {
        if (WiFi.status() != WL_CONNECTED) {
            wifi_connected = false;
            Serial.println("WiFi连接断开，退出数据流模式");
            exit_data_stream_mode();
            return;
        }
        last_connection_check = current_time;
    }
    
    // 5. 处理指令服务器（最低优先级）
    if (current_time - last_command_check > 100) {
        handle_command_server_data_stream_mode();
        last_command_check = current_time;
    }
    
    // 6. 更新显示（每500ms）
    static unsigned long last_display_update = 0;
    if (current_time - last_display_update > 500) {
        menu_updated = true;
        last_display_update = current_time;
    }
    
    if (menu_updated) {
        u8g2.clearBuffer();
        draw_data_stream_mode();
        u8g2.sendBuffer();
        menu_updated = false;
    }
    
    // 短暂延时，避免过于频繁的循环
    delay(2);
}

void loop_local_mode() {
    unsigned long current_time = millis();
    static unsigned long last_command_check = 0;
    static unsigned long last_sensor_check = 0;
    static unsigned long last_wifi_check = 0;
    static unsigned long last_reconnect_check = 0;
    static unsigned long last_queue_process = 0;
    
    // 1. 处理响应队列（高优先级）
    if (current_time - last_queue_process > 50) {
        process_response_queue();
        process_status_update_queue();
        last_queue_process = current_time;
    }
    
    // 2. 处理指令服务器
    if (current_time - last_command_check >= 10) {
        handle_command_server_local_mode();
        last_command_check = current_time;
    }
    
    // 3. 定期检查WiFi连接状态（每500ms）
    if (current_time - last_wifi_check >= 500) {
        check_wifi_connection_status();
        last_wifi_check = current_time;
    }
    
    // 4. 定期检查自动重连（每2秒）
    if (current_time - last_reconnect_check >= 2000) {
        check_auto_reconnect();
        last_reconnect_check = current_time;
    }
    
    // 5. OLED显示更新
    if (menu_updated) {
        u8g2.setPowerSave(0);
        u8g2.clearBuffer();
        
        if (in_spectral_mode) {
            draw_spectral_page_fast();
        } else {
            if (!in_submenu) {
                draw_main_menu_fast();
            } else {
                draw_submenu_fast();
            }
        }
        
        u8g2.sendBuffer();
        menu_updated = false;
    }
    
    // 6. 传感器数据读取
    if (in_spectral_mode && as7341_init_ok && 
        (current_time - last_sensor_read >= SENSOR_READ_INTERVAL)) {
        if (read_spectral_data()) {
            menu_updated = true;
        }
        last_sensor_read = current_time;
    }
    
    delay(2);
}

// ========== 其他必要函数（需要从原代码中保留） ==========

// 以下函数需要从你的原代码中保留，由于篇幅限制这里只列出函数声明：
// 工具函数
bool is_string_empty(const char* str) {
  if (!str || *str == '\0') return true;
  while (*str) {
    if (*str != ' ') return false;
    str++;
  }
  return true;
}

void safe_strcpy(char* dest, const char* src, size_t dest_size) {
  if (!dest || !src || dest_size == 0) return;
  size_t i;
  for (i = 0; i < dest_size - 1 && src[i] != '\0'; i++) {
    dest[i] = src[i];
  }
  dest[i] = '\0';
}

bool is_valid_ip_address(const char* ip) {
  if (is_string_empty(ip)) return false;
  
  IPAddress addr;
  return addr.fromString(ip);
}

// EEPROM函数
void init_eeprom() {
  EEPROM.begin(EEPROM_SIZE);
  delay(10);
  
  uint8_t init_flag = EEPROM.read(ADDR_INIT_FLAG);
  if (init_flag != 0xAA) {
    EEPROM.write(ADDR_INIT_FLAG, 0xAA);
    EEPROM.write(ADDR_AS7341_LED, as7341_led_state);
    EEPROM.write(ADDR_AS7341_BRIGHT, as7341_led_bright);
    EEPROM.write(ADDR_UV_LED, uv_led_state);
    EEPROM.write(ADDR_UV_BRIGHT, uv_led_bright);
    EEPROM.write(ADDR_BUZZER_EN, buzzer_enable);
    EEPROM.write(ADDR_BUZZER_VOL, buzzer_volume);
    EEPROM.write(ADDR_WIFI_ENABLE, wifi_enable);
    
    eeprom_write_string(ADDR_WIFI_SSID, "", WIFI_SSID_MAX_LEN);
    eeprom_write_string(ADDR_WIFI_PASS, "", WIFI_PASS_MAX_LEN);
    eeprom_write_string(ADDR_FIXED_IP, "", IP_ADDR_MAX_LEN);
    eeprom_write_string(ADDR_TARGET_IP, "", IP_ADDR_MAX_LEN);
    
    EEPROM.commit();
    Serial.println("EEPROM initialized with defaults");
  } else {
    as7341_led_state = EEPROM.read(ADDR_AS7341_LED);
    as7341_led_bright = constrain(EEPROM.read(ADDR_AS7341_BRIGHT), 1, 20);
    uv_led_state = EEPROM.read(ADDR_UV_LED);
    uv_led_bright = constrain(EEPROM.read(ADDR_UV_BRIGHT), 1, 20);
    buzzer_enable = EEPROM.read(ADDR_BUZZER_EN);
    buzzer_volume = constrain(EEPROM.read(ADDR_BUZZER_VOL), 1, BUZZER_VOL_MAX);
    wifi_enable = EEPROM.read(ADDR_WIFI_ENABLE);
    
    eeprom_read_string(ADDR_WIFI_SSID, wifi_ssid, WIFI_SSID_MAX_LEN);
    eeprom_read_string(ADDR_WIFI_PASS, wifi_pass, WIFI_PASS_MAX_LEN);
    eeprom_read_string(ADDR_FIXED_IP, fixed_ip, IP_ADDR_MAX_LEN);
    eeprom_read_string(ADDR_TARGET_IP, target_ip, IP_ADDR_MAX_LEN);
    
    if (!is_valid_ip_address(fixed_ip)) {
      memset(fixed_ip, 0, IP_ADDR_MAX_LEN);
    }
    if (!is_valid_ip_address(target_ip)) {
      memset(target_ip, 0, IP_ADDR_MAX_LEN);
    }
    
    Serial.println("EEPROM loaded saved settings");
  }
}

void save_to_eeprom() {
  EEPROM.write(ADDR_AS7341_LED, as7341_led_state);
  EEPROM.write(ADDR_AS7341_BRIGHT, as7341_led_bright);
  EEPROM.write(ADDR_UV_LED, uv_led_state);
  EEPROM.write(ADDR_UV_BRIGHT, uv_led_bright);
  EEPROM.write(ADDR_BUZZER_EN, buzzer_enable);
  EEPROM.write(ADDR_BUZZER_VOL, buzzer_volume);
  EEPROM.write(ADDR_WIFI_ENABLE, wifi_enable);
  
  eeprom_write_string(ADDR_WIFI_SSID, wifi_ssid, WIFI_SSID_MAX_LEN);
  eeprom_write_string(ADDR_WIFI_PASS, wifi_pass, WIFI_PASS_MAX_LEN);
  eeprom_write_string(ADDR_FIXED_IP, fixed_ip, IP_ADDR_MAX_LEN);
  eeprom_write_string(ADDR_TARGET_IP, target_ip, IP_ADDR_MAX_LEN);
  
  EEPROM.commit();
  Serial.println("Settings saved to EEPROM");
}

void eeprom_read_string(int start_addr, char* buffer, int max_len) {
  memset(buffer, 0, max_len);
  for (int i = 0; i < max_len; i++) {
    buffer[i] = EEPROM.read(start_addr + i);
    if (buffer[i] == '\0') break;
    if (buffer[i] < 32 || buffer[i] > 126) {
      buffer[i] = '\0';
      break;
    }
  }
  buffer[max_len - 1] = '\0';
}

void eeprom_write_string(int start_addr, const char* buffer, int max_len) {
  for (int i = 0; i < max_len; i++) {
    if (buffer[i] == '\0') {
      EEPROM.write(start_addr + i, '\0');
      break;
    }
    if (buffer[i] >= 32 && buffer[i] <= 126) {
      EEPROM.write(start_addr + i, buffer[i]);
    } else {
      EEPROM.write(start_addr + i, ' ');
    }
  }
}

// 蜂鸣器函数
void buzzer_stop_callback() {
  analogWrite(BUZZER_PIN, 0);
  buzzer_beeping = false;
  buzzerStopTicker.detach();
}

void buzzer_beep() {
  if (buzzer_enable && !buzzer_beeping) {
    buzzer_beeping = true;
    analogWrite(BUZZER_PIN, BUZZER_VOL_TO_PWM(buzzer_volume));
    buzzerStopTicker.attach_ms(BUZZER_BEEP_DURATION, buzzer_stop_callback);
  }
}

// 错误提示音
void buzzer_error() {
  if (buzzer_enable && !buzzer_beeping) {
    buzzer_beeping = true;
    analogWrite(BUZZER_PIN, BUZZER_VOL_TO_PWM(buzzer_volume));
    delay(50);
    analogWrite(BUZZER_PIN, 0);
    delay(50);
    analogWrite(BUZZER_PIN, BUZZER_VOL_TO_PWM(buzzer_volume));
    delay(50);
    analogWrite(BUZZER_PIN, 0);
    buzzer_beeping = false;
    buzzerStopTicker.detach();
  }
}

// WiFi编辑函数
void enter_edit_mode(int type) {
  disconnect_wifi();
  
  editing_wifi_ssid = false;
  editing_wifi_pass = false;
  editing_fixed_ip = false;
  editing_target_ip = false;
  wifi_editing_switch = false;
  shift_pressed = false;
  
  switch(type) {
    case 1: editing_wifi_ssid = true; break;
    case 2: editing_wifi_pass = true; break;
    case 3: editing_fixed_ip = true; break;
    case 4: editing_target_ip = true; break;
    case 5: wifi_editing_switch = true; break;
  }
  
  wifi_edit_pos = 0;
  current_char_index = 0;
  memset(wifi_edit_buffer, 0, sizeof(wifi_edit_buffer));
  
  if (editing_wifi_ssid) {
    safe_strcpy(wifi_edit_buffer, wifi_ssid, WIFI_SSID_MAX_LEN - 1);
    wifi_edit_pos = strlen(wifi_edit_buffer);
  } else if (editing_wifi_pass) {
    safe_strcpy(wifi_edit_buffer, wifi_pass, WIFI_PASS_MAX_LEN - 1);
    wifi_edit_pos = strlen(wifi_edit_buffer);
  } else if (editing_fixed_ip) {
    safe_strcpy(wifi_edit_buffer, fixed_ip, IP_ADDR_MAX_LEN - 1);
    wifi_edit_pos = strlen(wifi_edit_buffer);
  } else if (editing_target_ip) {
    safe_strcpy(wifi_edit_buffer, target_ip, IP_ADDR_MAX_LEN - 1);
    wifi_edit_pos = strlen(wifi_edit_buffer);
  }
  
  menu_updated = true;
}

void handle_wifi_editing() {
  if (editing_wifi_ssid || editing_wifi_pass || editing_fixed_ip || editing_target_ip) {
    // UP键长按检测 - 进入编辑模式
    if (btn_up.fell()) {
      up_press_start = millis();
      up_is_pressing = true;
      up_long_triggered = false;
    }
    
    // UP键长按处理
    if (up_is_pressing && !btn_up.read()) {
      if (!up_long_triggered && (millis() - up_press_start >= LONG_PRESS_THRESHOLD)) {
        up_long_triggered = true;
        if (!shift_pressed) {
          shift_pressed = true;
          buzzer_beep();
          menu_updated = true;
        }
      }
    }
    
    // UP键释放
    if (btn_up.rose() && up_is_pressing) {
      up_is_pressing = false;
      if (!up_long_triggered && !shift_pressed) {
        buzzer_beep();
        navigate_char_set(1);
      }
      up_long_triggered = false;
    }
    
    // DOWN键长按检测 - 退出编辑模式
    if (btn_down.fell()) {
      down_press_start = millis();
      down_is_pressing = true;
      down_long_triggered = false;
    }
    
    // DOWN键长按处理
    if (down_is_pressing && !btn_down.read()) {
      if (!down_long_triggered && (millis() - down_press_start >= LONG_PRESS_THRESHOLD)) {
        down_long_triggered = true;
        if (shift_pressed) {
          shift_pressed = false;
          buzzer_beep();
          menu_updated = true;
        }
      }
    }
    
    // DOWN键释放
    if (btn_down.rose() && down_is_pressing) {
      down_is_pressing = false;
      if (!down_long_triggered && !shift_pressed) {
        buzzer_beep();
        navigate_char_set(-1);
      }
      down_long_triggered = false;
    }
    
    // 编辑模式下的按键处理
    if (shift_pressed) {
      if (btn_up.fell() && !up_is_pressing) {
        buzzer_beep();
        move_cursor(1);
      }
      
      if (btn_down.fell() && !down_is_pressing) {
        buzzer_beep();
        move_cursor(-1);
      }
      
      if (btn_sel.fell()) {
        buzzer_beep();
        delete_char();
      }
    } else {
      if (btn_sel.fell()) {
        buzzer_beep();
        sel_press_start = millis();
        sel_is_pressing = true;
        long_press_triggered = false;
        sel_was_pressed = true;
      }
      
      if (sel_is_pressing && !btn_sel.read()) {
        if (!long_press_triggered && (millis() - sel_press_start >= LONG_PRESS_THRESHOLD)) {
          long_press_triggered = true;
          save_edited_value();
        }
      }
      
      if (btn_sel.rose() && sel_was_pressed && !long_press_triggered) {
        sel_is_pressing = false;
        sel_was_pressed = false;
        confirm_current_char();
      }
    }
  }
  else if (wifi_editing_switch) {
    if (btn_up.fell()) {
        buzzer_beep();
        if (!wifi_enable) {
            wifi_enable = true;
            // 重置重连计数
            reconnect_attempt_count = 0;
            save_to_eeprom();
            connect_to_wifi();
            menu_updated = true;
        }
    }
    
    if (btn_down.fell()) {
      buzzer_beep();
      if (wifi_enable) {
        wifi_enable = false;
        save_to_eeprom();
        wifiReconnectTicker.detach();
        disconnect_wifi();
        menu_updated = true;
      }
    }
    
    if (btn_sel.fell()) {
      buzzer_beep();
      wifi_editing_switch = false;
      menu_updated = true;
    }
  }
}
void navigate_char_set(int direction) {
  int char_set_size = get_current_char_set_size();
  current_char_index = (current_char_index + direction + char_set_size) % char_set_size;
  menu_updated = true;
}

void move_cursor(int direction) {
  int len = strlen(wifi_edit_buffer);
  
  if (direction > 0) {  // 向右移动
    if (wifi_edit_pos < len) {
      wifi_edit_pos++;
    }
  } else {  // 向左移动
    if (wifi_edit_pos > 0) {
      wifi_edit_pos--;
    }
  }
  
  menu_updated = true;
}

void delete_char() {
  int len = strlen(wifi_edit_buffer);
  
  if (len > 0 && wifi_edit_pos > 0) {
    wifi_edit_pos--;
    
    for (int i = wifi_edit_pos; i < len - 1; i++) {
      wifi_edit_buffer[i] = wifi_edit_buffer[i + 1];
    }
    
    wifi_edit_buffer[len - 1] = '\0';
    menu_updated = true;
  }
}

void confirm_current_char() {
  int max_len = 0;
  
  if (editing_wifi_ssid) max_len = WIFI_SSID_MAX_LEN - 1;
  else if (editing_wifi_pass) max_len = WIFI_PASS_MAX_LEN - 1;
  else max_len = IP_ADDR_MAX_LEN - 1;
  
  const char* char_set = get_current_char_set();
  char selected_char = char_set[current_char_index];
  
  if (wifi_edit_pos < strlen(wifi_edit_buffer)) {
    wifi_edit_buffer[wifi_edit_pos] = selected_char;
    wifi_edit_pos++;
  } else {
    if (strlen(wifi_edit_buffer) < max_len) {
      wifi_edit_buffer[strlen(wifi_edit_buffer)] = selected_char;
      wifi_edit_buffer[strlen(wifi_edit_buffer) + 1] = '\0';
      wifi_edit_pos = strlen(wifi_edit_buffer);
    }
  }
  
  menu_updated = true;
}

void save_edited_value() {
  int len = strlen(wifi_edit_buffer);
  while (len > 0 && wifi_edit_buffer[len - 1] == ' ') {
    len--;
    wifi_edit_buffer[len] = '\0';
  }
  
  if ((editing_fixed_ip || editing_target_ip) && 
      len > 0 && !is_valid_ip_address(wifi_edit_buffer)) {
    buzzer_error();
    menu_updated = true;
    return;
  }
  
  if (editing_wifi_ssid) {
    safe_strcpy(wifi_ssid, wifi_edit_buffer, WIFI_SSID_MAX_LEN - 1);
  } else if (editing_wifi_pass) {
    safe_strcpy(wifi_pass, wifi_edit_buffer, WIFI_PASS_MAX_LEN - 1);
  } else if (editing_fixed_ip) {
    safe_strcpy(fixed_ip, wifi_edit_buffer, IP_ADDR_MAX_LEN - 1);
  } else if (editing_target_ip) {
    safe_strcpy(target_ip, wifi_edit_buffer, IP_ADDR_MAX_LEN - 1);
  }
  
  editing_wifi_ssid = editing_wifi_pass = editing_fixed_ip = editing_target_ip = false;
  wifi_editing_switch = false;
  shift_pressed = false;
  wifi_edit_pos = 0;
  current_char_index = 0;
  memset(wifi_edit_buffer, 0, sizeof(wifi_edit_buffer));
  
  save_to_eeprom();
  reconnect_attempt_count = 0;
  
  if (wifi_enable) {
      wifiReconnectTicker.detach();
      connect_to_wifi();
      // 不再自动启动重连定时器，使用新的重连机制
  }
  
  menu_updated = true;
}

// 显示函数
void draw_edit_screen() {
  if (editing_wifi_ssid) u8g2.drawStr(0, 10, "Edit SSID:");
  else if (editing_wifi_pass) u8g2.drawStr(0, 10, "Edit Password:");
  else if (editing_fixed_ip) u8g2.drawStr(0, 10, "Edit Fixed IP:");
  else if (editing_target_ip) u8g2.drawStr(0, 10, "Edit Target IP:");
  else if (wifi_editing_switch) {
    u8g2.drawStr(0, 10, "WiFi Switch");
    u8g2.drawHLine(0, 12, 128);
    
    sprintf(str_buf, "Status: %s", wifi_enable ? "ON" : "OFF");
    u8g2.drawStr(10, 30, str_buf);
    
    u8g2.drawStr(10, 45, "UP: Turn ON");
    u8g2.drawStr(10, 57, "DOWN: Turn OFF");
    u8g2.drawStr(60, 57, "SEL: Exit");
    return;
  }
  
  u8g2.drawHLine(0, 12, 128);
  
  String display_text = wifi_edit_buffer;
  u8g2.drawStr(0, 24, display_text.c_str());
  
  int cursor_x = wifi_edit_pos * 6;
  u8g2.drawHLine(cursor_x, 26, 5);
  
  u8g2.drawHLine(0, 30, 128);
  
  if (shift_pressed) {
    u8g2.drawStr(0, 42, "Edit Mode:");
    u8g2.drawStr(70, 42, "UP: ->  DOWN: <-");
    u8g2.drawStr(70, 52, "SEL: Delete");
    u8g2.drawStr(0, 58, "Hold DOWN to exit");
  } else {
    u8g2.drawStr(0, 42, "Select:");
    u8g2.setFont(u8g2_font_10x20_tf);
    const char* char_set = get_current_char_set();
    char current_char[2] = {char_set[current_char_index], '\0'};
    u8g2.drawStr(40, 58, current_char);
    u8g2.setFont(u8g2_font_6x10_tf);
    
    u8g2.drawStr(70, 42, "SEL: Add");
    u8g2.drawStr(70, 52, "LONG: Save");
    u8g2.drawStr(0, 58, "Hold UP to edit");
  }
}

void draw_spectral_page_fast() {
  if (current_page == 1) {
    u8g2.drawStr(0, 10, "AS7341 Data");
    u8g2.drawHLine(0, 12, 128);

    if (!as7341_init_ok) {
      u8g2.drawStr(10, 32, "Sensor Not Ready");
    } else {
      for (int i = 0; i < 4; i++) {
        int y_pos = 24 + i * 12;
        sprintf(str_buf, "F%d: %d", i + 1, spectral_data[i]);
        u8g2.drawStr(0, y_pos, str_buf);
      }
      for (int i = 4; i < 8; i++) {
        int y_pos = 24 + (i - 4) * 12;
        sprintf(str_buf, "F%d: %d", i + 1, spectral_data[i]);
        u8g2.drawStr(64, y_pos, str_buf);
      }
    }
    if (data_stream_enabled) {
      u8g2.drawStr(0, 58, "DataStream: ON");
    }
    u8g2.drawTriangle(120, 60, 125, 55, 115, 55);
  }
  else if (current_page == 2) {
    u8g2.drawStr(0, 10, "System Status");
    u8g2.drawHLine(0, 12, 128);

    sprintf(str_buf, "AS7341: %s", as7341_init_ok ? "OK" : "FAIL");
    u8g2.drawStr(10, 26, str_buf);
    
    sprintf(str_buf, "AS7341 LED: %s", as7341_led_state ? "ON" : "OFF");
    u8g2.drawStr(10, 38, str_buf);
    
    sprintf(str_buf, "UV LED: %s", uv_led_state ? "ON" : "OFF");
    u8g2.drawStr(10, 50, str_buf);
    
    sprintf(str_buf, "Buzzer: %s", buzzer_enable ? "ON" : "OFF");
    u8g2.drawStr(10, 62, str_buf);
    
    u8g2.drawTriangle(120, 15, 125, 20, 115, 20);
    u8g2.drawTriangle(120, 60, 125, 55, 115, 55);
  }
  else if (current_page == 3) {
    u8g2.drawStr(0, 10, "WiFi Status");
    u8g2.drawHLine(0, 12, 128);

    sprintf(str_buf, "WiFi: %s", wifi_enable ? "Enabled" : "Disabled");
    u8g2.drawStr(10, 26, str_buf);

    const char* conn_status = "Disconnected";
    if (wifi_connected) conn_status = "Connected";
    else if (wifi_connecting) conn_status = "Connecting";
    sprintf(str_buf, "Status: %s", conn_status);
    u8g2.drawStr(10, 38, str_buf);

    // 添加重连状态信息
    if (wifi_enable && !wifi_connected && !wifi_connecting) {
        if (reconnect_attempt_count >= MAX_RECONNECT_ATTEMPTS) {
            u8g2.drawStr(10, 50, "Max retries reached");
        } else {
            sprintf(str_buf, "Retry: %d/%d", reconnect_attempt_count, MAX_RECONNECT_ATTEMPTS);
            u8g2.drawStr(10, 50, str_buf);
        }
    } else {
        if (!is_string_empty(wifi_ssid)) {
            sprintf(str_buf, "SSID: %s", wifi_ssid);
            u8g2.drawStr(10, 50, str_buf);
        } else {
            u8g2.drawStr(10, 50, "SSID: Not set");
        }
    }

    if (wifi_connected) {
        sprintf(str_buf, "IP: %s", WiFi.localIP().toString().c_str());
        u8g2.drawStr(10, 62, str_buf);
    } else {
        u8g2.drawStr(10, 62, "IP: Not available");
    }
    
    u8g2.drawTriangle(120, 15, 125, 20, 115, 20);
  }
}

void draw_main_menu_fast() {
  u8g2.drawStr(0, 10, "Option Menu");
  u8g2.drawHLine(0, 12, 128);

  for (int i = 0; i < VISIBLE_ITEMS; i++) {
    int menu_index = scroll_offset + i;
    if (menu_index >= MENU_COUNT) break;
    int y_pos = 24 + i * 12;
    
    if (menu_index == current_menu) {
      u8g2.drawStr(0, y_pos, ">");
    }
    u8g2.drawStr(10, y_pos, main_menu[menu_index]);
  }

  if (scroll_offset > 0) {
    u8g2.drawTriangle(120, 15, 125, 20, 115, 20);
  }
  if (scroll_offset < MENU_COUNT - VISIBLE_ITEMS) {
    u8g2.drawTriangle(120, 60, 125, 55, 115, 55);
  }
}

void draw_submenu_fast() {
  u8g2.drawStr(0, 10, main_menu[current_menu]);
  u8g2.drawHLine(0, 12, 128);

  switch (current_menu) {
    case 0:
      if (as7341_submenu_type == 1) {
        u8g2.drawStr(10, 26, "LED Brightness");
        sprintf(str_buf, "Level: %d/20", as7341_led_bright);
        u8g2.drawStr(10, 38, str_buf);
        u8g2.drawStr(10, 50, "UP:+1  DOWN:-1");
      } else if (as7341_submenu_type == 2) {
        u8g2.drawStr(10, 26, "LED Switch");
        sprintf(str_buf, "Status: %s", as7341_led_state ? "ON" : "OFF");
        u8g2.drawStr(10, 38, str_buf);
        u8g2.drawStr(10, 50, "UP:ON  DOWN:OFF");
      }
      u8g2.drawStr(10, 62, "Long SEL: Back");
      break;
    case 1:
      if (uv_submenu_type == 1) {
        u8g2.drawStr(10, 26, "UV Brightness");
        sprintf(str_buf, "Level: %d/20", uv_led_bright);
        u8g2.drawStr(10, 38, str_buf);
        u8g2.drawStr(10, 50, "UP:+1  DOWN:-1");
      } else if (uv_submenu_type == 2) {
        u8g2.drawStr(10, 26, "UV Switch");
        sprintf(str_buf, "Status: %s", uv_led_state ? "ON" : "OFF");
        u8g2.drawStr(10, 38, str_buf);
        u8g2.drawStr(10, 50, "UP:ON  DOWN:OFF");
      }
      u8g2.drawStr(10, 62, "Long SEL: Back");
      break;
    case 2:
      if (buzzer_submenu_type == 1) {
        u8g2.drawStr(10, 26, "Buzzer Volume");
        sprintf(str_buf, "Level: %d/%d", buzzer_volume, BUZZER_VOL_MAX);
        u8g2.drawStr(10, 38, str_buf);
        u8g2.drawStr(10, 50, "UP:+1  DOWN:-1");
        u8g2.drawStr(10, 62, "Beep on key press");
      } else if (buzzer_submenu_type == 2) {
        u8g2.drawStr(10, 26, "Buzzer Switch");
        sprintf(str_buf, "Status: %s", buzzer_enable ? "ON" : "OFF");
        u8g2.drawStr(10, 38, str_buf);
        u8g2.drawStr(10, 50, "UP:ON  DOWN:OFF");
      }
      break;
    case 3:
        if (editing_wifi_ssid || editing_wifi_pass || 
            editing_fixed_ip || editing_target_ip || wifi_editing_switch) {
            draw_edit_screen();
        } else if (wifi_submenu_type == 1) {
            u8g2.drawStr(10, 26, "1. WiFi SSID");
            u8g2.drawStr(10, 38, is_string_empty(wifi_ssid) ? "Not set" : wifi_ssid);
            u8g2.drawStr(10, 50, "SEL: Edit");
            u8g2.drawStr(10, 62, "Long SEL: Back");
        } else if (wifi_submenu_type == 2) {
            u8g2.drawStr(10, 26, "2. WiFi Password");
            u8g2.drawStr(10, 38, is_string_empty(wifi_pass) ? "Not set" : wifi_pass);
            u8g2.drawStr(10, 50, "SEL: Edit");
            u8g2.drawStr(10, 62, "Long SEL: Back");
        } else if (wifi_submenu_type == 3) {
            u8g2.drawStr(10, 26, "3. Fixed IP");
            u8g2.drawStr(10, 38, is_string_empty(fixed_ip) ? "Not set (DHCP)" : fixed_ip);
            u8g2.drawStr(10, 50, "SEL: Edit");
            u8g2.drawStr(10, 62, "Long SEL: Back");
        } else if (wifi_submenu_type == 4) {
            u8g2.drawStr(10, 26, "4. Target IP");
            u8g2.drawStr(10, 38, is_string_empty(target_ip) ? "Not set" : target_ip);
            u8g2.drawStr(10, 50, "SEL: Edit");
            u8g2.drawStr(10, 62, "Port: 6677");
        } else if (wifi_submenu_type == 5) {
            u8g2.drawStr(10, 26, "5. WiFi Switch");
            sprintf(str_buf, "Status: %s", wifi_enable ? "ON" : "OFF");
            u8g2.drawStr(10, 38, str_buf);
            u8g2.drawStr(10, 50, "SEL: Edit");
            u8g2.drawStr(10, 62, "Long SEL: Back");
        } else if (wifi_submenu_type == 6) {  // 新增手动重连选项
            u8g2.drawStr(10, 26, "6. Manual Reconnect");
            u8g2.drawStr(10, 38, "SEL: Reconnect Now");
            u8g2.drawStr(10, 50, "Reset retry count");
            u8g2.drawStr(10, 62, "Long SEL: Back");
        }
        break;
    case 4:
      u8g2.drawStr(10, 38, "Confirm exit?");
      break;
  }
}

void handle_scroll_offset() {
  if (current_menu >= scroll_offset + VISIBLE_ITEMS) {
    scroll_offset = current_menu - VISIBLE_ITEMS + 1;
  } else if (current_menu < scroll_offset) {
    scroll_offset = current_menu;
  }
  scroll_offset = constrain(scroll_offset, 0, max(0, MENU_COUNT - VISIBLE_ITEMS));
}

// 传感器函数
bool read_spectral_data() {
  if (!as7341_init_ok) {
    return false;
  }

  // 第一次测量 - F1-F4通道
  as7341.startMeasure(as7341.eF1F4ClearNIR);
  delay(5); // 短暂延时确保测量完成
  DFRobot_AS7341::sModeOneData_t data1 = as7341.readSpectralDataOne();
  
  // 第二次测量 - F5-F8通道
  as7341.startMeasure(as7341.eF5F8ClearNIR);
  delay(5); // 短暂延时确保测量完成
  DFRobot_AS7341::sModeTwoData_t data2 = as7341.readSpectralDataTwo();

  // 直接赋值，不进行异常判断
  spectral_data[0] = data1.ADF1;
  spectral_data[1] = data1.ADF2;
  spectral_data[2] = data1.ADF3;
  spectral_data[3] = data1.ADF4;
  spectral_data[4] = data2.ADF5;
  spectral_data[5] = data2.ADF6;
  spectral_data[6] = data2.ADF7;
  spectral_data[7] = data2.ADF8;
  
  return true; // 假设读取总是成功
}

// 修改原有的send_command_response函数，改为非阻塞版本
void send_command_response(const char* message) {
    send_command_response_non_blocking(message);
}

// // 响应函数
// void send_command_response(const char* message) {
//   if (currentCommandClient && currentCommandClient.connected()) {
//     String response = "{\"response\":\"";
//     response += message;
//     response += "\"}";
//     currentCommandClient.println(response);
//     Serial.print("发送响应: ");
//     Serial.println(response);
//   }
// }

// 发送数据流统计信息
void send_data_stream_stats() {
  if (!data_stream_mode_active && data_stream_packet_count > 0) {
    unsigned long duration = millis() - data_stream_start_time;
    float fps = (float)data_stream_packet_count / (duration / 1000.0);
    
    String stats = "{\"type\":\"stats\",\"packets\":";
    stats += data_stream_packet_count;
    stats += ",\"duration\":";
    stats += duration;
    stats += ",\"fps\":";
    stats += fps;
    stats += "}";
    
    // 使用targetClient而不是client
    if (targetClient && targetClient.connected()) {
      targetClient.println(stats);
    }
    Serial.println(stats);
  }
}

// 看门狗函数
void task_watchdog() {
  // 检查任务是否超时
  if (wifi_task_running) {
    unsigned long task_duration = millis() - task_start_time;
    if (task_duration > TASK_WATCHDOG_TIMEOUT) {
      Serial.print("看门狗触发：任务'");
      Serial.print(current_task_name);
      Serial.print("'超时（");
      Serial.print(task_duration);
      Serial.println("ms）");
      wifi_task_running = false;
      current_task_name = "";
      // 使用targetClient而不是client
      if (targetClient.connected()) {
        targetClient.stop();
        Serial.println("已强制断开TCP连接");
      }
      menu_updated = true;
    }
  }
  
  // 定期同步WiFi状态
  wl_status_t actual_status = WiFi.status();
  bool new_connected = (actual_status == WL_CONNECTED);

  // 只有当状态真正改变时才更新
  if (new_connected != wifi_connected) {
      Serial.print("WiFi状态变化: ");
      Serial.print(wifi_connected ? "已连接" : "未连接");
      Serial.print(" -> ");
      Serial.println(new_connected ? "已连接" : "未连接");
      
      bool old_connected = wifi_connected;
      wifi_connected = new_connected;
      
      if (new_connected) {
          // 连接成功
          wifi_connecting = false;
          reconnect_attempt_count = 0;
          last_stable_connection = millis();
          
          // 状态从断开变为连接时发送通知（仅在本地模式）
          if (!old_connected && !connection_notified && !data_stream_mode_active) {
              Serial.println("WiFi重新连接成功，发送通知");
              send_connection_notification(true);
          }
      } else {
          // 连接断开
          wifi_connecting = false;
          last_reconnect_attempt = millis();
          
          // 状态从连接变为断开时发送通知
          if (old_connected && connection_notified && !data_stream_mode_active) {
              Serial.println("WiFi连接断开，发送通知");
              send_connection_notification(false);
          }
      }
      
      menu_updated = true;
  }
}

// 字符集函数
const char* get_current_char_set() {
  if (editing_fixed_ip || editing_target_ip) {
    return ip_char_set;
  }
  return normal_char_set;
}

int get_current_char_set_size() {
  if (editing_fixed_ip || editing_target_ip) {
    return ip_char_set_size;
  }
  return normal_char_set_size;
}

// 初始化函数
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("Starting system...");

    // 按键初始化
    btn_up.attach(KEY_UP, INPUT_PULLUP);
    btn_sel.attach(KEY_SEL, INPUT_PULLUP);
    btn_down.attach(KEY_DOWN, INPUT_PULLUP);
    btn_up.interval(10);
    btn_sel.interval(10);
    btn_down.interval(10);

    // 蜂鸣器初始化
    pinMode(BUZZER_PIN, OUTPUT);
    analogWrite(BUZZER_PIN, 0);

    // UV灯初始化
    pinMode(UV_LED_PIN, OUTPUT);
    analogWrite(UV_LED_PIN, 0);

    // OLED初始化
    u8g2.begin();
    u8g2.setFont(u8g2_font_6x10_tf);
    u8g2.setBusClock(400000);
    u8g2.clearBuffer();
    u8g2.drawStr(20, 32, "Initializing...");
    u8g2.sendBuffer();

    // AS7341初始化
    Serial.println("初始化AS7341传感器...");
    if (as7341.begin() == 0) {
      as7341_init_ok = true;
      Serial.println("AS7341 init success");
    } else {
      Serial.println("AS7341 init failed");
    }

    // 初始化EEPROM和WiFi
    init_eeprom();
    WiFi.disconnect();
    WiFi.mode(WIFI_STA);

    // 初始化指令服务器
    commandServer.begin();
    Serial.print("指令服务器启动，端口: ");
    Serial.println(COMMAND_PORT);
    
    // 初始化UDP
    dataStreamUdp.begin(DATA_STREAM_PORT);
    Serial.print("数据流UDP启动，端口: ");
    Serial.println(DATA_STREAM_PORT);

    // 确保所有定时器初始状态
    data_stream_mode_active = false;
    data_stream_enabled = false;
    dataStreamTicker.detach();
    keyScanTicker.detach();
    taskWatchdogTicker.detach();
    wifiReconnectTicker.detach();

    // 恢复硬件状态
    if (as7341_init_ok) {
      as7341.enableLed(as7341_led_state);
      as7341.controlLed(as7341_led_bright);
    }
    if (uv_led_state) {
      analogWrite(UV_LED_PIN, UV_BRIGHT_TO_PWM(uv_led_bright));
    }

    // 初始化本地模式
    init_local_mode();
    
    if (wifi_enable) {
        connect_to_wifi();
        // 移除原有的重连定时器设置，因为现在使用非阻塞方式
        // 连接状态会在主循环中定期检查
        Serial.println("WiFi连接已启动（非阻塞模式）");
    }

    menu_updated = true;
    Serial.println("Setup completed - Settings loaded from EEPROM");
}